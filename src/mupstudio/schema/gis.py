"""Spatial data brought into a project.

A model of a real place starts from things someone else made: a catchment
boundary, a river network, a set of well locations, a digital elevation model.
This is the record of which of those a project uses.

Two decisions shape it.

The files are **copied into the project**, not referenced where they were found.
A project directory is the unit that gets shared, archived and staged to a
cluster, and a model whose boundary lives in someone's Downloads folder is a
model that stops working the moment that folder is tidied.

The **coordinate system comes from the project, not the file**. Shapefiles carry
a .prj that is often absent, sometimes wrong, and occasionally in a form nothing
agrees on. So a source records the CRS it was read as, and the project's own CRS
is what everything is put into — a file that disagrees is reprojected, and one
with no CRS at all is assumed to be already in the project's.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from mupstudio.schema.common import Id

# What a layer is drawn in before anyone chooses. Distinct enough to tell apart
# on a satellite basemap, which is mostly green, brown and grey.
DEFAULT_COLOURS = (
    "#38bdf8",
    "#4ade80",
    "#fbbf24",
    "#f87171",
    "#c084fc",
    "#22d3ee",
    "#fb923c",
)


class SourceBase(BaseModel):
    """What every imported layer has."""

    id: Id
    label: str = ""
    #: Where the copy lives, relative to the project's ``gis`` directory.
    path: str
    #: The CRS the file was read as. None means it carried none and is taken to
    #: be in the project's own.
    crs: str | None = None
    visible: bool = True
    colour: str = DEFAULT_COLOURS[0]
    #: Bounding box in the source CRS: west, south, east, north.
    bounds: tuple[float, float, float, float] | None = None

    @property
    def name(self) -> str:
        return self.label or self.id


class VectorSource(SourceBase):
    """Polygons, lines or points from a shapefile or GeoJSON.

    The geometry type is recorded because it decides what the layer can be used
    for: a polygon can become the model boundary, a line can refine a grid along
    a river, and neither can be a pumping well.
    """

    kind: Literal["vector"] = "vector"
    geometry: Literal["polygon", "line", "point", "mixed"] = "polygon"
    feature_count: int = 0
    #: Attribute names, so a field can be picked without opening the file.
    fields: list[str] = Field(default_factory=list)


class RasterSource(SourceBase):
    """A grid of values: an elevation model, a thickness, a recharge map."""

    kind: Literal["raster"] = "raster"
    width: int = 0
    height: int = 0
    band_count: int = 1
    #: What the file uses for cells with no data, if it says.
    nodata: float | None = None


class PointTableSource(SourceBase):
    """Points from a CSV, with the columns that make them points.

    Kept apart from a vector source because a CSV is not a spatial file: it
    becomes one only once someone says which columns are the coordinates, and
    that choice is worth recording rather than re-guessing.
    """

    kind: Literal["points"] = "points"
    x_column: str
    y_column: str
    label_column: str | None = None
    row_count: int = 0
    fields: list[str] = Field(default_factory=list)


GisSource = Annotated[
    VectorSource | RasterSource | PointTableSource,
    Field(discriminator="kind"),
]


class DataModel(BaseModel):
    """Everything imported into a project, and how the map is set up."""

    sources: list[GisSource] = Field(default_factory=list)
    #: Which basemap is drawn beneath. None draws nothing, which is the default:
    #: a basemap fetches tiles from a third party, and that is a choice to make
    #: rather than one to discover.
    basemap: str | None = None

    @model_validator(mode="after")
    def _ids_are_unique(self) -> DataModel:
        seen: set[str] = set()
        for source in self.sources:
            if source.id in seen:
                raise ValueError(f"two data layers share the id {source.id!r}")
            seen.add(source.id)
        return self

    def source(self, source_id: str) -> GisSource:
        for item in self.sources:
            if item.id == source_id:
                return item
        raise KeyError(f"no data layer {source_id!r}")

    def next_colour(self) -> str:
        """A colour not already in use, so a new layer is distinguishable."""
        used = {item.colour for item in self.sources}
        for colour in DEFAULT_COLOURS:
            if colour not in used:
                return colour
        return DEFAULT_COLOURS[len(self.sources) % len(DEFAULT_COLOURS)]
