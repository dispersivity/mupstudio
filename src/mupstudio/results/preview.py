"""Drawing a model that has not been run.

Results answer "what happened". While a model is being built the question is
"what did I just say", and until now there was no way to ask it: the viewport
only knew how to show a finished run, so the grid, the boundary cells and the
chemistry zones existed as numbers in a form and nowhere else. A wrong row index
stayed invisible until a run came back empty.

So a project compiles to a dataset of the same shape a run produces — a mesh and
a set of named fields — and the same viewport draws it. What it shows is not a
prediction of anything; it is the input, coloured.

Everything here is derived, cheap, and has one timestep. Nothing is stored.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from mupstudio.compile.compiler import CompiledGrid, CompiledModel, compile_project
from mupstudio.grids.mesh import DisvMesh
from mupstudio.schema.project import Project

log = logging.getLogger(__name__)

# Properties worth looking at, and what to call them on screen. The keys are
# what the compiler produces.
PROPERTIES: dict[str, tuple[str, str]] = {
    "k": ("Hydraulic conductivity", "length/time"),
    "k33": ("Vertical conductivity", "length/time"),
    "porosity": ("Porosity", ""),
    "transport_porosity": ("Transport porosity", ""),
    "ss": ("Specific storage", "1/length"),
    "sy": ("Specific yield", ""),
    "strt": ("Starting head", "length"),
    "alh": ("Longitudinal dispersivity", "length"),
    "ath1": ("Transverse dispersivity", "length"),
    "atv": ("Vertical dispersivity", "length"),
    "diffc": ("Diffusion", "length2/time"),
}

# Prefixes that say what a field is, so the UI can group them without parsing
# names it does not control.
BOUNDARY_PREFIX = "boundary:"
CHEMISTRY_PREFIX = "chemistry:"

# What a cell with no value carries.
#
# The renderer's sentinel, not not-a-number. NaN would be the obvious choice and
# is the wrong one: the shader has to test for it, and the only portable test is
# self-inequality, which a driver entitled to assume no NaN exists is entitled to
# optimise away. Metal does. A sentinel is an ordinary float that compares equal
# on every backend.
ABSENT = -1e30


def structured_mesh(grid: CompiledGrid) -> DisvMesh:
    """A renderable mesh from a structured grid.

    The viewport draws one geometry, a set of cell footprints with a top and a
    bottom per layer, whether the grid was structured or a vertex grid. So a
    structured grid is converted rather than given its own render path — the
    same choice the results reader makes, for the same reason.
    """
    x = np.concatenate([[0.0], np.cumsum(grid.delr)]) + grid.origin_x
    # Rows count from the top of the grid downward, which is how MODFLOW
    # numbers them and how a modeller reads a listing file.
    y_edges = np.concatenate([[0.0], np.cumsum(grid.delc)])
    y = (y_edges[-1] - y_edges) + grid.origin_y

    nx, ny = len(x), len(y)
    vertices = np.array([(x[i], y[j]) for j in range(ny) for i in range(nx)], dtype=np.float32)

    corners: list[int] = []
    offsets = [0]
    centers: list[tuple[float, float]] = []
    for row in range(grid.nrow):
        for column in range(grid.ncol):
            # Counter-clockwise in screen terms, which is the winding the
            # renderer's fan triangulation expects.
            top_left = row * nx + column
            corners.extend([top_left, top_left + nx, top_left + nx + 1, top_left + 1])
            offsets.append(len(corners))
            centers.append(
                (
                    float((x[column] + x[column + 1]) / 2),
                    float((y[row] + y[row + 1]) / 2),
                )
            )

    ncpl = grid.nrow * grid.ncol
    tops = np.concatenate([grid.top[None, :, :], grid.botm[:-1]]).reshape(grid.nlay, ncpl)

    return DisvMesh(
        vertices=vertices,
        cell_offsets=np.asarray(offsets, dtype=np.int32),
        cell_indices=np.asarray(corners, dtype=np.int32),
        cell_centers=np.asarray(centers, dtype=np.float32),
        top=tops.astype(np.float32),
        botm=grid.botm.reshape(grid.nlay, ncpl).astype(np.float32),
    )


class PreviewDataset:
    """A project's inputs, as something the viewport can draw.

    One timestep: these are inputs, not a history. A transient boundary is
    shown at its first stress period, which is what "the model as defined"
    means before anything has been solved.
    """

    def __init__(self, model: CompiledModel, name: str = "preview"):
        self.name = name
        self._model = model
        self.mesh = structured_mesh(model.grid)
        self.times = [0.0]
        self._fields = _build_fields(model)

    def component_names(self) -> list[str]:
        return list(self._fields)

    def component_unit(self, component: str) -> str:
        return self._field(component).unit

    def component_range(self, component: str) -> tuple[float, float]:
        """The range of the cells that have a value.

        Boundary fields are mostly not-a-number — a well touches one cell in a
        thousand — so the range has to come from the cells that are set. Taking
        the plain minimum would give NaN and leave the colour scale undefined.
        """
        values = self._field(component).values
        present = values[values != np.float32(ABSENT)]
        if present.size == 0:
            # Nothing is set anywhere. Any range will do so long as it is not
            # empty; the renderer will draw every cell as absent regardless.
            return 0.0, 1.0
        return float(present.min()), float(present.max())

    def all_timesteps(self, component: str) -> np.ndarray:
        return self._field(component).values[None, ...]

    def timestep(self, component: str, index: int) -> np.ndarray:
        if index != 0:
            raise IndexError("a preview has one timestep; there is nothing to scrub")
        return self._field(component).values

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "preview",
            "status": "not run",
            "project": self._model.project.meta.name,
            "engine": self._model.project.meta.engine,
            "warnings": list(self._model.warnings),
            "cells": self.mesh.ncells,
            "fields": [
                {
                    "name": name,
                    "label": field.label,
                    "kind": field.kind,
                    "unit": field.unit,
                    # How much of the grid this covers. A boundary on one cell
                    # and a property on every cell can both have a single value,
                    # and a legend that could not tell them apart would read
                    # "0.67 everywhere" for a single well.
                    "setCells": field.set_cells,
                }
                for name, field in self._fields.items()
            ],
        }

    def _field(self, component: str) -> _Field:
        try:
            return self._fields[component]
        except KeyError:
            known = ", ".join(self._fields) or "none"
            raise KeyError(f"no field {component!r} in this preview (have: {known})") from None


class _Field:
    """One drawable array, and what it is."""

    __slots__ = ("kind", "label", "unit", "values")

    def __init__(self, values: np.ndarray, label: str, kind: str, unit: str = ""):
        # Flattened to (nlay, ncpl), which is what every scalar frame carries.
        flat = np.ascontiguousarray(values.reshape(values.shape[0], -1), dtype=np.float32)
        # Callers build sparse fields with NaN because that is the natural way to
        # say "not set"; it becomes the renderer's sentinel here, once.
        self.values = np.where(np.isnan(flat), np.float32(ABSENT), flat)
        self.label = label
        self.kind = kind
        self.unit = unit

    @property
    def set_cells(self) -> int:
        """How many cells carry a value."""
        return int(np.count_nonzero(self.values != np.float32(ABSENT)))


def _build_fields(model: CompiledModel) -> dict[str, _Field]:
    """Everything about this project worth colouring a cell by."""
    fields: dict[str, _Field] = {}

    for key, (label, unit) in PROPERTIES.items():
        values = model.properties.get(key)
        if values is not None:
            fields[key] = _Field(values, label, kind="property", unit=unit)

    fields.update(_boundary_fields(model))
    fields.update(_chemistry_fields(model))
    return fields


def _boundary_fields(model: CompiledModel) -> dict[str, _Field]:
    """Where each boundary acts, and what it is set to there.

    The value rather than a flag: a well field shows the pumping rate, so a
    sign error or a rate off by a thousand is visible as well as the position.
    Cells the package does not touch are not-a-number, which the renderer draws
    as absent rather than as zero.
    """
    from mupstudio.schema.flow import PACKAGE_NAMES

    shape = model.grid.shape
    fields: dict[str, _Field] = {}

    for boundary in model.boundaries:
        values = np.full(shape, np.nan, dtype=np.float64)
        # The first stress period: a preview shows the model as defined, and a
        # transient series has no single value to draw.
        for record in boundary.spd.get(0, []):
            layer, row, column = record[0]
            values[layer, row, column] = float(record[1])

        package = PACKAGE_NAMES.get(boundary.kind, boundary.kind.upper())
        fields[f"{BOUNDARY_PREFIX}{boundary.id}"] = _Field(
            values,
            label=f"{package} {boundary.id}",
            kind="boundary",
        )

    return fields


def _chemistry_fields(model: CompiledModel) -> dict[str, _Field]:
    """Which assemblage each cell was given, as the number PHREEQC will see.

    Drawn as the number rather than the name because the viewport colours by
    value; the legend maps them back. Zero means the cell has none of that kind,
    which is what an unpainted assemblage looks like to both engines.
    """
    compiled = model.chemistry
    if compiled is None:
        return {}

    labels = {
        "solution": "Solution",
        "equilibrium_phases": "Minerals",
        "exchange": "Exchange",
        "surface": "Surface",
        "kinetics": "Kinetics",
        "gas_phase": "Gas phase",
    }
    fields: dict[str, _Field] = {}

    for block, values in compiled.assemblages.items():
        # A block nothing uses is every cell at zero, which is a flat picture of
        # nothing and only clutters the list.
        if not compiled.numbering.get(block):
            continue
        fields[f"{CHEMISTRY_PREFIX}{block}"] = _Field(
            values.astype(np.float64),
            label=labels.get(block, block),
            kind="chemistry",
        )

    return fields


def preview_of(project: Project, *, root: Any = None) -> PreviewDataset:
    """Compile a project and make it drawable."""
    return PreviewDataset(compile_project(project, root=root), name=project.meta.name)
