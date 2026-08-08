"""Turning imported data into something a map can draw.

The map draws in longitude and latitude, because that is what web tiles are cut
for. The model works in a projected system in metres, because a cell size in
degrees is meaningless. Neither of those is negotiable, so something has to
convert, and this is it.

Reprojection happens here rather than on import: the file keeps the coordinates
it arrived with, and what is sent to the screen is derived. That way a project
whose CRS is corrected later does not need its data re-imported, and nothing on
disk is ever silently moved.

Geometry is also simplified for display. A catchment boundary can carry a
hundred thousand vertices surveyed at centimetre precision; on a screen a
thousand pixels wide, all but a few hundred of them land on top of each other.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mupstudio.gisio.ingest import source_path
from mupstudio.schema.gis import GisSource, PointTableSource, RasterSource, VectorSource

log = logging.getLogger(__name__)

# What the map draws in. Web tiles are cut in Web Mercator, whose geographic
# coordinates are these, so this is what a client can plot without doing any
# projection maths of its own.
DISPLAY_CRS = "EPSG:4326"

# How much of the screen a dropped vertex is allowed to move something. Below
# roughly a pixel nobody can see the difference, and a boundary drawn from a
# survey has thousands of vertices that are all within a pixel of each other.
SIMPLIFY_PIXELS = 0.75
DEFAULT_SCREEN_PIXELS = 1200

# Beyond this a browser struggles to draw the layer at all, and the answer is
# to say so rather than to send it and let the tab lock up.
MAX_FEATURES = 20_000


class PreviewError(Exception):
    """The layer could not be prepared for display."""


def geojson_for(
    project: Path,
    source: GisSource,
    *,
    project_crs: str | None,
    simplify: bool = True,
) -> dict[str, Any]:
    """One layer as GeoJSON in longitude and latitude.

    ``project_crs`` is what a file carrying no CRS of its own is taken to be in.
    A file that carries one is trusted over it: the file knows where it is, and
    the project's CRS is a statement about the model, not about the data.
    """
    if isinstance(source, RasterSource):
        return _raster_outline(source, project_crs)

    frame = _read(project, source, project_crs)

    if len(frame) > MAX_FEATURES:
        raise PreviewError(
            f"{source.name} has {len(frame):,} features, which is more than the map will "
            f"draw ({MAX_FEATURES:,}). Filter or dissolve it before importing."
        )

    frame = frame.to_crs(DISPLAY_CRS)

    if simplify and not frame.empty:
        tolerance = _tolerance(frame)
        if tolerance > 0:
            # preserve_topology keeps polygons closed and stops a simplified
            # boundary crossing itself, which would render as a bow tie.
            frame = frame.set_geometry(frame.geometry.simplify(tolerance, preserve_topology=True))

    return dict(frame.to_geo_dict())


def _read(project: Path, source: GisSource, project_crs: str | None) -> Any:
    """The layer as a GeoDataFrame, with a CRS attached whatever happened."""
    import geopandas as gpd

    path = source_path(project, source)
    if not path.exists():
        raise PreviewError(f"{source.name} points at {source.path}, which is not in the project")

    if isinstance(source, PointTableSource):
        import pandas as pd

        table = pd.read_csv(path)
        table = table.apply(
            lambda column: (
                pd.to_numeric(column, errors="coerce")
                if column.name in (source.x_column, source.y_column)
                else column
            )
        )
        frame = gpd.GeoDataFrame(
            table,
            geometry=gpd.points_from_xy(table[source.x_column], table[source.y_column]),
            crs=source.crs or project_crs,
        )
        return frame[frame.geometry.is_valid & ~frame.geometry.is_empty]

    if isinstance(source, VectorSource):
        frame = gpd.read_file(path)
        if frame.crs is None:
            frame = frame.set_crs(source.crs or project_crs, allow_override=True)
        return frame

    raise PreviewError(f"{source.name} is not something with geometry to draw")


def _tolerance(frame: Any) -> float:
    """How far a vertex may move, in degrees, to be worth dropping.

    Derived from the layer's own extent rather than fixed: a tolerance that is
    right for a catchment is far too coarse for a wellfield a hundred metres
    across, and one right for the wellfield does nothing for the catchment.
    """
    west, south, east, north = frame.total_bounds
    span = max(east - west, north - south)
    if not (span > 0):
        return 0.0
    return float(span / DEFAULT_SCREEN_PIXELS * SIMPLIFY_PIXELS)


def _raster_outline(source: RasterSource, project_crs: str | None) -> dict[str, Any]:
    """A raster's footprint, so it can be shown before it is sampled.

    The pixels are not sent. A digital elevation model is tens of megabytes and
    the question on the Data step is where it covers, not what it says; reading
    values out of it is the Grid step's job.
    """
    if source.bounds is None:
        raise PreviewError(f"{source.name} has no extent recorded")

    west, south, east, north = _to_display(source.bounds, source.crs or project_crs)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": source.name,
                    "width": source.width,
                    "height": source.height,
                    "bands": source.band_count,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]
                    ],
                },
            }
        ],
    }


def _to_display(
    bounds: tuple[float, float, float, float], crs: str | None
) -> tuple[float, float, float, float]:
    """A bounding box in longitude and latitude."""
    if crs is None:
        raise PreviewError(
            "this layer has no coordinate system and the project has none either, so "
            "there is no way to know where it belongs on a map"
        )

    from pyproj import Transformer

    west, south, east, north = bounds
    transformer = Transformer.from_crs(crs, DISPLAY_CRS, always_xy=True)
    # Transforming the box as two corners is wrong for a rotated or strongly
    # curved projection, so all four go through and the extremes are taken.
    xs, ys = transformer.transform(
        [west, east, west, east],
        [south, south, north, north],
    )
    return min(xs), min(ys), max(xs), max(ys)


def extent_of(
    sources: list[GisSource], project_crs: str | None
) -> tuple[float, float, float, float] | None:
    """Everything's extent together, so the map can open looking at the data."""
    boxes = []
    for source in sources:
        if source.bounds is None:
            continue
        try:
            boxes.append(_to_display(source.bounds, source.crs or project_crs))
        except PreviewError:
            continue

    if not boxes:
        return None

    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
