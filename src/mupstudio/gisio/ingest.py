"""Reading spatial files into a project.

Importing does three things: work out what the file is, copy it into the
project so the project stays self-contained, and record enough about it that
the rest of the app never has to open it again to answer a simple question.

A shapefile is not one file. It is a .shp with a .dbf beside it, usually a .shx,
often a .prj, and the set is useless if any of the first three is missing. So
importing one takes the sidecars with it, and a zip of a shapefile is unpacked
rather than refused — that is how shapefiles actually arrive.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mupstudio.schema.gis import (
    GisSource,
    PointTableSource,
    RasterSource,
    VectorSource,
)

log = logging.getLogger(__name__)

GIS_DIR = "gis"

# What a shapefile needs beside it. The first three are required; a shapefile
# missing its .dbf has no attributes and most readers refuse it outright.
SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".sbn", ".sbx")

VECTOR_SUFFIXES = {".shp", ".geojson", ".json", ".gpkg"}
RASTER_SUFFIXES = {".tif", ".tiff", ".asc", ".vrt", ".img"}
TABLE_SUFFIXES = {".csv", ".txt"}

# Shapely's geometry names, grouped the way the app cares about them.
GEOMETRY_KINDS = {
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
    "LineString": "line",
    "MultiLineString": "line",
    "LinearRing": "line",
    "Point": "point",
    "MultiPoint": "point",
}


class ImportError_(Exception):
    """The file could not be imported, with a reason worth showing."""


@dataclass
class Imported:
    """A source, and anything the user should know about how it was read."""

    source: GisSource
    warnings: list[str]


def import_file(
    path: Path,
    project: Path,
    *,
    source_id: str,
    label: str = "",
    colour: str = "#38bdf8",
    x_column: str | None = None,
    y_column: str | None = None,
    crs: str | None = None,
) -> Imported:
    """Bring one file into a project.

    ``crs`` is used when the file carries none of its own, which is common for
    CSVs and not rare for shapefiles.
    """
    path = Path(path)
    if not path.exists():
        raise ImportError_(f"{path} does not exist")

    suffix = path.suffix.lower()
    if suffix == ".zip":
        path = _unpack(path, project)
        suffix = path.suffix.lower()

    destination = _stage(path, project)

    if suffix in VECTOR_SUFFIXES:
        return _read_vector(destination, source_id, label, colour, crs)
    if suffix in RASTER_SUFFIXES:
        return _read_raster(destination, source_id, label, colour, crs)
    if suffix in TABLE_SUFFIXES:
        return _read_table(destination, source_id, label, colour, crs, x_column, y_column)

    known = ", ".join(sorted(VECTOR_SUFFIXES | RASTER_SUFFIXES | TABLE_SUFFIXES))
    raise ImportError_(f"{path.name} is not a kind of file this reads (it knows: {known})")


def _stage(path: Path, project: Path) -> Path:
    """Copy a file, and a shapefile's sidecars, into the project.

    Returns where the copy landed. A file already inside the project's gis
    directory is left where it is rather than copied over itself.
    """
    directory = Path(project) / GIS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / path.name

    if path.resolve() == destination.resolve():
        return destination

    shutil.copyfile(path, destination)

    if path.suffix.lower() == ".shp":
        for part in SHAPEFILE_PARTS:
            sidecar = path.with_suffix(part)
            if sidecar.exists() and sidecar != path:
                shutil.copyfile(sidecar, directory / sidecar.name)

    return destination


def _unpack(archive: Path, project: Path) -> Path:
    """Pull a shapefile out of a zip, which is how they are usually shared."""
    scratch = Path(project) / GIS_DIR / f".{archive.stem}"
    scratch.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as bundle:
        # Entries are extracted by base name so a zip cannot write outside the
        # directory it is being unpacked into.
        for entry in bundle.infolist():
            if entry.is_dir():
                continue
            name = Path(entry.filename).name
            if not name:
                continue
            with bundle.open(entry) as source, open(scratch / name, "wb") as target:
                shutil.copyfileobj(source, target)

    shapefiles = sorted(scratch.glob("*.shp"))
    if not shapefiles:
        raise ImportError_(f"{archive.name} holds no shapefile")
    if len(shapefiles) > 1:
        names = ", ".join(item.name for item in shapefiles)
        raise ImportError_(f"{archive.name} holds more than one shapefile ({names}); unzip it")
    return shapefiles[0]


def _read_vector(path: Path, source_id: str, label: str, colour: str, crs: str | None) -> Imported:
    import geopandas as gpd

    try:
        frame = gpd.read_file(path)
    except Exception as error:
        raise ImportError_(f"{path.name} could not be read: {error}") from error

    warnings: list[str] = []
    if frame.crs is None:
        warnings.append(
            f"{path.name} says nothing about its coordinate system; it is being read as "
            f"{crs or 'the project CRS'}"
        )
    found = str(frame.crs) if frame.crs is not None else crs

    kinds = {GEOMETRY_KINDS.get(name, "mixed") for name in frame.geom_type.dropna().unique()}
    geometry = kinds.pop() if len(kinds) == 1 else "mixed"
    if geometry == "mixed" and kinds:
        warnings.append(f"{path.name} mixes geometry types, which limits what it can be used for")

    bounds = tuple(float(value) for value in frame.total_bounds) if len(frame) else None

    return Imported(
        source=VectorSource(
            id=source_id,
            label=label or path.stem,
            path=path.name,
            crs=found,
            colour=colour,
            geometry=geometry,  # type: ignore[arg-type]
            feature_count=len(frame),
            fields=[str(name) for name in frame.columns if name != frame.geometry.name],
            bounds=bounds,  # type: ignore[arg-type]
        ),
        warnings=warnings,
    )


def _read_raster(path: Path, source_id: str, label: str, colour: str, crs: str | None) -> Imported:
    import rasterio

    try:
        with rasterio.open(path) as dataset:
            found = str(dataset.crs) if dataset.crs else crs
            bounds = (
                float(dataset.bounds.left),
                float(dataset.bounds.bottom),
                float(dataset.bounds.right),
                float(dataset.bounds.top),
            )
            source = RasterSource(
                id=source_id,
                label=label or path.stem,
                path=path.name,
                crs=found,
                colour=colour,
                width=int(dataset.width),
                height=int(dataset.height),
                band_count=int(dataset.count),
                nodata=float(dataset.nodata) if dataset.nodata is not None else None,
                bounds=bounds,
            )
            warnings = (
                []
                if dataset.crs
                else [f"{path.name} carries no coordinate system; it is being read as {crs}"]
            )
    except ImportError_:
        raise
    except Exception as error:
        raise ImportError_(f"{path.name} could not be read: {error}") from error

    return Imported(source=source, warnings=warnings)


def _read_table(
    path: Path,
    source_id: str,
    label: str,
    colour: str,
    crs: str | None,
    x_column: str | None,
    y_column: str | None,
) -> Imported:
    """A CSV of points, once someone says which columns the coordinates are in.

    Guessed when not given, because the usual names are few and being wrong is
    visible immediately — the points land somewhere absurd on the map.
    """
    import pandas as pd

    try:
        table = pd.read_csv(path)
    except Exception as error:
        raise ImportError_(f"{path.name} could not be read: {error}") from error

    columns = [str(name) for name in table.columns]
    x_name = x_column or _guess_column(columns, ("x", "easting", "lon", "longitude", "east"))
    y_name = y_column or _guess_column(columns, ("y", "northing", "lat", "latitude", "north"))

    if x_name is None or y_name is None:
        raise ImportError_(
            f"{path.name} needs the columns holding the coordinates naming; it has: "
            f"{', '.join(columns)}"
        )

    warnings: list[str] = []
    if x_column is None or y_column is None:
        warnings.append(f"read {x_name} and {y_name} as the coordinates")

    points = table[[x_name, y_name]].apply(pd.to_numeric, errors="coerce").dropna()
    if points.empty:
        raise ImportError_(f"{x_name} and {y_name} in {path.name} hold no usable numbers")
    if len(points) < len(table):
        warnings.append(f"{len(table) - len(points)} row(s) had no usable coordinates")

    return Imported(
        source=PointTableSource(
            id=source_id,
            label=label or path.stem,
            path=path.name,
            crs=crs,
            colour=colour,
            x_column=x_name,
            y_column=y_name,
            row_count=len(points),
            fields=columns,
            bounds=(
                float(points[x_name].min()),
                float(points[y_name].min()),
                float(points[x_name].max()),
                float(points[y_name].max()),
            ),
        ),
        warnings=warnings,
    )


def _guess_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {name.lower().strip(): name for name in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def source_path(project: Path, source: Any) -> Path:
    """Where a source's file actually is."""
    return Path(project) / GIS_DIR / str(source.path)
