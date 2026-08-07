"""Turning a project definition into the arrays an engine writer needs.

The schema describes a model the way a person thinks about it: a constant here,
a value per zone there, cells named by index. An engine wants arrays of the
right shape and lists of cell ids. This module is the one place that conversion
happens, so both engine writers consume the same resolved form and neither has
to understand the schema's conveniences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mupstudio.schema.common import ArrayField, ConstantField, PropertyField, ZoneField
from mupstudio.schema.flow import SOLUTE_CARRYING
from mupstudio.schema.grid import StructuredGrid
from mupstudio.schema.project import Project

# Conventional ratios of transverse to longitudinal dispersivity, used when the
# project does not state them.
TRANSVERSE_HORIZONTAL_RATIO = 0.1
TRANSVERSE_VERTICAL_RATIO = 0.01


class CompileError(Exception):
    """The project cannot be turned into a runnable model."""


@dataclass(frozen=True)
class CompiledGrid:
    """Discretisation, in the numbers MODFLOW's DIS package wants."""

    nlay: int
    nrow: int
    ncol: int
    delr: np.ndarray
    delc: np.ndarray
    top: np.ndarray
    botm: np.ndarray
    origin_x: float
    origin_y: float
    rotation: float

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.nlay, self.nrow, self.ncol)

    @property
    def ncells(self) -> int:
        return self.nlay * self.nrow * self.ncol


@dataclass(frozen=True)
class CompiledBoundary:
    """One boundary package, as per-period stress period data.

    ``spd`` maps a stress period index to the list of records MODFLOW expects:
    ``((layer, row, col), value, ...)`` with zero-based cell ids, since that is
    what FloPy takes even though the schema uses one-based indices.
    """

    id: str
    kind: str
    spd: dict[int, list[tuple[Any, ...]]]
    # Whether the records carry a trailing concentration for the SSM package.
    carries_solute: bool = False

    @property
    def cell_count(self) -> int:
        return max((len(records) for records in self.spd.values()), default=0)


