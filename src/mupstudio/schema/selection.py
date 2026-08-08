"""Which cells something applies to.

Every part of a model that is not uniform has to say where it applies: a well
field, a fixed-head edge, a conductivity zone, an initial water composition.
Those are the same question asked four times, so they get one answer here and
each of them holds a `CellSelection`.

There are three honest ways to point at cells, and a modeller uses all three on
the same model:

  - by index, when the grid is small enough to count and the cells form a block
  - by an explicit list, when they were clicked in the viewport
  - by a shape, when the geometry came from GIS and the cells follow from it

The third is the one that survives a grid change. A river drawn as a line stays
the river after the grid is refined; a list of cell indices taken from that line
becomes wrong the moment a cell size changes, silently. So a shape selection
stores the shape and resolves to cells at compile time, never the other way
round.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from mupstudio.schema.common import Id


class CellRange(BaseModel):
    """Cells named by index, as the outer product of layers, rows and columns.

    Indices are 1-based to match how MODFLOW input reads, since anyone checking
    this against a listing file is counting from one.
    """

    kind: Literal["cells"] = "cells"
    layers: list[int] = Field(min_length=1)
    rows: list[int] = Field(min_length=1)
    columns: list[int] = Field(min_length=1)

    @field_validator("layers", "rows", "columns")
    @classmethod
    def _one_based(cls, value: list[int]) -> list[int]:
        if any(index < 1 for index in value):
            raise ValueError("that is not a cell; indices start at 1, as MODFLOW input does")
        return value


class CellList(BaseModel):
    """Cells named one at a time.

    What clicking in the viewport produces. A block would be a `CellRange`;
    this is for the cases that are not a block — a diagonal fault trace, a
    handful of wells, the cells left over after a boundary was trimmed.
    """

    kind: Literal["list"] = "list"
    indices: list[tuple[int, int, int]] = Field(
        default_factory=list,
        description="(layer, row, column) triples, 1-based",
    )

    @field_validator("indices")
    @classmethod
    def _one_based(cls, value: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
        if any(index < 1 for cell in value for index in cell):
            raise ValueError("that is not a cell; indices start at 1, as MODFLOW input does")
        # Duplicates would write the same MODFLOW record twice, which some
        # packages sum and others reject. Removing them here means neither
        # happens by accident, and clicking a cell twice is not a data error.
        return list(dict.fromkeys(value))


class ShapeSelection(BaseModel):
    """Cells picked out by an imported shape.

    The shape is the truth and the cells are derived, so refining the grid
    re-derives them instead of leaving a stale list behind. This is the only
    selection that stays correct across a regrid.
    """

    kind: Literal["shape"] = "shape"
    source: Id = Field(description="Id of the imported data source to intersect with")
    layers: list[int] = Field(default_factory=lambda: [1], min_length=1)
    rule: Literal["intersects", "centroid"] = Field(
        default="intersects",
        description=(
            "intersects takes every cell the shape touches, centroid only cells whose "
            "centre it covers. Centroid suits an area, intersects suits a line."
        ),
    )
    buffer: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Widen the shape by this distance first, in model length units. A river "
            "drawn as a line with a 50 m buffer catches its floodplain too."
        ),
    )

    @field_validator("layers")
    @classmethod
    def _one_based(cls, value: list[int]) -> list[int]:
        if any(index < 1 for index in value):
            raise ValueError("that is not a layer; indices start at 1, as MODFLOW input does")
        return value


CellSelection = Annotated[
    CellRange | CellList | ShapeSelection,
    Field(discriminator="kind"),
]


def cells(layers: list[int], rows: list[int], columns: list[int]) -> CellRange:
    """Shorthand, since a block of cells is the common case in a small model."""
    return CellRange(layers=layers, rows=rows, columns=columns)


def out_of_range(selection: CellSelection | None, *, nlay: int, nrow: int, ncol: int) -> str | None:
    """The first index outside the grid, described, or None if all fit.

    An index typo is worth catching here rather than in a MODFLOW listing file,
    where it appears as a cell number with no hint of which package put it
    there. A shape selection can only be wrong about layers: which rows and
    columns it covers is the grid's answer, not the user's.
    """
    limits = (("layer", nlay), ("row", nrow), ("column", ncol))

    if selection is None:
        return None

    if selection.kind == "shape":
        return _first_bad(selection.layers, "layer", nlay)

    if selection.kind == "list":
        for cell in selection.indices:
            for value, (axis, limit) in zip(cell, limits, strict=True):
                if not 1 <= value <= limit:
                    return f"{axis} {value}, but the grid has {limit} (indices start at 1)"
        return None

    for axis, limit in limits:
        found = _first_bad(getattr(selection, f"{axis}s"), axis, limit)
        if found:
            return found
    return None


def _first_bad(indices: list[int], axis: str, limit: int) -> str | None:
    for index in indices:
        if not 1 <= index <= limit:
            return f"{axis} {index}, but the grid has {limit} (indices start at 1)"
    return None


def describe(selection: CellSelection | None) -> str:
    """A short phrase for a selection, for a list row or a validation message."""
    if selection is None:
        return "everywhere it applies"
    if selection.kind == "cells":
        count = len(selection.layers) * len(selection.rows) * len(selection.columns)
        return f"{count} cell{'s' if count != 1 else ''} by index"
    if selection.kind == "list":
        count = len(selection.indices)
        return f"{count} cell{'s' if count != 1 else ''} picked"
    layers = ", ".join(str(index) for index in selection.layers)
    return f"from {selection.source} in layer {layers}"
