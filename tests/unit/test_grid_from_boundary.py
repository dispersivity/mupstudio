"""Covering an imported boundary with cells.

Two things come out of one polygon and they are easy to conflate: the grid,
which is a rectangle because a structured grid always is, and which of its cells
the boundary actually contains. Getting the second wrong gives a model that
solves flow across a bounding box and reports heads outside the catchment.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from mupstudio.gisio import ingest
from mupstudio.grids.fromboundary import (
    BoundaryGridError,
    grid_from_boundary,
    suggest_cell_size,
)
from mupstudio.schema.grid import LayerSpec

UTM19S = "EPSG:32719"
LAYERS = [LayerSpec(bottom=0.0)]

# A 20 km by 20 km square, which makes every count checkable by hand.
WEST, SOUTH = 340_000.0, 6_280_000.0
SIDE = 20_000.0


def boundary(tmp_path: Path, shape=None) -> tuple[Path, object]:  # type: ignore[no-untyped-def]
    """A project with one area imported into it."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    if shape is None:
        shape = Polygon(
            [
                (WEST, SOUTH),
                (WEST + SIDE, SOUTH),
                (WEST + SIDE, SOUTH + SIDE),
                (WEST, SOUTH + SIDE),
            ]
        )

    source_file = tmp_path / "source" / "area.shp"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"n": [1]}, geometry=[shape], crs=UTM19S).to_file(source_file)

    project = tmp_path / "model.mup"
    project.mkdir(exist_ok=True)
    return project, ingest.import_file(source_file, project, source_id="area").source


def build(tmp_path: Path, cell_size: float, **kwargs):  # type: ignore[no-untyped-def]
    project, source = boundary(tmp_path)
    return grid_from_boundary(
        project, source, cell_size=cell_size, top=100.0, layers=LAYERS, project_crs=UTM19S, **kwargs
    )


def test_a_square_divides_exactly(tmp_path: Path) -> None:
    """20 km at 1 km cells is 20 by 20, with nothing left over."""
    generated = build(tmp_path, 1000.0)

    assert (generated.grid.nrow, generated.grid.ncol) == (20, 20)
    assert generated.total_cells == 400


def test_the_grid_starts_at_the_boundary_corner(tmp_path: Path) -> None:
    """So a cell index means the same thing here as in the source data."""
    generated = build(tmp_path, 1000.0)

    assert generated.grid.origin_x == pytest.approx(WEST)
    assert generated.grid.origin_y == pytest.approx(SOUTH)


def test_the_grid_covers_the_boundary_rather_than_clipping_it(tmp_path: Path) -> None:
    """A size that does not divide evenly rounds up: the extra lands outside,
    where the cells are inactive anyway, and clipping would lose real area."""
    generated = build(tmp_path, 3000.0)

    assert generated.grid.ncol == math.ceil(SIDE / 3000.0) == 7
    assert generated.grid.columns.total_length >= SIDE


def test_a_square_boundary_fills_its_own_grid(tmp_path: Path) -> None:
    generated = build(tmp_path, 1000.0)

    assert generated.active_cells == generated.total_cells
    assert any("every cell is inside" in warning for warning in generated.warnings)


