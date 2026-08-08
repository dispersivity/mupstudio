"""Pointing at cells.

The three ways of naming cells are the vocabulary the whole builder is written
in, so they are checked on their own before anything that uses them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from mupstudio.grids.select import SelectionError, cells_under_shape
from mupstudio.schema.gis import VectorSource
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid
from mupstudio.schema.selection import (
    CellList,
    CellRange,
    ShapeSelection,
    describe,
    out_of_range,
)


def square_grid(**overrides: object) -> StructuredGrid:
    """A 10x10 grid of unit cells with its corner at the origin."""
    defaults: dict[str, object] = {
        "columns": AxisSpacing(ncells=10, total_length=10.0),
        "rows": AxisSpacing(ncells=10, total_length=10.0),
        "top": 0.0,
        "layers": [LayerSpec(bottom=-1.0)],
    }
    return StructuredGrid(**{**defaults, **overrides})  # type: ignore[arg-type]


def write_shapefile(project: Path, name: str, geometry: object, crs: str = "EPSG:32719"):
    """A source file where an imported one would be: inside the project's gis/."""
    import geopandas as gpd

    folder = project / "gis"
    folder.mkdir(exist_ok=True)
    frame = gpd.GeoDataFrame({"name": ["thing"]}, geometry=[geometry], crs=crs)
    frame.to_file(folder / name)
    kind = geometry.geom_type.lower().replace("multi", "")  # type: ignore[attr-defined]
    return VectorSource(
        id="feature",
        name="Feature",
        path=name,
        geometry="line" if kind == "linestring" else kind,  # type: ignore[arg-type]
        crs=crs,
    )


class TestOneBasedIndices:
    def test_zero_is_not_a_cell(self) -> None:
        """Indices match MODFLOW input, where counting starts at one."""
        with pytest.raises(ValidationError, match="indices start at 1"):
            CellRange(layers=[0], rows=[1], columns=[1])

    def test_a_list_is_checked_too(self) -> None:
        with pytest.raises(ValidationError, match="indices start at 1"):
            CellList(indices=[(1, 1, 0)])

    def test_clicking_the_same_cell_twice_is_not_an_error(self) -> None:
        """It writes one MODFLOW record, so it should hold one entry."""
        assert CellList(indices=[(1, 2, 3), (1, 2, 3)]).indices == [(1, 2, 3)]


class TestOutOfRange:
    def test_accepts_what_fits(self) -> None:
        selection = CellRange(layers=[1], rows=[1], columns=[10])

        assert out_of_range(selection, nlay=1, nrow=1, ncol=10) is None

    def test_names_the_axis_and_the_limit(self) -> None:
        selection = CellRange(layers=[1], rows=[1], columns=[99])

        assert out_of_range(selection, nlay=1, nrow=1, ncol=10) == (
            "column 99, but the grid has 10 (indices start at 1)"
        )

    def test_a_shape_is_only_checked_for_its_layers(self) -> None:
        """Which rows and columns it covers is the grid's answer, not the user's."""
        selection = ShapeSelection(source="river", layers=[5])

        assert out_of_range(selection, nlay=2, nrow=99, ncol=99) == (
            "layer 5, but the grid has 2 (indices start at 1)"
        )


class TestDescribe:
    def test_counts_a_block(self) -> None:
        assert describe(CellRange(layers=[1, 2], rows=[1], columns=[1, 2, 3])) == "6 cells by index"

    def test_counts_a_picked_list(self) -> None:
        assert describe(CellList(indices=[(1, 1, 1)])) == "1 cell picked"

    def test_names_the_source_of_a_shape(self) -> None:
        assert describe(ShapeSelection(source="river")) == "from river in layer 1"


