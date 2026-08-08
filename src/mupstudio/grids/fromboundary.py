"""Building a grid from an imported boundary.

The first real thing anyone does with a catchment outline is cover it in cells.
Doing that by hand means reading the shapefile's extent out of a GIS, dividing
by the cell size you want, typing four numbers into a form and hoping you got
the origin right. This does it from the polygon.

Two separate results come out of one polygon, and it is worth keeping them
apart:

* the **grid**, which is a rectangle — a structured grid always is, and it has
  to cover the boundary rather than follow it;
* which of those cells are **inside** the boundary, which is what makes the
  corner cells of that rectangle inactive rather than part of the model.

MODFLOW calls the second one IDOMAIN. Without it a catchment model solves flow
across the whole bounding box and reports heads in cells that are not in the
catchment at all.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mupstudio.gisio.ingest import source_path
from mupstudio.schema.gis import GisSource, VectorSource
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid
from mupstudio.schema.selection import ShapeSelection
from mupstudio.schema.surfaces import SurfaceSource

log = logging.getLogger(__name__)

# Refuse to build something nobody can run. A structured grid over a large
# catchment at a small cell size grows as the square of the refinement, and the
# gap between "slow" and "impossible" is one keystroke wide.
MAX_CELLS_PER_LAYER = 4_000_000


class BoundaryGridError(Exception):
    """A grid cannot be built from this boundary."""


@dataclass
class GeneratedGrid:
    """A grid, and which of its cells the boundary covers."""

    grid: StructuredGrid
    #: (nrow, ncol) boolean: True where the cell centre falls inside.
    inside: np.ndarray
    warnings: list[str]

    @property
    def active_cells(self) -> int:
        return int(np.count_nonzero(self.inside))

    @property
    def total_cells(self) -> int:
        return int(self.inside.size)

    def describe(self) -> str:
        """One line saying what was made, for the screen that asked for it."""
        rows, columns = self.inside.shape
        share = self.active_cells / self.total_cells if self.total_cells else 0
        return f"{rows} by {columns} cells, {self.active_cells:,} inside the boundary ({share:.0%})"


def grid_from_boundary(
    project: Path,
    source: GisSource,
    *,
    cell_size: float,
    top: SurfaceSource | float,
    layers: list[LayerSpec],
    margin: float = 0.0,
    project_crs: str | None = None,
) -> GeneratedGrid:
    """Cover a boundary polygon with square cells.

    ``cell_size`` is in the boundary's own units, which for a projected CRS
    means metres. ``margin`` extends the rectangle beyond the polygon, which is
    worth having when a boundary is a catchment divide rather than a no-flow
    edge.
    """
    polygon = _read_polygon(project, source, project_crs)

    if cell_size <= 0:
        raise BoundaryGridError("the cell size has to be greater than zero")

    west, south, east, north = polygon.bounds
    west, south = west - margin, south - margin
    east, north = east + margin, north + margin

    # Rounded up so the grid covers the boundary rather than clipping it, and
    # the extra lands outside where those cells will be inactive anyway.
    ncol = max(1, math.ceil((east - west) / cell_size))
    nrow = max(1, math.ceil((north - south) / cell_size))

    if nrow * ncol > MAX_CELLS_PER_LAYER:
        suggested = math.sqrt((east - west) * (north - south) / MAX_CELLS_PER_LAYER)
        raise BoundaryGridError(
            f"{nrow:,} by {ncol:,} is {nrow * ncol:,} cells per layer, which is more than "
            f"this will build. A cell size of about {suggested:,.0f} would fit."
        )

    grid = StructuredGrid(
        origin_x=west,
        origin_y=south,
        rotation=0.0,
        columns=AxisSpacing(ncells=ncol, total_length=ncol * cell_size),
        rows=AxisSpacing(ncells=nrow, total_length=nrow * cell_size),
        top=top,  # type: ignore[arg-type]
        layers=layers,
        # The cells the boundary covers are the model; the rest of the
        # rectangle is not. Stored as the boundary itself rather than as the
        # list of cells it currently covers, so refining the grid re-derives
        # them instead of leaving a stale list behind.
        active=ShapeSelection(
            source=source.id,
            layers=list(range(1, sum(layer.sublayers for layer in layers) + 1)),
            rule="centroid",
        ),
    )

    inside = _cells_inside(polygon, grid, cell_size, west, north)

    warnings: list[str] = []
    if not inside.any():
        warnings.append(
            "no cell centre falls inside the boundary; the cells are larger than the "
            "area they are covering"
        )
    elif inside.all():
        warnings.append(
            "every cell is inside the boundary, so the grid adds nothing the extent "
            "would not have given"
        )

    return GeneratedGrid(grid=grid, inside=inside, warnings=warnings)


def _read_polygon(project: Path, source: GisSource, project_crs: str | None) -> Any:
    """The boundary as one shape, in its own coordinates.

    Several polygons are merged rather than refused: a catchment split across
    features is still one catchment, and a model of it wants one outline.
    """
    if not isinstance(source, VectorSource) or source.geometry != "polygon":
        raise BoundaryGridError(
            f"{source.name} is not an area, so there is nothing to fill with cells"
        )

    import geopandas as gpd
    from shapely.ops import unary_union

    path = source_path(project, source)
    if not path.exists():
        raise BoundaryGridError(f"{source.name} points at {source.path}, which is missing")

    frame = gpd.read_file(path)
    if frame.crs is None:
        frame = frame.set_crs(source.crs or project_crs, allow_override=True)
    if frame.empty:
        raise BoundaryGridError(f"{source.name} has no features in it")

    merged = unary_union(frame.geometry.tolist())
    if merged.is_empty:
        raise BoundaryGridError(f"{source.name} encloses no area")
    return merged


def _cells_inside(
    polygon: Any,
    grid: StructuredGrid,
    cell_size: float,
    west: float,
    north: float,
) -> np.ndarray:
    """Which cell centres the boundary contains.

    By centre rather than by overlap: a cell whose centre is outside is mostly
    outside, and a rule that kept every cell the boundary merely touches would
    grow the model by a ring of cells that are almost entirely not in it.
    """
    import shapely

    ncol, nrow = grid.ncol, grid.nrow

    # Columns run west to east; rows run north to south, as MODFLOW numbers them.
    xs = west + (np.arange(ncol) + 0.5) * cell_size
    ys = north - (np.arange(nrow) + 0.5) * cell_size

    grid_x, grid_y = np.meshgrid(xs, ys)

    # Vectorised: a hundred thousand point-in-polygon tests done one at a time
    # is seconds of waiting, and this is milliseconds.
    covered = shapely.contains_xy(polygon, grid_x.ravel(), grid_y.ravel())

    return np.asarray(covered, dtype=bool).reshape(nrow, ncol)


def suggest_cell_size(
    project: Path, source: GisSource, *, target_cells: int = 20_000, project_crs: str | None = None
) -> float:
    """A cell size that lands near a given number of cells.

    Offered as a starting point rather than a recommendation: how fine a grid
    needs to be is a modelling judgement about gradients and features, not
    something a bounding box can answer. But a number in the box beats an empty
    one, and it is the right order of magnitude.
    """
    polygon = _read_polygon(project, source, project_crs)
    west, south, east, north = polygon.bounds
    area = (east - west) * (north - south)
    if area <= 0:
        raise BoundaryGridError(f"{source.name} has no extent")

    raw = math.sqrt(area / max(target_cells, 1))
    # Rounded to something a person would have typed.
    magnitude = 10 ** math.floor(math.log10(raw))
    return float(round(raw / magnitude) * magnitude)
