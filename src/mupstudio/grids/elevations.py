"""Turning layer surfaces into the elevation arrays MODFLOW wants.

Two jobs. The first is sampling: a raster, a set of scattered points or a plain
number, each becoming one value per cell of the plan view. The second is making
the result a legal grid, because nothing guarantees that two surfaces sampled
independently stay in order — a DEM and an interpolated bedrock pick will cross
wherever the bedrock outcrops, and MODFLOW will not run on a layer with a
negative thickness.

Crossing surfaces are clamped rather than refused. A model of a real place
almost always has a few cells where the units pinch out, and stopping the build
over eleven cells out of a hundred thousand helps nobody. What matters is that
the clamping is counted and reported, so "my layer is 0.1 m thick here" is a
thing the screen said rather than a thing discovered three days later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mupstudio.schema.gis import GisSource, PointTableSource, RasterSource
from mupstudio.schema.grid import StructuredGrid
from mupstudio.schema.surfaces import (
    ConstantSurface,
    OffsetSurface,
    PointsSurface,
    RasterSurface,
)


class ElevationError(Exception):
    """A surface that cannot be turned into elevations, said in the user's terms."""


@dataclass
class LayerElevations:
    """The elevations a grid was built with, and what had to be adjusted."""

    #: (nrow, ncol) model top.
    top: np.ndarray
    #: (nlay, nrow, ncol) bottom of each layer, sub-layers already split out.
    botm: np.ndarray
    warnings: list[str] = field(default_factory=list)

    @property
    def nlay(self) -> int:
        return int(self.botm.shape[0])


def resolve_elevations(
    grid: StructuredGrid,
    *,
    project: Path | None = None,
    sources: dict[str, GisSource] | None = None,
    project_crs: str | None = None,
) -> LayerElevations:
    """Every layer surface, sampled onto the grid and put in order."""
    sources = sources or {}
    warnings: list[str] = []
    shape = (grid.nrow, grid.ncol)

    top = _sample(grid.top, grid, project, sources, project_crs, above=None, name="model top")

    bottoms: list[np.ndarray] = []
    above = top
    for index, layer in enumerate(grid.layers, start=1):
        name = layer.name or f"layer {index}"
        bottom = _sample(layer.bottom, grid, project, sources, project_crs, above=above, name=name)

        # Clamp before splitting into sub-layers, so a pinch-out is fixed once
        # rather than once per sub-layer at a fraction of the thickness each.
        bottom, clamped = _keep_below(above, bottom, layer.minimum_thickness)
        if clamped:
            warnings.append(
                f"{name}: {clamped:,} cell{'s' if clamped != 1 else ''} reached or crossed the "
                f"surface above and {'was' if clamped == 1 else 'were'} pushed down to keep a "
                f"thickness of {layer.minimum_thickness or MIN_THICKNESS:g}"
            )

        # Sub-layers divide the interval equally, following both surfaces rather
        # than sitting flat, which is the point of splitting a unit at all.
        for sublayer in range(1, layer.sublayers + 1):
            bottoms.append(above + (bottom - above) * (sublayer / layer.sublayers))
        above = bottom

    return LayerElevations(
        top=top.astype(np.float64),
        botm=np.stack(bottoms).astype(np.float64)
        if bottoms
        else np.zeros((0, *shape), dtype=np.float64),
        warnings=warnings,
    )


# What a layer is given when it would otherwise be flat or inverted and no
# minimum was asked for. Small enough not to distort a model, large enough that
# MODFLOW's own thickness checks do not trip on it.
MIN_THICKNESS = 0.01


def _keep_below(above: np.ndarray, bottom: np.ndarray, minimum: float) -> tuple[np.ndarray, int]:
    """Push a surface down wherever it reaches the one above it."""
    floor = above - max(minimum, MIN_THICKNESS)
    crossing = bottom > floor
    return np.where(crossing, floor, bottom), int(crossing.sum())


