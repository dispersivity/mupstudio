"""Turning an imported shape into the cells it covers.

The counterpart to `fromboundary`: that one builds a grid to fit a polygon,
this one asks which cells of an existing grid a shape falls on. It is what
makes "the river runs through these cells" a fact derived from the river rather
than a list somebody typed and has to retype after every regrid.

Everything happens in model coordinates. A rotated grid is a rotated rectangle
in the world, and testing against a rotated rectangle is fiddly; unrotating the
shape instead makes every test axis-aligned, which is both simpler and faster.
Rotation is rigid, so distances — and therefore buffers — are unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from mupstudio.schema.gis import GisSource, VectorSource
from mupstudio.schema.grid import StructuredGrid
from mupstudio.schema.selection import ShapeSelection


class SelectionError(Exception):
    """A shape that cannot be turned into cells, said in the user's terms."""


def cells_under_shape(
    project: Path,
    selection: ShapeSelection,
    source: GisSource,
    grid: StructuredGrid,
    *,
    project_crs: str | None = None,
) -> np.ndarray:
    """A (nrow, ncol) boolean mask of the cells the shape falls on."""
    shape = _read_shape(project, source, project_crs)
    shape = _into_model_space(shape, grid)

    if selection.buffer > 0:
        shape = shape.buffer(selection.buffer)

    edges_x, edges_y = _cell_edges(grid)

    if selection.rule == "centroid":
        return _by_centroid(shape, edges_x, edges_y)
    return _by_overlap(shape, edges_x, edges_y)


def _cell_edges(grid: StructuredGrid) -> tuple[np.ndarray, np.ndarray]:
    """Column and row boundaries in model coordinates, from the origin.

    Columns run west to east from the origin. Rows run north to south, as
    MODFLOW numbers them, so the first row edge is at the top of the grid and
    the array descends.
    """
    widths = np.asarray(grid.columns.resolve(), dtype=float)
    heights = np.asarray(grid.rows.resolve(), dtype=float)

    edges_x = np.concatenate([[0.0], np.cumsum(widths)])
    edges_y = float(heights.sum()) - np.concatenate([[0.0], np.cumsum(heights)])
    return edges_x, edges_y


def _by_centroid(shape: Any, edges_x: np.ndarray, edges_y: np.ndarray) -> np.ndarray:
    """Cells whose centre the shape covers.

    The right rule for an area: a cell mostly outside a zone should not take
    the zone's properties, and a cell mostly inside should.
    """
    import shapely

    centres_x = (edges_x[:-1] + edges_x[1:]) / 2
    centres_y = (edges_y[:-1] + edges_y[1:]) / 2
    grid_x, grid_y = np.meshgrid(centres_x, centres_y)

    covered = shapely.contains_xy(shape, grid_x.ravel(), grid_y.ravel())
    return np.asarray(covered, dtype=bool).reshape(len(centres_y), len(centres_x))


def _by_overlap(shape: Any, edges_x: np.ndarray, edges_y: np.ndarray) -> np.ndarray:
    """Every cell the shape touches.

    The right rule for a line or a point: a river that crosses the corner of a
    cell is still in that cell, and centre-testing a line finds almost nothing
    because a line has no area to contain a centre with.
    """
    import shapely

    nrow, ncol = len(edges_y) - 1, len(edges_x) - 1
    mask = np.zeros((nrow, ncol), dtype=bool)

    # Only cells inside the shape's bounding box can touch it. On a large grid
    # with a small feature this is the difference between testing a handful of
    # cells and testing all of them.
    minx, miny, maxx, maxy = shape.bounds
    first_col, last_col = _span(edges_x, minx, maxx, ascending=True)
    first_row, last_row = _span(edges_y, miny, maxy, ascending=False)
    if first_col > last_col or first_row > last_row:
        return mask

    rows = np.arange(first_row, last_row + 1)
    cols = np.arange(first_col, last_col + 1)
    row_grid, col_grid = np.meshgrid(rows, cols, indexing="ij")

    boxes = shapely.box(
        edges_x[col_grid],
        edges_y[row_grid + 1],
        edges_x[col_grid + 1],
        edges_y[row_grid],
    )

    hits = shapely.intersects(boxes.ravel(), shape)
    mask[first_row : last_row + 1, first_col : last_col + 1] = np.asarray(hits, dtype=bool).reshape(
        row_grid.shape
    )
    return mask


def _span(edges: np.ndarray, low: float, high: float, *, ascending: bool) -> tuple[int, int]:
    """The index range of cells overlapping [low, high] along one axis."""
    ncell = len(edges) - 1
    if ascending:
        first = int(np.searchsorted(edges, low, side="right")) - 1
        last = int(np.searchsorted(edges, high, side="left")) - 1
    else:
        # Row edges descend, so the comparison flips and so does which end of
        # the interval gives the first index.
        first = int(np.searchsorted(-edges, -high, side="right")) - 1
        last = int(np.searchsorted(-edges, -low, side="left")) - 1

    return max(first, 0), min(last, ncell - 1)


def _into_model_space(shape: Any, grid: StructuredGrid) -> Any:
    """Move a world shape into coordinates the grid is axis-aligned in."""
    from shapely.affinity import rotate, translate

    if grid.rotation:
        shape = rotate(shape, -grid.rotation, origin=(grid.origin_x, grid.origin_y))
    return translate(shape, xoff=-grid.origin_x, yoff=-grid.origin_y)


def _read_shape(project: Path, source: GisSource, project_crs: str | None) -> Any:
    """Every feature of a source as one shape, in its own coordinates."""
    if not isinstance(source, VectorSource):
        raise SelectionError(f"{source.name} is not a set of shapes, so it cannot pick out cells")

    import geopandas as gpd
    from shapely.ops import unary_union

    from mupstudio.gisio.ingest import source_path

    path = source_path(project, source)
    if not path.exists():
        raise SelectionError(f"{source.name} points at {source.path}, which is missing")

    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs(source.crs or project_crs, allow_override=True)
    if frame.empty:
        raise SelectionError(f"{source.name} has no features in it")

    # The grid is laid out in the project's coordinate system, so a source in
    # another one has to be brought across first. Skipping this would put the
    # shape somewhere else entirely, and it would select nothing rather than
    # visibly failing.
    if project_crs and frame.crs is not None:
        try:
            frame = frame.to_crs(project_crs)
        except Exception as error:  # pragma: no cover - depends on the CRS pair
            raise SelectionError(
                f"{source.name} is in {frame.crs}, which will not convert to the "
                f"model's {project_crs}: {error}"
            ) from error

    merged = unary_union(frame.geometry.tolist())
    if merged.is_empty:
        raise SelectionError(f"{source.name} encloses nothing to select with")
    return merged