def test_a_circle_leaves_the_corners_out(tmp_path: Path) -> None:
    """The case the whole feature exists for: a rectangle of cells over a
    boundary that is not a rectangle."""
    from shapely.geometry import Point

    project, source = boundary(tmp_path, Point(WEST + SIDE / 2, SOUTH + SIDE / 2).buffer(SIDE / 2))
    generated = grid_from_boundary(
        project, source, cell_size=500.0, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    share = generated.active_cells / generated.total_cells
    # A circle fills pi/4 of its bounding square.
    assert share == pytest.approx(math.pi / 4, abs=0.02)
    assert generated.warnings == []


def test_the_corners_are_the_cells_left_out(tmp_path: Path) -> None:
    from shapely.geometry import Point

    project, source = boundary(tmp_path, Point(WEST + SIDE / 2, SOUTH + SIDE / 2).buffer(SIDE / 2))
    generated = grid_from_boundary(
        project, source, cell_size=1000.0, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    assert not generated.inside[0, 0]
    assert not generated.inside[-1, -1]
    middle = generated.inside.shape[0] // 2
    assert generated.inside[middle, middle]


def test_rows_run_north_to_south(tmp_path: Path) -> None:
    """As MODFLOW numbers them, so row 1 in the model is row 1 on the map.

    Checked with a triangle: wide along its northern edge, tapering to a point
    in the south. The grid is built from the polygon's own extent, so a shape
    that merely sat in one half would fill its grid completely and prove
    nothing; this one has to differ top from bottom within its own bounds.
    """
    from shapely.geometry import Polygon

    wedge = Polygon(
        [
            (WEST, SOUTH + SIDE),
            (WEST + SIDE, SOUTH + SIDE),
            (WEST + SIDE / 2, SOUTH),
        ]
    )
    project, source = boundary(tmp_path, wedge)
    generated = grid_from_boundary(
        project, source, cell_size=1000.0, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    # Row 0 is the wide northern edge; the last row is the southern point.
    assert generated.inside[0].sum() > generated.inside[-1].sum()
    assert generated.inside[0].sum() > generated.grid.ncol * 0.8


def test_a_margin_grows_the_grid_around_the_boundary(tmp_path: Path) -> None:
    plain = build(tmp_path, 1000.0)
    padded = build(tmp_path, 1000.0, margin=2000.0)

    assert padded.grid.ncol == plain.grid.ncol + 4
    assert padded.grid.origin_x == pytest.approx(WEST - 2000.0)


def test_layers_are_carried_through(tmp_path: Path) -> None:
    """Regenerating a grid should not throw away the layering someone set up."""
    project, source = boundary(tmp_path)
    layers = [LayerSpec(name="sand", bottom=50.0, sublayers=2), LayerSpec(name="rock", bottom=0.0)]

    generated = grid_from_boundary(
        project, source, cell_size=2000.0, top=100.0, layers=layers, project_crs=UTM19S
    )

    assert generated.grid.nlay == 3
    assert generated.grid.top.value == 100.0
    assert generated.grid.layers[0].name == "sand"


def test_a_cell_size_that_would_never_run_is_refused_with_one_that_would(
    tmp_path: Path,
) -> None:
    """The gap between slow and impossible is one keystroke wide, and the
    message has to be actionable rather than just a refusal."""
    with pytest.raises(BoundaryGridError, match="cell size of about") as caught:
        build(tmp_path, 0.5)

    assert "cells per layer" in str(caught.value)


def test_a_cell_size_of_zero_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BoundaryGridError, match="greater than zero"):
        build(tmp_path, 0.0)


def test_cells_larger_than_the_boundary_say_so(tmp_path: Path) -> None:
    """Rather than returning an empty model that looks like a bug elsewhere."""
    from shapely.geometry import Point

    project, source = boundary(tmp_path, Point(WEST, SOUTH).buffer(50.0))
    generated = grid_from_boundary(
        project, source, cell_size=1000.0, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    assert generated.active_cells == 0
    assert any("no cell centre" in warning for warning in generated.warnings)


def test_a_line_layer_cannot_be_filled_with_cells(tmp_path: Path) -> None:
    import geopandas as gpd
    from shapely.geometry import LineString

    project = tmp_path / "model.mup"
    project.mkdir()
    path = tmp_path / "river.shp"
    gpd.GeoDataFrame(
        {"n": [1]}, geometry=[LineString([(WEST, SOUTH), (WEST + SIDE, SOUTH)])], crs=UTM19S
    ).to_file(path)
    source = ingest.import_file(path, project, source_id="river").source

    with pytest.raises(BoundaryGridError, match="not an area"):
        grid_from_boundary(
            project, source, cell_size=1000.0, top=100.0, layers=LAYERS, project_crs=UTM19S
        )


def test_several_polygons_become_one_outline(tmp_path: Path) -> None:
    """A catchment split across features is still one catchment."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    project = tmp_path / "model.mup"
    project.mkdir()
    path = tmp_path / "halves.shp"
    left = Polygon(
        [
            (WEST, SOUTH),
            (WEST + SIDE / 2, SOUTH),
            (WEST + SIDE / 2, SOUTH + SIDE),
            (WEST, SOUTH + SIDE),
        ]
    )
    right = Polygon(
        [
            (WEST + SIDE / 2, SOUTH),
            (WEST + SIDE, SOUTH),
            (WEST + SIDE, SOUTH + SIDE),
            (WEST + SIDE / 2, SOUTH + SIDE),
        ]
    )
    gpd.GeoDataFrame({"n": [1, 2]}, geometry=[left, right], crs=UTM19S).to_file(path)
    source = ingest.import_file(path, project, source_id="halves").source

    generated = grid_from_boundary(
        project, source, cell_size=1000.0, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    assert generated.grid.ncol == 20
    assert generated.active_cells == generated.total_cells


def test_a_suggested_size_lands_near_the_target(tmp_path: Path) -> None:
    """Offered as a starting point, not a recommendation — but it should be the
    right order of magnitude rather than a number out of the air."""
    project, source = boundary(tmp_path)

    size = suggest_cell_size(project, source, target_cells=10_000, project_crs=UTM19S)
    generated = grid_from_boundary(
        project, source, cell_size=size, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    assert 2_000 < generated.total_cells < 50_000


def test_the_summary_says_what_was_made(tmp_path: Path) -> None:
    from shapely.geometry import Point

    project, source = boundary(tmp_path, Point(WEST + SIDE / 2, SOUTH + SIDE / 2).buffer(SIDE / 2))
    generated = grid_from_boundary(
        project, source, cell_size=1000.0, top=100.0, layers=LAYERS, project_crs=UTM19S
    )

    summary = generated.describe()
    assert "20 by 20 cells" in summary
    assert "inside the boundary" in summary
    assert "%" in summary


def test_the_inside_map_matches_the_grid(tmp_path: Path) -> None:
    """It is indexed by row and column, so it has to be that shape."""
    generated = build(tmp_path, 1500.0)

    assert generated.inside.shape == (generated.grid.nrow, generated.grid.ncol)
    assert generated.inside.dtype == np.bool_
