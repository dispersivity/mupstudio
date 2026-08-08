"""How a model is discretised in space.

Two grid kinds to start with. A blank rectilinear grid is what column and box
benchmarks need, and it is the only kind PHT3D accepts. Voronoi and quadtree
grids arrive with the map-based builder and are MF6RTM only.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from mupstudio.schema.selection import CellSelection
from mupstudio.schema.surfaces import (
    ConstantSurface,
    SurfaceSource,
    as_surface,
    constant_value,
)


class AxisSpacing(BaseModel):
    """Cell widths along one axis.

    Either a count of equal cells, or explicit widths when the discretisation
    is graded — finer near a source, coarser at the boundary.
    """

    ncells: int | None = Field(default=None, ge=1)
    total_length: float | None = Field(default=None, gt=0)
    widths: list[float] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _needs_one_description(self) -> AxisSpacing:
        by_count = self.ncells is not None and self.total_length is not None
        by_widths = self.widths is not None

        if by_count == by_widths:
            raise ValueError(
                "give either ncells with total_length, or explicit widths, but not both"
            )
        if self.widths is not None and any(width <= 0 for width in self.widths):
            raise ValueError("every cell width must be positive")
        return self

    def resolve(self) -> list[float]:
        """The cell widths this describes."""
        if self.widths is not None:
            return list(self.widths)
        assert self.ncells is not None and self.total_length is not None
        return [self.total_length / self.ncells] * self.ncells

    @property
    def count(self) -> int:
        return len(self.resolve())

    @property
    def length(self) -> float:
        return sum(self.resolve())


class LayerSpec(BaseModel):
    """One layer's bottom elevation, and how many cells it is split into."""

    name: str | None = None
    bottom: SurfaceSource
    sublayers: int = Field(default=1, ge=1)
    minimum_thickness: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Keep the layer at least this thick where the surfaces cross or pinch out. "
            "Cells that had to be pushed down are reported after the grid is built."
        ),
    )

    @field_validator("bottom", mode="before")
    @classmethod
    def _accept_a_number(cls, value: object) -> object:
        return as_surface(value)


class StructuredGrid(BaseModel):
    """A rectilinear grid: MODFLOW's DIS.

    The only grid PHT3D can use, and the right one for column benchmarks and
    anything laid out on a rectangle.
    """

    kind: Literal["structured"] = "structured"
    origin_x: float = 0.0
    origin_y: float = 0.0
    rotation: float = Field(default=0.0, description="Degrees counterclockwise about the origin")
    columns: AxisSpacing
    rows: AxisSpacing
    top: SurfaceSource
    layers: list[LayerSpec] = Field(min_length=1)
    active: CellSelection | None = Field(
        default=None,
        description=(
            "Which cells are part of the model. Everything if unset. This becomes "
            "IDOMAIN, so cells outside an imported catchment stop taking part in "
            "the flow solution instead of quietly extending it to the bounding box."
        ),
    )

    @field_validator("top", mode="before")
    @classmethod
    def _accept_a_number(cls, value: object) -> object:
        return as_surface(value)

    @model_validator(mode="after")
    def _layers_must_descend(self) -> StructuredGrid:
        """Only where the elevations are numbers.

        A raster or an interpolated surface is not known until the grid is
        built, and two of them can legitimately cross in a corner of the model
        that is inactive anyway. Those are caught during the build, where the
        offending cells can be counted and clamped rather than guessed at.
        """
        elevation = constant_value(self.top)
        for index, layer in enumerate(self.layers):
            bottom = constant_value(layer.bottom)
            if bottom is None or elevation is None:
                elevation = bottom
                continue
            if bottom >= elevation:
                raise ValueError(
                    f"layer {index + 1} has bottom {bottom} at or above the "
                    f"{'model top' if index == 0 else 'layer above'} ({elevation}); "
                    "layers must descend"
                )
            elevation = bottom
        return self

    @property
    def nlay(self) -> int:
        return sum(layer.sublayers for layer in self.layers)

    @property
    def nrow(self) -> int:
        return self.rows.count

    @property
    def ncol(self) -> int:
        return self.columns.count

    @property
    def ncpl(self) -> int:
        return self.nrow * self.ncol

    @property
    def ncells(self) -> int:
        return self.nlay * self.ncpl


GridSpec = Annotated[StructuredGrid, Field(discriminator="kind")]


def column_grid(
    ncells: int,
    length: float,
    *,
    width: float = 1.0,
    thickness: float = 1.0,
    top: float = 0.0,
) -> StructuredGrid:
    """A 1D column: one row, one layer, cells along x.

    The shape most reactive transport benchmarks use. Width and thickness
    default to 1 so cell volumes are simply the cell length, which is what
    makes hand-checking a mass balance possible.
    """
    return StructuredGrid(
        columns=AxisSpacing(ncells=ncells, total_length=length),
        rows=AxisSpacing(ncells=1, total_length=width),
        # The validators accept a bare number; mypy sees only the union.
        top=ConstantSurface(value=top),
        layers=[LayerSpec(bottom=ConstantSurface(value=top - thickness))],
    )
