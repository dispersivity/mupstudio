"""Turning a project definition into the arrays an engine writer needs.

The schema describes a model the way a person thinks about it: a constant here,
a value per zone there, cells named by index. An engine wants arrays of the
right shape and lists of cell ids. This module is the one place that conversion
happens, so both engine writers consume the same resolved form and neither has
to understand the schema's conveniences.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    #: 1 where a cell takes part in the solution, 0 where it does not. MODFLOW 6
    #: calls this IDOMAIN and MODFLOW-2005 calls it IBOUND; both need it, or a
    #: model of a catchment quietly solves flow over its bounding rectangle.
    idomain: np.ndarray | None = None

    @property
    def active_cells(self) -> int:
        return self.ncells if self.idomain is None else int((self.idomain != 0).sum())

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


@dataclass(frozen=True)
class CompiledChemistry:
    """Chemistry as PHREEQC numbers it: one assemblage index per cell.

    ``assemblages`` maps a PHREEQC block name to an int array of shape
    ``(nlay, nrow, ncol)``. Zero means "none of this kind here", which is how
    both PhreeqcRM and PHT3D read an absent assemblage, and is why numbering
    starts at one.

    The definitions are kept alongside, in the same numbering, so a writer can
    emit the blocks and the cell map without going back to the schema.
    """

    assemblages: dict[str, np.ndarray]
    # Block name to the ordered ids whose position gives each one its number.
    numbering: dict[str, list[str]]

    # The PHREEQC blocks a composition can name, in the order a .pqi is written.
    BLOCKS = ("solution", "equilibrium_phases", "exchange", "surface", "kinetics", "gas_phase")

    def number_of(self, block: str, item_id: str) -> int:
        """The PHREEQC number an assemblage was given, or 0 if it has none."""
        order = self.numbering.get(block, [])
        return order.index(item_id) + 1 if item_id in order else 0


@dataclass
class CompiledModel:
    """Everything an engine writer needs, and nothing it has to interpret."""

    project: Project
    grid: CompiledGrid
    properties: dict[str, np.ndarray]
    boundaries: list[CompiledBoundary] = field(default_factory=list)
    chemistry: CompiledChemistry | None = None
    # One zone number per cell, by position in the project's zone list. Zero
    # where no zone covers the cell.
    zones: np.ndarray | None = None
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

    warnings: list[str] = []
    grid = _compile_grid(project.grid, project=project, root=root, warnings=warnings)
    grid = _apply_idomain(grid, project, root=root, warnings=warnings)
    properties = _compile_properties(project, grid, root=root, warnings=warnings)
    boundaries = [
        _compile_boundary(package, project, grid, root=root) for package in project.flow.packages
    ]

    return CompiledModel(
        project=project,
        grid=grid,
        properties=properties,
        boundaries=boundaries,
        chemistry=_compile_chemistry(project, grid, root=root),
        zones=_compile_zones(project, grid, root=root),
        warnings=warnings,
    )


def _apply_idomain(
    grid: CompiledGrid, project: Project, *, root: Path | None, warnings: list[str]
) -> CompiledGrid:
    """Mark the cells the model is actually made of.

    Without this a grid built to fit a catchment still solves flow over the
    whole rectangle it was cut from — the cells outside the boundary have
    conductivity, take recharge and pass water, and the water balance is for a
    model nobody drew.
    """
    active = getattr(project.grid, "active", None)
    if active is None:
        return grid

    cells = _cell_ids(active, project, grid, root=root)
    if not cells:
        raise CompileError(
            "the active-cell selection covers no cells, which would leave a model "
            "with nothing in it"
        )

    idomain = np.zeros(grid.shape, dtype=np.int32)
    idomain[tuple(np.array(axis) for axis in zip(*cells, strict=True))] = 1

    inactive = grid.ncells - int(idomain.sum())
    if inactive:
        share = 100 * inactive / grid.ncells
        warnings.append(
            f"{inactive:,} of {grid.ncells:,} cells ({share:.0f}%) are outside the model "
            "and will not take part in the flow solution"
        )

    return replace(grid, idomain=idomain)


def _compile_zones(project: Project, grid: CompiledGrid, *, root: Path | None) -> np.ndarray:
    """Which zone won each cell, by position in the list, or 0 for none.

    Kept even though the properties are already resolved, because "which zone
    is this cell in" is a question the screen has to answer: it is what the
    zone map draws and what a click reports. Recomputing it from the property
    arrays is not possible once two zones share a value.
    """
    numbers = np.zeros(grid.shape, dtype=np.int32)

    for number, zone in enumerate(project.zones, start=1):
        cells = _cell_ids(zone.cells, project, grid, root=root)
        if not cells:
            continue
        selection = tuple(np.array(axis) for axis in zip(*cells, strict=True))
        numbers[selection] = number

    return numbers


def _compile_chemistry(
    project: Project, grid: CompiledGrid, *, root: Path | None
) -> CompiledChemistry | None:
    """Compositions and zones, as one assemblage number per cell.

    Zones are painted in order, so a later zone overwrites an earlier one where
    they overlap. That is what a zone list means everywhere else in the app, and
    it lets a broad background be corrected by a narrow patch.
    """
    chemistry = project.chemistry
    if not chemistry.enabled or not chemistry.compositions:
        return None

    numbering = {
        "solution": [item.id for item in chemistry.solutions],
        "equilibrium_phases": [item.id for item in chemistry.equilibrium_phases],
        "exchange": [item.id for item in chemistry.exchange],
        "surface": [item.id for item in chemistry.surface],
        "kinetics": [item.id for item in chemistry.kinetics],
        "gas_phase": [item.id for item in chemistry.gas_phases],
    }

    def numbers_for(composition_id: str) -> dict[str, int]:
        composition = chemistry.composition(composition_id)
        return {
            block: (
                numbering[block].index(referenced) + 1
                if (referenced := getattr(composition, block)) in numbering[block]
                else 0
            )
            for block in CompiledChemistry.BLOCKS
        }

    background = numbers_for(chemistry.background) if chemistry.background else {}
    assemblages = {
        block: np.full(grid.shape, background.get(block, 0), dtype=np.int32)
        for block in CompiledChemistry.BLOCKS
    }

    for zone in chemistry.zones:
        numbers = numbers_for(zone.composition)
        cells = _cell_ids(zone.cells, project, grid, root=root)
        if not cells:
            continue
        selection = tuple(np.array(axis) for axis in zip(*cells, strict=True))
        for block, number in numbers.items():
            assemblages[block][selection] = number

    return CompiledChemistry(assemblages=assemblages, numbering=numbering)


def _compile_grid(
    spec: StructuredGrid,
    *,
    project: Project | None = None,
    root: Path | None = None,
    warnings: list[str] | None = None,
) -> CompiledGrid:
    from mupstudio.grids.elevations import ElevationError, resolve_elevations

    delr = np.asarray(spec.columns.resolve(), dtype=np.float64)
    delc = np.asarray(spec.rows.resolve(), dtype=np.float64)

    sources = {source.id: source for source in project.data.sources} if project else {}
    try:
        elevations = resolve_elevations(
            spec,
            project=root,
            sources=sources,
            project_crs=project.meta.crs if project else None,
        )
    except ElevationError as error:
        raise CompileError(str(error)) from error

    if warnings is not None:
        warnings.extend(elevations.warnings)

    return CompiledGrid(
        nlay=elevations.nlay,
        nrow=len(delc),
        ncol=len(delr),
        delr=delr,
        delc=delc,
        top=elevations.top,
        botm=elevations.botm,
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
        return _resolve_field(spec, grid, name=name, project=project, root=root, warnings=warnings)

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

    # Dual porosity is two more property fields, resolved here like the rest so
    # a writer never has to reach back into the schema for them.
    if transport.dual_porosity is not None:
        properties["immobile_porosity"] = resolve(
            "immobile porosity", transport.dual_porosity.immobile_porosity
        )
        properties["transfer_rate"] = resolve(
            "mass transfer rate", transport.dual_porosity.transfer_rate
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
    project: Project,
    root: Path | None,
    warnings: list[str],
) -> np.ndarray:
    """One property, as a (nlay, nrow, ncol) array."""
    if isinstance(spec, ConstantField):
        return np.full(grid.shape, spec.value, dtype=np.float64)

    if isinstance(spec, ZoneField):
        return _paint_zones(spec, grid, name=name, project=project, root=root, warnings=warnings)

    if isinstance(spec, ArrayField):
        return _load_array(spec, grid, name=name, root=root)

    raise CompileError(f"unknown property kind for {name}: {spec!r}")


def _paint_zones(
    spec: ZoneField,
    grid: CompiledGrid,
    *,
    name: str,
    project: Project,
    root: Path | None,
    warnings: list[str],
) -> np.ndarray:
    """The default everywhere, then each zone painted over it in list order.

    Later zones win where they overlap, which is what a layer list means in
    every GIS and the only rule that can be predicted without reading anything.
    A zone with no value for this property is skipped rather than defaulted:
    the sand can have its own conductivity and take the model's porosity.
    """
    values = np.full(grid.shape, spec.default, dtype=np.float64)

    for zone in project.zones:
        if zone.id not in spec.values:
            continue

        cells = _cell_ids(zone.cells, project, grid, root=root)
        if not cells:
            warnings.append(f"{name}: zone {zone.id!r} covers no cells, so it changes nothing")
            continue

        layers, rows, columns = (np.array(axis) for axis in zip(*cells, strict=True))
        values[layers, rows, columns] = spec.values[zone.id]

    return values


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


def _compile_boundary(  # type: ignore[no-untyped-def]
    package, project: Project, grid: CompiledGrid, *, root: Path | None
) -> CompiledBoundary:
    """One package, as stress period data keyed by period index.

    Every entry contributes its own records, so a WEL with six wells at six
    rates writes six records per period and a CHD over an edge writes one per
    cell of that edge. That is what a MODFLOW package file holds.
    """
    nper = project.time.nper

    # The values MODFLOW expects per record, in the order its input defines.
    value_fields = {
        "well": ("rate",),
        "chd": ("head",),
        "recharge": ("rate",),
        "drn": ("elevation", "conductance"),
        "riv": ("stage", "conductance", "bottom"),
        "ghb": ("head", "conductance"),
    }[package.kind]

    # Solute-carrying boundaries carry the inflow concentration as an auxiliary
    # value. MODFLOW's SSM package reads it from there, and it is what mf6rtm
    # replaces per component in a reactive run.
    carries_solute = package.kind in SOLUTE_CARRYING

    spd: dict[int, list[tuple[Any, ...]]] = {period: [] for period in range(nper)}
    seen: set[tuple[int, int, int]] = set()

    for position, entry in enumerate(package.entries, start=1):
        cells = _cell_ids(entry.cells, project, grid, root=root)

        if package.kind == "recharge" and not cells:
            # Recharge is areal: the whole top of the model unless told which
            # cells, which is the only boundary where that default is right.
            cells = [(0, row, col) for row in range(grid.nrow) for col in range(grid.ncol)]

        # Two entries claiming a cell would write two records for it. MODFLOW
        # sums some packages and rejects others, so neither outcome is what
        # anyone drew; the first entry keeps the cell and the clash is named.
        kept = []
        for cell in cells:
            if cell in seen:
                label = entry.label or f"entry {position}"
                raise CompileError(
                    f"in {package.id}, {label} claims cell "
                    f"{cell[0] + 1},{cell[1] + 1},{cell[2] + 1}, which an earlier entry "
                    "already has. A cell can only take one value per package."
                )
            seen.add(cell)
            kept.append(cell)

        concentration = getattr(entry, "concentration", None)
        for period in range(nper):
            values = tuple(_series_value(getattr(entry, field), period) for field in value_fields)
            if carries_solute:
                aux = _series_value(concentration, period) if concentration is not None else 0.0
                spd[period].extend((cell, *values, aux) for cell in kept)
            else:
                spd[period].extend((cell, *values) for cell in kept)

    return CompiledBoundary(
        id=package.id, kind=package.kind, spd=spd, carries_solute=carries_solute
    )


def _cell_ids(  # type: ignore[no-untyped-def]
    selection, project: Project, grid: CompiledGrid, *, root: Path | None
) -> list[tuple[int, int, int]]:
    """Zero-based cell ids from any of the ways a selection can name cells."""
    if selection is None:
        return []

    if selection.kind == "cells":
        return [
            (layer - 1, row - 1, column - 1)
            for layer in selection.layers
            for row in selection.rows
            for column in selection.columns
        ]

    if selection.kind == "list":
        return [(layer - 1, row - 1, column - 1) for layer, row, column in selection.indices]

    return _cells_from_shape(selection, project, grid, root=root)


def _cells_from_shape(  # type: ignore[no-untyped-def]
    selection, project: Project, grid: CompiledGrid, *, root: Path | None
) -> list[tuple[int, int, int]]:
    """A shape's footprint, repeated down the layers it applies to.

    Resolved here rather than stored, so refining the grid re-derives the cells
    instead of leaving a stale list pointing at cells that have moved.
    """
    from mupstudio.grids.select import SelectionError, cells_under_shape

    if root is None:
        raise CompileError(
            f"the selection from {selection.source!r} needs the project directory to "
            "find the shape, and none was given"
        )

    source = next((item for item in project.data.sources if item.id == selection.source), None)
    if source is None:
        raise CompileError(f"no data source {selection.source!r} to select cells with")

    if not isinstance(project.grid, StructuredGrid):
        raise CompileError("selecting cells from a shape needs a structured grid")

    try:
        mask = cells_under_shape(
            root, selection, source, project.grid, project_crs=project.meta.crs
        )
    except SelectionError as error:
        raise CompileError(str(error)) from error

    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        raise CompileError(
            f"{source.name} does not overlap the grid, so it selects no cells. "
            "Check that the model's coordinate system matches the data."
        )

    return [
        (layer - 1, int(row), int(column))
        for layer in selection.layers
        for row, column in zip(rows, columns, strict=True)
    ]


def _series_value(series, period: int) -> float:  # type: ignore[no-untyped-def]
    if series.kind == "constant":
        return float(series.value)
    return float(series.values[period])