def _sample(
    surface: Any,
    grid: StructuredGrid,
    project: Path | None,
    sources: dict[str, GisSource],
    project_crs: str | None,
    *,
    above: np.ndarray | None,
    name: str,
) -> np.ndarray:
    shape = (grid.nrow, grid.ncol)

    if isinstance(surface, ConstantSurface):
        return np.full(shape, surface.value, dtype=np.float64)

    if isinstance(surface, OffsetSurface):
        if above is None:
            raise ElevationError(
                f"{name} is an offset from the surface above, but it is the model top, "
                "which has nothing above it"
            )
        return above - surface.thickness

    if isinstance(surface, RasterSurface):
        return _from_raster(surface, grid, project, sources, project_crs, name=name)

    if isinstance(surface, PointsSurface):
        return _from_points(surface, grid, project, sources, project_crs, name=name)

    raise ElevationError(f"{name} has an elevation kind this version does not know: {surface!r}")


def cell_centres(grid: StructuredGrid) -> tuple[np.ndarray, np.ndarray]:
    """World coordinates of every cell centre, as two (nrow, ncol) arrays.

    Columns run west to east from the origin and rows north to south, as
    MODFLOW numbers them; rotation is applied last, about the origin.
    """
    widths = np.asarray(grid.columns.resolve(), dtype=float)
    heights = np.asarray(grid.rows.resolve(), dtype=float)

    xs = np.cumsum(widths) - widths / 2
    ys = float(heights.sum()) - (np.cumsum(heights) - heights / 2)
    local_x, local_y = np.meshgrid(xs, ys)

    if grid.rotation:
        angle = np.radians(grid.rotation)
        cos, sin = np.cos(angle), np.sin(angle)
        local_x, local_y = (
            local_x * cos - local_y * sin,
            local_x * sin + local_y * cos,
        )

    return local_x + grid.origin_x, local_y + grid.origin_y


def _from_raster(
    surface: RasterSurface,
    grid: StructuredGrid,
    project: Path | None,
    sources: dict[str, GisSource],
    project_crs: str | None,
    *,
    name: str,
) -> np.ndarray:
    import rasterio
    from rasterio.warp import transform as warp_transform

    from mupstudio.gisio.ingest import source_path

    source = sources.get(surface.source)
    if source is None:
        raise ElevationError(f"{name} reads {surface.source!r}, which this project does not have")
    if not isinstance(source, RasterSource):
        raise ElevationError(f"{name} reads {source.name}, which is not a raster")
    if project is None:
        raise ElevationError(f"{name} reads a raster, but no project directory was given")

    path = source_path(project, source)
    if not path.exists():
        raise ElevationError(f"{name} reads {source.path}, which is missing")

    x, y = cell_centres(grid)

    with rasterio.open(path) as dataset:
        if surface.band > dataset.count:
            raise ElevationError(
                f"{name} asks for band {surface.band} of {source.name}, which has {dataset.count}"
            )

        # The grid is laid out in the project's coordinate system; the raster
        # may be in another. Moving the sample points is far cheaper than
        # reprojecting the raster, and loses nothing: this is a point lookup.
        sample_x, sample_y = x.ravel(), y.ravel()
        if project_crs and dataset.crs and str(dataset.crs) != project_crs:
            sample_x, sample_y = warp_transform(
                project_crs, dataset.crs, list(sample_x), list(sample_y)
            )
            sample_x, sample_y = np.asarray(sample_x), np.asarray(sample_y)

        values = np.fromiter(
            (item[surface.band - 1] for item in dataset.sample(zip(sample_x, sample_y, strict=True))),
            dtype=np.float64,
            count=sample_x.size,
        )
        nodata = dataset.nodata

    missing = ~np.isfinite(values)
    if nodata is not None:
        missing |= values == nodata

    if missing.any():
        if surface.fill is not None:
            values[missing] = surface.fill
        elif missing.all():
            raise ElevationError(
                f"{name}: {source.name} covers none of the grid. Check that the model's "
                "coordinate system matches the raster's."
            )
        else:
            # Nearest covered cell, so a DEM that stops just short of the grid
            # edge does not punch holes in the model.
            values[missing] = _nearest(x.ravel(), y.ravel(), values, missing)

    return values.reshape(grid.nrow, grid.ncol) + surface.offset


