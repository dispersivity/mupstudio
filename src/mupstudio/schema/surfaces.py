"""Where a layer's top or bottom comes from.

A column benchmark has flat layers and one number is the whole answer. A model
of a real place almost never does: the top follows the ground, the base of the
alluvium follows a surface someone interpolated from boreholes, and the layers
between are the first two minus a thickness.

So an elevation is a small tagged union rather than a float, in the same shape
as the property fields and the cell selections — one number, a raster to sample,
scattered points to interpolate, or an offset from the surface above.

The offset case is the one that makes layering bearable. Writing "the ground,
then twenty metres down, then to the base of the alluvium" is three lines here
and three interpolations otherwise, and it is what keeps sub-layers parallel to
the topography instead of flat.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from mupstudio.schema.common import Id


class ConstantSurface(BaseModel):
    """One elevation everywhere. What a column or a box uses."""

    kind: Literal["constant"] = "constant"
    value: float


class RasterSurface(BaseModel):
    """Sampled from an imported raster, at each cell centre.

    Cells the raster does not cover keep `fill`, or the nearest value it does
    have when `fill` is None — a DEM that stops at the catchment edge should
    not punch holes in a grid that extends slightly past it.
    """

    kind: Literal["raster"] = "raster"
    source: Id
    band: int = Field(default=1, ge=1)
    fill: float | None = Field(
        default=None,
        description="Elevation for cells the raster does not cover. Nearest value if unset.",
    )
    offset: float = Field(
        default=0.0, description="Added after sampling, for a surface parallel to another"
    )


class PointsSurface(BaseModel):
    """Interpolated from scattered points: borehole tops, picked contacts.

    Inverse distance weighting rather than kriging: it needs no variogram to be
    fitted first, it never overshoots the data, and a modeller who wants
    kriging has a geostatistics package and will bring their own raster.
    """

    kind: Literal["points"] = "points"
    source: Id
    column: str = Field(description="Which column of the point table holds the elevation")
    power: float = Field(
        default=2.0, gt=0, description="Distance weighting exponent. Higher is more local."
    )
    neighbours: int = Field(
        default=8, ge=1, description="How many nearest points each cell is built from"
    )


class OffsetSurface(BaseModel):
    """A fixed distance below the surface above it.

    Positive `thickness` goes down, because that is the direction layers go and
    "twenty metres thick" should not have to be written as minus twenty.
    """

    kind: Literal["offset"] = "offset"
    thickness: float = Field(gt=0)


SurfaceSource = Annotated[
    ConstantSurface | RasterSurface | PointsSurface | OffsetSurface,
    Field(discriminator="kind"),
]


def as_surface(value: object) -> object:
    """Accept a bare number where a surface is expected.

    Every project written before elevations could vary says `top = 0.0`, and
    a column model still wants to. Both stay valid.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"kind": "constant", "value": float(value)}
    return value


def constant_value(surface: object) -> float | None:
    """The elevation, when it is a plain number, for checks that need one."""
    return surface.value if isinstance(surface, ConstantSurface) else None
