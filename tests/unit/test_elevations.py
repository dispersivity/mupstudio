"""Layer surfaces, and which cells are in the model.

Until this existed, a grid built to fit a catchment was still a flat slab over
the catchment's bounding rectangle: every layer one number thick, every cell
active. These are the two things that make it a model of a place.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import CompileError, compile_project
from mupstudio.grids.elevations import ElevationError, cell_centres, resolve_elevations
from mupstudio.schema.common import StressPeriod, TimeDiscretisation
from mupstudio.schema.gis import DataModel, PointTableSource, RasterSource
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.selection import CellRange, ShapeSelection
from mupstudio.schema.surfaces import (
    OffsetSurface,
    PointsSurface,
    RasterSurface,
)


def grid(**overrides: object) -> StructuredGrid:
    """A 4x4 grid of 10 m cells with its corner at the origin."""
    defaults: dict[str, object] = {
        "columns": AxisSpacing(ncells=4, total_length=40.0),
        "rows": AxisSpacing(ncells=4, total_length=40.0),
        "top": 100.0,
        "layers": [LayerSpec(bottom=90.0)],
    }
    return StructuredGrid(**{**defaults, **overrides})  # type: ignore[arg-type]


def write_dem(
    project: Path, name: str, values: np.ndarray, *, crs: str = "EPSG:32719"
) -> RasterSource:
    """A raster covering the 40x40 m grid, one pixel per cell."""
    import rasterio
    from rasterio.transform import from_origin

    folder = project / "gis"
    folder.mkdir(exist_ok=True)
    rows, cols = values.shape
    with rasterio.open(
        folder / name,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(0.0, 40.0, 40.0 / cols, 40.0 / rows),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)

    return RasterSource(id="dem", name="DEM", path=name, crs=crs, width=cols, height=rows)


class TestCellCentres:
    def test_columns_run_east_and_rows_run_south(self) -> None:
        """MODFLOW numbers rows from the north, which is why y descends."""
        x, y = cell_centres(grid())

        assert x[0].tolist() == [5.0, 15.0, 25.0, 35.0]
        assert y[:, 0].tolist() == [35.0, 25.0, 15.0, 5.0]

    def test_the_origin_moves_the_whole_grid(self) -> None:
        x, y = cell_centres(grid(origin_x=1000.0, origin_y=5000.0))

        assert x[0, 0] == 1005.0
        assert y[0, 0] == 5035.0

    def test_rotation_turns_counterclockwise_about_the_origin(self) -> None:
        x, y = cell_centres(grid(rotation=90.0))

        # The first cell sits at (5, 35) unrotated, so at 90 degrees it is at
        # (-35, 5). Getting the sign wrong samples the wrong side of a DEM.
        assert x[0, 0] == pytest.approx(-35.0)
        assert y[0, 0] == pytest.approx(5.0)


class TestConstantAndOffset:
    def test_a_number_fills_the_layer(self) -> None:
        found = resolve_elevations(grid())

        assert found.top.shape == (4, 4)
        assert np.all(found.top == 100.0)
        assert np.all(found.botm[0] == 90.0)

    def test_an_offset_follows_the_surface_above(self) -> None:
        """What keeps a layer parallel to the topography instead of flat."""
        found = resolve_elevations(grid(layers=[LayerSpec(bottom=OffsetSurface(thickness=25.0))]))

        assert np.all(found.botm[0] == 75.0)

    def test_offsets_stack(self) -> None:
        found = resolve_elevations(
            grid(
                layers=[
                    LayerSpec(bottom=OffsetSurface(thickness=10.0)),
                    LayerSpec(bottom=OffsetSurface(thickness=5.0)),
                ]
            )
        )

        assert np.all(found.botm[0] == 90.0)
        assert np.all(found.botm[1] == 85.0)

    def test_the_model_top_cannot_be_an_offset(self) -> None:
        with pytest.raises(ElevationError, match="nothing above it"):
            resolve_elevations(grid(top=OffsetSurface(thickness=1.0)))

    def test_sublayers_divide_the_interval_rather_than_sitting_flat(self) -> None:
        found = resolve_elevations(grid(top=100.0, layers=[LayerSpec(bottom=70.0, sublayers=3)]))

        assert found.nlay == 3
        assert [float(found.botm[index][0, 0]) for index in range(3)] == [90.0, 80.0, 70.0]


class TestRaster:
    def test_each_cell_takes_the_value_under_its_centre(self, tmp_path: Path) -> None:
        values = np.arange(16, dtype=float).reshape(4, 4)
        source = write_dem(tmp_path, "dem.tif", values)

        found = resolve_elevations(
            grid(top=RasterSurface(source="dem")),
            project=tmp_path,
            sources={"dem": source},
        )

        # Raster row 0 is the north edge, and so is grid row 0.
        np.testing.assert_array_equal(found.top, values)

    def test_an_offset_shifts_a_sampled_surface(self, tmp_path: Path) -> None:
        source = write_dem(tmp_path, "dem.tif", np.full((4, 4), 50.0))

        found = resolve_elevations(
            grid(top=RasterSurface(source="dem", offset=5.0), layers=[LayerSpec(bottom=0.0)]),
            project=tmp_path,
            sources={"dem": source},
        )

        assert np.all(found.top == 55.0)

    def test_nodata_is_filled_from_the_nearest_covered_cell(self, tmp_path: Path) -> None:
        """A DEM that stops short of the grid should not punch holes in it."""
        values = np.full((4, 4), 60.0)
        values[0, 0] = -9999.0
        source = write_dem(tmp_path, "dem.tif", values)

        found = resolve_elevations(
            grid(top=RasterSurface(source="dem")), project=tmp_path, sources={"dem": source}
        )

        assert found.top[0, 0] == 60.0

    def test_an_explicit_fill_wins_over_the_nearest_value(self, tmp_path: Path) -> None:
        values = np.full((4, 4), 60.0)
        values[0, 0] = -9999.0
        source = write_dem(tmp_path, "dem.tif", values)

        found = resolve_elevations(
            grid(top=RasterSurface(source="dem", fill=12.0)),
            project=tmp_path,
            sources={"dem": source},
        )

        assert found.top[0, 0] == 12.0

    def test_a_raster_that_misses_the_grid_is_refused_by_name(self, tmp_path: Path) -> None:
        source = write_dem(tmp_path, "dem.tif", np.full((4, 4), 60.0))

        with pytest.raises(ElevationError, match="coordinate system"):
            resolve_elevations(
                grid(origin_x=500_000.0, origin_y=500_000.0, top=RasterSurface(source="dem")),
                project=tmp_path,
                sources={"dem": source},
            )

    def test_an_unknown_source_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(ElevationError, match="does not have"):
            resolve_elevations(
                grid(top=RasterSurface(source="ghost")), project=tmp_path, sources={}
            )


class TestPoints:
    def points(self, tmp_path: Path, rows: str) -> PointTableSource:
        folder = tmp_path / "gis"
        folder.mkdir(exist_ok=True)
        (folder / "picks.csv").write_text("x,y,elev\n" + rows)
        return PointTableSource(
            id="picks", name="Picks", path="picks.csv", x_column="x", y_column="y"
        )

    def test_a_cell_on_a_measurement_takes_it_exactly(self, tmp_path: Path) -> None:
        source = self.points(tmp_path, "5,35,42\n35,5,10\n")

        found = resolve_elevations(
            grid(top=PointsSurface(source="picks", column="elev")),
            project=tmp_path,
            sources={"picks": source},
        )

        assert found.top[0, 0] == pytest.approx(42.0)
        assert found.top[3, 3] == pytest.approx(10.0)

    def test_values_stay_between_the_measurements(self, tmp_path: Path) -> None:
        """Inverse distance never overshoots, which is why it is the default."""
        source = self.points(tmp_path, "5,35,0\n35,5,100\n")

        found = resolve_elevations(
            grid(top=PointsSurface(source="picks", column="elev")),
            project=tmp_path,
            sources={"picks": source},
        )

        assert found.top.min() >= 0.0
        assert found.top.max() <= 100.0

    def test_a_missing_column_lists_the_ones_there_are(self, tmp_path: Path) -> None:
        source = self.points(tmp_path, "5,35,42\n")

        with pytest.raises(ElevationError, match="it has: x, y, elev"):
            resolve_elevations(
                grid(top=PointsSurface(source="picks", column="depth")),
                project=tmp_path,
                sources={"picks": source},
            )


class TestCrossingSurfaces:
    def test_a_layer_that_crosses_the_one_above_is_clamped_and_counted(
        self, tmp_path: Path
    ) -> None:
        """Units pinch out in real models; stopping the build helps nobody."""
        source = write_dem(tmp_path, "base.tif", np.full((4, 4), 200.0))

        found = resolve_elevations(
            grid(top=100.0, layers=[LayerSpec(name="rock", bottom=RasterSurface(source="base"))]),
            project=tmp_path,
            sources={"base": source},
        )

        assert np.all(found.botm[0] < found.top)
        assert any("16 cells" in warning and "rock" in warning for warning in found.warnings)

    def test_a_minimum_thickness_is_honoured(self, tmp_path: Path) -> None:
        source = write_dem(tmp_path, "base.tif", np.full((4, 4), 99.9))

        found = resolve_elevations(
            grid(
                top=100.0,
                layers=[LayerSpec(bottom=RasterSurface(source="base"), minimum_thickness=2.0)],
            ),
            project=tmp_path,
            sources={"base": source},
        )

        assert np.all(found.top - found.botm[0] >= 2.0)

    def test_surfaces_that_are_plain_numbers_are_still_checked_up_front(self) -> None:
        """A typed-in inversion is a mistake, not a pinch-out."""
        with pytest.raises(ValueError, match="must descend"):
            grid(top=0.0, layers=[LayerSpec(bottom=10.0)])


def project_with(**overrides: object) -> Project:
    defaults: dict[str, object] = {
        "meta": ProjectMeta(name="test", engine="mf6rtm"),
        "grid": grid(),
        "time": TimeDiscretisation(periods=[StressPeriod(perlen=1.0)]),
    }
    return Project(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestIdomain:
    def test_every_cell_is_active_when_nothing_says_otherwise(self) -> None:
        model = compile_project(project_with())

        assert model.grid.idomain is None
        assert model.grid.active_cells == model.grid.ncells

    def test_a_selection_marks_the_rest_inactive(self) -> None:
        model = compile_project(
            project_with(grid=grid(active=CellRange(layers=[1], rows=[1, 2], columns=[1, 2])))
        )

        assert model.grid.idomain is not None
        assert model.grid.active_cells == 4
        assert model.grid.idomain[0, 0, 0] == 1
        assert model.grid.idomain[0, 3, 3] == 0

    def test_how_much_was_switched_off_is_reported(self) -> None:
        """A model that quietly lost 87% of its cells should say so."""
        model = compile_project(
            project_with(grid=grid(active=CellRange(layers=[1], rows=[1], columns=[1])))
        )

        assert any("outside the model" in warning for warning in model.warnings)

    def test_a_selection_that_cannot_resolve_is_refused(self) -> None:
        # Naming a shape the project does not have would otherwise leave every
        # cell inactive, which is a model with nothing in it.
        with pytest.raises(CompileError, match="outline"):
            compile_project(
                project_with(
                    grid=grid(active=ShapeSelection(source="outline")),
                    data=DataModel(sources=[]),
                )
            )
