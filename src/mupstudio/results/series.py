"""Values through time at chosen cells.

A map shows where something is at one moment; a time series shows what happened
at one place. Both are needed to judge a reactive model, and the second is what
you compare against an observation.

Cells can be named three ways, because a modeller has three different things to
hand: an index from a listing file, a coordinate from a map, or a click.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from mupstudio.grids.mesh import DisvMesh


class CellLookupError(Exception):
    """The cell asked for does not exist in this grid."""


@dataclass(frozen=True)
class CellRef:
    """One cell, with every way of naming it resolved.

    ``cell`` is the index within a layer, which is what MODFLOW calls cell2d on
    a vertex grid and what a structured grid reaches by row and column.
    """

    layer: int
    cell: int
    x: float
    y: float
    row: int | None = None
    column: int | None = None

    def label(self, structured: bool) -> str:
        """How to name this cell to a person."""
        if structured and self.row is not None and self.column is not None:
            return f"L{self.layer + 1} R{self.row + 1} C{self.column + 1}"
        return f"L{self.layer + 1} cell {self.cell + 1}"

    def as_dict(self, structured: bool) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "cell": self.cell,
            "row": self.row,
            "column": self.column,
            "x": self.x,
            "y": self.y,
            "label": self.label(structured),
        }


def by_index(mesh: DisvMesh, layer: int, cell: int) -> CellRef:
    """A cell by its layer and its index within that layer, both zero-based."""
    if not 0 <= layer < mesh.nlay:
        raise CellLookupError(f"layer {layer + 1} is outside 1..{mesh.nlay}")
    if not 0 <= cell < mesh.ncpl:
        raise CellLookupError(f"cell {cell + 1} is outside 1..{mesh.ncpl}")

    x, y = mesh.cell_centers[cell]
    return CellRef(layer=layer, cell=cell, x=float(x), y=float(y))


def by_row_column(mesh: DisvMesh, layer: int, row: int, column: int, ncol: int) -> CellRef:
    """A cell by layer, row and column, for a structured grid.

    Structured grids number cells row-major within a layer, so a row and column
    resolve to one index; the caller supplies the column count because the mesh
    itself no longer distinguishes structured from vertex grids.
    """
    if ncol <= 0:
        raise CellLookupError("this grid has no rows and columns to index by")

    nrow = mesh.ncpl // ncol
    if not 0 <= row < nrow:
        raise CellLookupError(f"row {row + 1} is outside 1..{nrow}")
    if not 0 <= column < ncol:
        raise CellLookupError(f"column {column + 1} is outside 1..{ncol}")

    reference = by_index(mesh, layer, row * ncol + column)
    return CellRef(
        layer=reference.layer,
        cell=reference.cell,
        x=reference.x,
        y=reference.y,
        row=row,
        column=column,
    )


def nearest(mesh: DisvMesh, x: float, y: float, layer: int = 0) -> CellRef:
    """The cell whose centre is closest to a point.

    Nearest centre rather than strict containment: a click just outside the
    grid, or on an edge, should still select the obvious cell instead of
    nothing.
    """
    centers = mesh.cell_centers
    distances = (centers[:, 0] - x) ** 2 + (centers[:, 1] - y) ** 2
    return by_index(mesh, layer, int(np.argmin(distances)))


def with_row_column(reference: CellRef, ncol: int) -> CellRef:
    """Fill in row and column for a cell found some other way."""
    if ncol <= 0:
        return reference
    return CellRef(
        layer=reference.layer,
        cell=reference.cell,
        x=reference.x,
        y=reference.y,
        row=reference.cell // ncol,
        column=reference.cell % ncol,
    )


def extract(values: np.ndarray, reference: CellRef) -> list[float]:
    """One cell's value at every timestep.

    ``values`` is (ntimes, nlay, ncpl), so this is a strided read down the time
    axis rather than a scan: cheap even on a memory-mapped file.
    """
    return [float(item) for item in values[:, reference.layer, reference.cell]]