def _nearest(x: np.ndarray, y: np.ndarray, values: np.ndarray, missing: np.ndarray) -> np.ndarray:
    """Fill gaps from the closest cell that has a value."""
    known = ~missing
    tree_x, tree_y = x[known], y[known]
    gap_x, gap_y = x[missing], y[missing]

    # Chunked so a large grid with a large gap does not allocate an
    # (ngap x nknown) distance matrix all at once.
    filled = np.empty(gap_x.size, dtype=np.float64)
    chunk = max(1, 4_000_000 // max(tree_x.size, 1))
    for start in range(0, gap_x.size, chunk):
        stop = min(start + chunk, gap_x.size)
        dx = gap_x[start:stop, None] - tree_x[None, :]
        dy = gap_y[start:stop, None] - tree_y[None, :]
        filled[start:stop] = values[known][np.argmin(dx * dx + dy * dy, axis=1)]
    return filled


def _from_points(
    surface: PointsSurface,
    grid: StructuredGrid,
    project: Path | None,
    sources: dict[str, GisSource],
    project_crs: str | None,
    *,
    name: str,
) -> np.ndarray:
    import pandas as pd

    from mupstudio.gisio.ingest import source_path

    source = sources.get(surface.source)
    if source is None:
        raise ElevationError(f"{name} reads {surface.source!r}, which this project does not have")
    if not isinstance(source, PointTableSource):
        raise ElevationError(f"{name} reads {source.name}, which is not a table of points")
    if project is None:
        raise ElevationError(f"{name} reads points, but no project directory was given")

    path = source_path(project, source)
    if not path.exists():
        raise ElevationError(f"{name} reads {source.path}, which is missing")

    table = pd.read_csv(path)
    for column in (source.x_column, source.y_column, surface.column):
        if column not in table.columns:
            have = ", ".join(map(str, table.columns))
            raise ElevationError(f"{name}: {source.name} has no column {column!r} (it has: {have})")

    points = table[[source.x_column, source.y_column, surface.column]].apply(
        pd.to_numeric, errors="coerce"
    )
    points = points.dropna()
    if points.empty:
        raise ElevationError(f"{name}: {source.name} has no usable points in it")

    px = points[source.x_column].to_numpy(dtype=np.float64)
    py = points[source.y_column].to_numpy(dtype=np.float64)
    pz = points[surface.column].to_numpy(dtype=np.float64)

    if source.crs and project_crs and source.crs != project_crs:
        from pyproj import Transformer

        transformer = Transformer.from_crs(source.crs, project_crs, always_xy=True)
        px, py = transformer.transform(px, py)

    return _inverse_distance(grid, px, py, pz, surface.power, surface.neighbours)


def _inverse_distance(
    grid: StructuredGrid,
    px: np.ndarray,
    py: np.ndarray,
    pz: np.ndarray,
    power: float,
    neighbours: int,
) -> np.ndarray:
    """Weight the nearest few points by inverse distance.

    Nearest few rather than all of them, so a dense survey on one side of the
    model does not drag values across the whole of it.
    """
    x, y = cell_centres(grid)
    flat_x, flat_y = x.ravel(), y.ravel()
    take = min(neighbours, px.size)

    out = np.empty(flat_x.size, dtype=np.float64)
    chunk = max(1, 4_000_000 // max(px.size, 1))

    for start in range(0, flat_x.size, chunk):
        stop = min(start + chunk, flat_x.size)
        dx = flat_x[start:stop, None] - px[None, :]
        dy = flat_y[start:stop, None] - py[None, :]
        squared = dx * dx + dy * dy

        # argpartition gives the nearest `take` in no particular order, which is
        # all inverse distance needs — but it means the closest is not
        # necessarily first, so an exact hit has to be searched for.
        near = np.argpartition(squared, take - 1, axis=1)[:, :take]
        rows = np.arange(stop - start)[:, None]
        distance = np.sqrt(squared[rows, near])

        weights = 1.0 / np.power(np.maximum(distance, 1e-12), power)
        block = (weights * pz[near]).sum(axis=1) / weights.sum(axis=1)

        # A cell sitting exactly on a measurement takes that measurement,
        # rather than dividing by nearly zero on the way to the same answer.
        closest = np.argmin(distance, axis=1)
        exact = distance[np.arange(distance.shape[0]), closest] == 0
        if exact.any():
            block[exact] = pz[near[exact, closest[exact]]]

        out[start:stop] = block

    return out.reshape(grid.nrow, grid.ncol)