@dataclass
class CompiledModel:
    """Everything an engine writer needs, and nothing it has to interpret."""

    project: Project
    grid: CompiledGrid
    properties: dict[str, np.ndarray]
    boundaries: list[CompiledBoundary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def nper(self) -> int:
        return self.project.time.nper

    def boundary(self, package_id: str) -> CompiledBoundary:
        for boundary in self.boundaries:
            if boundary.id == package_id:
                return boundary
        raise KeyError(f"no compiled boundary {package_id!r}")


def compile_project(project: Project, *, root: Path | None = None) -> CompiledModel:
    """Resolve a project into arrays and cell lists.

    ``root`` is the project directory, needed only when a property points at an
    array file.
    """
    if not isinstance(project.grid, StructuredGrid):
        raise CompileError(f"cannot compile a {project.grid.kind} grid yet")

    grid = _compile_grid(project.grid)
    warnings: list[str] = []
    properties = _compile_properties(project, grid, root=root, warnings=warnings)
    boundaries = [_compile_boundary(package, project, grid) for package in project.flow.packages]

    return CompiledModel(
        project=project,
        grid=grid,
        properties=properties,
        boundaries=boundaries,
        warnings=warnings,
    )


def _compile_grid(spec: StructuredGrid) -> CompiledGrid:
    delr = np.asarray(spec.columns.resolve(), dtype=np.float64)
    delc = np.asarray(spec.rows.resolve(), dtype=np.float64)
    nrow, ncol = len(delc), len(delr)

    # A layer with sublayers is split into equal thicknesses between its top and
    # its bottom, which is what "3 sublayers" is understood to mean.
    bottoms: list[float] = []
    elevation = spec.top
    for layer in spec.layers:
        step = (elevation - layer.bottom) / layer.sublayers
        for sublayer in range(layer.sublayers):
            bottoms.append(elevation - step * (sublayer + 1))
        elevation = layer.bottom

    nlay = len(bottoms)
    return CompiledGrid(
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=np.full((nrow, ncol), spec.top, dtype=np.float64),
        botm=np.stack([np.full((nrow, ncol), bottom, dtype=np.float64) for bottom in bottoms]),
        origin_x=spec.origin_x,
        origin_y=spec.origin_y,
        rotation=spec.rotation,
    )


def _compile_properties(
    project: Project,
    grid: CompiledGrid,
    *,
    root: Path | None,
    warnings: list[str],
) -> dict[str, np.ndarray]:
    flow = project.flow.properties

    def resolve(name: str, spec: PropertyField) -> np.ndarray:
        return _resolve_field(spec, grid, name=name, root=root, warnings=warnings)

    properties = {
        "k": resolve("k", flow.k),
        "porosity": resolve("porosity", flow.porosity),
        "ss": resolve("specific_storage", flow.specific_storage),
        "sy": resolve("specific_yield", flow.specific_yield),
        "strt": resolve("starting_head", flow.starting_head),
    }
    # Vertical conductivity defaults to the horizontal value, which is what
    # MODFLOW assumes when K33 is absent.
    properties["k33"] = resolve("k33", flow.k33) if flow.k33 is not None else properties["k"].copy()

    transport = project.transport
    properties["transport_porosity"] = (
        resolve("transport porosity", transport.porosity)
        if transport.porosity is not None
        else properties["porosity"].copy()
    )

    dispersion = transport.dispersion
    properties["alh"] = resolve("longitudinal dispersivity", dispersion.longitudinal)
    properties["diffc"] = resolve("diffusion", dispersion.diffusion)

    # MODFLOW requires a transverse dispersivity wherever a longitudinal one is
    # given, so the conventional ratios are applied rather than left to fail at
    # run time. A tenth and a hundredth of the longitudinal value are the usual
    # starting points, and both are overridable.
    properties["ath1"] = (
        resolve("transverse horizontal dispersivity", dispersion.transverse_horizontal)
        if dispersion.transverse_horizontal is not None
        else properties["alh"] * TRANSVERSE_HORIZONTAL_RATIO
    )
    properties["atv"] = (
        resolve("transverse vertical dispersivity", dispersion.transverse_vertical)
        if dispersion.transverse_vertical is not None
        else properties["alh"] * TRANSVERSE_VERTICAL_RATIO
    )

    return properties


def _resolve_field(
    spec: PropertyField,
    grid: CompiledGrid,
    *,
    name: str,
    root: Path | None,
    warnings: list[str],
) -> np.ndarray:
    """One property, as a (nlay, nrow, ncol) array."""
    if isinstance(spec, ConstantField):
        return np.full(grid.shape, spec.value, dtype=np.float64)

    if isinstance(spec, ZoneField):
        # Zone geometry arrives with the map-based builder; until then a zone
        # field resolves to its default and says so rather than failing, so a
        # project written for later use still runs now.
        if spec.values:
            warnings.append(
                f"{name} names {len(spec.values)} zone(s), but zone geometry is not "
                f"supported yet; using the default {spec.default}"
            )
        return np.full(grid.shape, spec.default, dtype=np.float64)

    if isinstance(spec, ArrayField):
        return _load_array(spec, grid, name=name, root=root)

    raise CompileError(f"unknown property kind for {name}: {spec!r}")


def _load_array(
    spec: ArrayField, grid: CompiledGrid, *, name: str, root: Path | None
) -> np.ndarray:
    if root is None:
        raise CompileError(
            f"{name} points at the array {spec.path}, but no project directory was given"
        )

    path = (root / spec.path).resolve()
    if not path.exists():
        raise CompileError(f"{name} points at {spec.path}, which does not exist")

    values = np.load(path) if path.suffix == ".npy" else np.loadtxt(path)

    # Accept a full 3D array, one 2D layer to broadcast, or a flat list.
    if values.shape == grid.shape:
        return values.astype(np.float64)
    if values.shape == (grid.nrow, grid.ncol):
        return np.broadcast_to(values, grid.shape).astype(np.float64).copy()
    if values.size == grid.ncells:
        return values.reshape(grid.shape).astype(np.float64)

    raise CompileError(
        f"{name} array {spec.path} has shape {values.shape}, which does not fit a "
        f"{grid.nlay}x{grid.nrow}x{grid.ncol} grid"
    )


def _compile_boundary(package, project: Project, grid: CompiledGrid) -> CompiledBoundary:  # type: ignore[no-untyped-def]
    """One package, as stress period data keyed by period index."""
    nper = project.time.nper
    cells = _cell_ids(package, grid)

    if package.kind == "recharge":
        # Recharge is areal: one record per top-layer cell, or per named cell.
        cells = cells or [(0, row, col) for row in range(grid.nrow) for col in range(grid.ncol)]

    series = getattr(package, "rate" if package.kind in {"well", "recharge"} else "head")
    concentration = getattr(package, "concentration", None)

    # Solute-carrying boundaries carry the inflow concentration as an auxiliary
    # value. MODFLOW's SSM package reads it from there, and it is what mf6rtm
    # replaces per component in a reactive run.
    carries_solute = package.kind in SOLUTE_CARRYING

    spd: dict[int, list[tuple[Any, ...]]] = {}
    for period in range(nper):
        value = _series_value(series, period)
        if carries_solute:
            aux = _series_value(concentration, period) if concentration is not None else 0.0
            spd[period] = [(cell, value, aux) for cell in cells]
        else:
            spd[period] = [(cell, value) for cell in cells]

    return CompiledBoundary(
        id=package.id, kind=package.kind, spd=spd, carries_solute=carries_solute
    )


def _cell_ids(package, grid: CompiledGrid) -> list[tuple[int, int, int]]:  # type: ignore[no-untyped-def]
    """Zero-based cell ids from the schema's one-based selection."""
    selection = getattr(package, "cells", None)
    if selection is None:
        return []

    return [
        (layer - 1, row - 1, column - 1)
        for layer in selection.layers
        for row in selection.rows
        for column in selection.columns
    ]


def _series_value(series, period: int) -> float:  # type: ignore[no-untyped-def]
    if series.kind == "constant":
        return float(series.value)
    return float(series.values[period])