class TestShapeSelection:
    def test_a_polygon_takes_the_cells_it_covers(self, tmp_path: Path) -> None:
        from shapely.geometry import box

        # Covers columns 3-4 and rows 7-8 counting from the north.
        source = write_shapefile(tmp_path, "zone.shp", box(2.0, 2.0, 4.0, 4.0))

        mask = cells_under_shape(
            tmp_path,
            ShapeSelection(source="feature", rule="centroid"),
            source,
            square_grid(),
            project_crs="EPSG:32719",
        )

        assert mask.sum() == 4
        assert np.array_equal(np.nonzero(mask)[0], [6, 6, 7, 7])
        assert np.array_equal(np.nonzero(mask)[1], [2, 3, 2, 3])

    def test_rows_run_north_to_south(self, tmp_path: Path) -> None:
        """MODFLOW numbers rows from the top, so a shape at high y is row 1."""
        from shapely.geometry import box

        source = write_shapefile(tmp_path, "north.shp", box(0.0, 9.0, 10.0, 10.0))

        mask = cells_under_shape(
            tmp_path,
            ShapeSelection(source="feature", rule="centroid"),
            source,
            square_grid(),
        )

        assert mask[0].all()
        assert not mask[1:].any()

    def test_a_line_takes_every_cell_it_crosses(self, tmp_path: Path) -> None:
        """Centre-testing a line finds nothing: a line has no area to contain one."""
        from shapely.geometry import LineString

        source = write_shapefile(tmp_path, "river.shp", LineString([(0.5, 5.5), (9.5, 5.5)]))
        selection = ShapeSelection(source="feature", rule="intersects")

        mask = cells_under_shape(tmp_path, selection, source, square_grid())

        assert mask.sum() == 10
        assert mask[4].all()

    def test_a_buffer_widens_the_catch(self, tmp_path: Path) -> None:
        from shapely.geometry import LineString

        source = write_shapefile(tmp_path, "river.shp", LineString([(0.5, 5.5), (9.5, 5.5)]))

        narrow = cells_under_shape(
            tmp_path, ShapeSelection(source="feature"), source, square_grid()
        )
        wide = cells_under_shape(
            tmp_path, ShapeSelection(source="feature", buffer=1.5), source, square_grid()
        )

        assert wide.sum() > narrow.sum()

    def test_the_origin_is_where_the_grid_starts(self, tmp_path: Path) -> None:
        """A grid placed in the world selects by world coordinates, not by index."""
        from shapely.geometry import box

        source = write_shapefile(tmp_path, "zone.shp", box(1002.0, 5002.0, 1004.0, 5004.0))
        placed = square_grid(origin_x=1000.0, origin_y=5000.0)

        mask = cells_under_shape(
            tmp_path, ShapeSelection(source="feature", rule="centroid"), source, placed
        )

        assert mask.sum() == 4
        assert np.array_equal(np.nonzero(mask)[1], [2, 3, 2, 3])

    def test_a_rotated_grid_is_selected_in_its_own_frame(self, tmp_path: Path) -> None:
        """Rotation is counterclockwise, so the grid lies west of the origin at 90.

        A cell at model (0.5, 1.5) — first column, ninth row down — is then at
        world (-1.5, 0.5). Testing the exact cell rather than "some cell" is
        what catches a rotation applied the wrong way round, which otherwise
        selects plausible-looking cells on the wrong side of the model.
        """
        from shapely.geometry import box

        source = write_shapefile(tmp_path, "zone.shp", box(-1.9, 0.1, -1.1, 0.9))

        mask = cells_under_shape(
            tmp_path,
            ShapeSelection(source="feature", rule="centroid"),
            source,
            square_grid(rotation=90.0),
        )

        assert [tuple(axis) for axis in np.nonzero(mask)] == [(8,), (0,)]

    def test_a_shape_off_the_grid_selects_nothing(self, tmp_path: Path) -> None:
        from shapely.geometry import box

        source = write_shapefile(tmp_path, "far.shp", box(500.0, 500.0, 510.0, 510.0))

        mask = cells_under_shape(tmp_path, ShapeSelection(source="feature"), source, square_grid())

        assert not mask.any()

    def test_a_missing_file_is_said_in_the_user_s_terms(self, tmp_path: Path) -> None:
        source = VectorSource(id="gone", name="Gone", path="nowhere.shp", geometry="polygon")

        with pytest.raises(SelectionError, match="which is missing"):
            cells_under_shape(tmp_path, ShapeSelection(source="gone"), source, square_grid())

    def test_a_source_in_another_crs_is_brought_across(self, tmp_path: Path) -> None:
        """Skipping this puts the shape somewhere else and selects nothing."""
        import geopandas as gpd
        from shapely.geometry import box

        # The same square, expressed in latitude and longitude.
        utm = gpd.GeoDataFrame(geometry=[box(1002.0, 5002.0, 1004.0, 5004.0)], crs="EPSG:32719")
        (tmp_path / "gis").mkdir()
        utm.to_crs("EPSG:4326").to_file(tmp_path / "gis" / "zone.shp")
        source = VectorSource(
            id="feature", name="Feature", path="zone.shp", geometry="polygon", crs="EPSG:4326"
        )

        mask = cells_under_shape(
            tmp_path,
            ShapeSelection(source="feature", rule="centroid"),
            source,
            square_grid(origin_x=1000.0, origin_y=5000.0),
            project_crs="EPSG:32719",
        )

        assert mask.sum() == 4
