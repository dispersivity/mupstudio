"""Resolving a project into arrays.

No MODFLOW here: this is the conversion from how a person describes a model to
what an engine writer consumes, and it should be checkable without running one.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import CompileError, compile_project
from mupstudio.schema.common import (
    ArrayField,
    ConstantSeries,
    PerPeriodSeries,
    StressPeriod,
    TimeDiscretisation,
    ZoneField,
    constant,
)
from mupstudio.schema.flow import (
    CellRange,
    ConstantHeadPackage,
    FlowModel,
    FlowProperties,
    RechargePackage,
    WellPackage,
)
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid, column_grid
from mupstudio.schema.project import Project, ProjectMeta


def project(**overrides) -> Project:
    defaults = {
        "meta": ProjectMeta(name="test", engine="mf6rtm"),
        "grid": column_grid(ncells=10, length=1.0),
        "time": TimeDiscretisation(periods=[StressPeriod(perlen=1.0)]),
    }
    return Project(**{**defaults, **overrides})


class TestGrid:
    def test_a_column_compiles_to_one_row_and_one_layer(self) -> None:
        grid = compile_project(project()).grid

        assert grid.shape == (1, 1, 10)
        assert grid.delr.tolist() == [0.1] * 10
        assert grid.delc.tolist() == [1.0]

    def test_graded_spacing_is_carried_through(self) -> None:
        graded = StructuredGrid(
            columns=AxisSpacing(widths=[0.1, 0.2, 0.7]),
            rows=AxisSpacing(ncells=1, total_length=1.0),
            top=0.0,
            layers=[LayerSpec(bottom=-1.0)],
        )

        grid = compile_project(project(grid=graded)).grid

        assert grid.delr.tolist() == [0.1, 0.2, 0.7]

    def test_sublayers_are_split_into_equal_thicknesses(self) -> None:
        """Three sublayers between 10 and 4 means thicknesses of 2."""
        layered = StructuredGrid(
            columns=AxisSpacing(ncells=1, total_length=1.0),
            rows=AxisSpacing(ncells=1, total_length=1.0),
            top=10.0,
            layers=[LayerSpec(bottom=4.0, sublayers=3)],
        )

        grid = compile_project(project(grid=layered)).grid

        assert grid.nlay == 3
        assert grid.botm[:, 0, 0].tolist() == [8.0, 6.0, 4.0]

    def test_layers_stack_without_a_gap(self) -> None:
        stacked = StructuredGrid(
            columns=AxisSpacing(ncells=1, total_length=1.0),
            rows=AxisSpacing(ncells=1, total_length=1.0),
            top=0.0,
            layers=[LayerSpec(bottom=-2.0, sublayers=2), LayerSpec(bottom=-5.0)],
        )

        grid = compile_project(project(grid=stacked)).grid

        assert grid.botm[:, 0, 0].tolist() == [-1.0, -2.0, -5.0]

    def test_origin_and_rotation_survive(self) -> None:
        placed = StructuredGrid(
            origin_x=500.0,
            origin_y=-250.0,
            rotation=30.0,
            columns=AxisSpacing(ncells=2, total_length=2.0),
            rows=AxisSpacing(ncells=2, total_length=2.0),
            top=0.0,
            layers=[LayerSpec(bottom=-1.0)],
        )

        grid = compile_project(project(grid=placed)).grid

        assert (grid.origin_x, grid.origin_y, grid.rotation) == (500.0, -250.0, 30.0)


class TestProperties:
    def test_a_constant_fills_the_grid(self) -> None:
        model = compile_project(project(flow=FlowModel(properties=FlowProperties(k=constant(7.5)))))

        assert model.properties["k"].shape == model.grid.shape
        assert np.all(model.properties["k"] == 7.5)

    def test_vertical_conductivity_defaults_to_the_horizontal_value(self) -> None:
        model = compile_project(project(flow=FlowModel(properties=FlowProperties(k=constant(3.0)))))

        np.testing.assert_array_equal(model.properties["k33"], model.properties["k"])

    def test_an_explicit_vertical_conductivity_is_used(self) -> None:
        model = compile_project(
            project(flow=FlowModel(properties=FlowProperties(k=constant(3.0), k33=constant(0.3))))
        )

        assert np.all(model.properties["k33"] == 0.3)

    def test_transport_porosity_falls_back_to_the_flow_porosity(self) -> None:
        model = compile_project(
            project(flow=FlowModel(properties=FlowProperties(porosity=constant(0.4))))
        )

        assert np.all(model.properties["transport_porosity"] == 0.4)

    def test_a_zone_field_uses_its_default_and_says_so(self) -> None:
        """Zone geometry arrives with the builder; until then this must not fail."""
        model = compile_project(
            project(
                flow=FlowModel(
                    properties=FlowProperties(k=ZoneField(default=2.0, values={"sand": 9.0}))
                )
            )
        )

        assert np.all(model.properties["k"] == 2.0)
        assert any("zone" in warning for warning in model.warnings)

    def test_a_zone_field_with_no_zones_warns_about_nothing(self) -> None:
        model = compile_project(
            project(flow=FlowModel(properties=FlowProperties(k=ZoneField(default=2.0))))
        )

        assert model.warnings == []


class TestArrayFields:
    def test_loads_a_full_three_dimensional_array(self, tmp_path: Path) -> None:
        values = np.arange(10, dtype=float).reshape(1, 1, 10)
        np.save(tmp_path / "k.npy", values)

        model = compile_project(
            project(flow=FlowModel(properties=FlowProperties(k=ArrayField(path="k.npy")))),
            root=tmp_path,
        )

        np.testing.assert_array_equal(model.properties["k"], values)

    def test_broadcasts_a_single_layer_across_the_grid(self, tmp_path: Path) -> None:
        layered = StructuredGrid(
            columns=AxisSpacing(ncells=4, total_length=4.0),
            rows=AxisSpacing(ncells=2, total_length=2.0),
            top=0.0,
            layers=[LayerSpec(bottom=-1.0, sublayers=3)],
        )
        np.save(tmp_path / "k.npy", np.full((2, 4), 5.0))

        model = compile_project(
            project(
                grid=layered,
                flow=FlowModel(properties=FlowProperties(k=ArrayField(path="k.npy"))),
            ),
            root=tmp_path,
        )

        assert model.properties["k"].shape == (3, 2, 4)
        assert np.all(model.properties["k"] == 5.0)

    def test_reports_an_array_that_does_not_fit(self, tmp_path: Path) -> None:
        np.save(tmp_path / "k.npy", np.zeros((3, 3)))

        with pytest.raises(CompileError, match="does not fit"):
            compile_project(
                project(flow=FlowModel(properties=FlowProperties(k=ArrayField(path="k.npy")))),
                root=tmp_path,
            )

    def test_reports_a_missing_array(self, tmp_path: Path) -> None:
        with pytest.raises(CompileError, match="does not exist"):
            compile_project(
                project(flow=FlowModel(properties=FlowProperties(k=ArrayField(path="gone.npy")))),
                root=tmp_path,
            )

    def test_reports_an_array_reference_with_nowhere_to_look(self) -> None:
        with pytest.raises(CompileError, match="no project directory"):
            compile_project(
                project(flow=FlowModel(properties=FlowProperties(k=ArrayField(path="k.npy"))))
            )


class TestBoundaries:
    def test_cell_indices_become_zero_based(self) -> None:
        """The schema counts from one to match MODFLOW input; FloPy counts from zero."""
        model = compile_project(
            project(
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[1], rows=[1], columns=[10]),
                            rate=ConstantSeries(value=-1.0),
                        )
                    ]
                )
            )
        )

        cell, *_ = model.boundary("w").spd[0][0]
        assert cell == (0, 0, 9)

    def test_a_selection_expands_to_every_combination(self) -> None:
        model = compile_project(
            project(
                grid=StructuredGrid(
                    columns=AxisSpacing(ncells=3, total_length=3.0),
                    rows=AxisSpacing(ncells=2, total_length=2.0),
                    top=0.0,
                    layers=[LayerSpec(bottom=-1.0, sublayers=2)],
                ),
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[1, 2], rows=[1, 2], columns=[1, 2, 3]),
                            rate=ConstantSeries(value=-1.0),
                        )
                    ]
                ),
            )
        )

        assert model.boundary("w").cell_count == 2 * 2 * 3

    def test_a_constant_series_repeats_across_periods(self) -> None:
        model = compile_project(
            project(
                time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0)] * 3),
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[1], rows=[1], columns=[1]),
                            rate=ConstantSeries(value=-2.0),
                        )
                    ]
                ),
            )
        )

        rates = {model.boundary("w").spd[period][0][1] for period in range(3)}
        assert rates == {-2.0}

    def test_a_per_period_series_varies_by_period(self) -> None:
        model = compile_project(
            project(
                time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0)] * 3),
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[1], rows=[1], columns=[1]),
                            rate=PerPeriodSeries(values=[-1.0, -2.0, -3.0]),
                        )
                    ]
                ),
            )
        )

        assert [model.boundary("w").spd[period][0][1] for period in range(3)] == [
            -1.0,
            -2.0,
            -3.0,
        ]

    def test_a_solute_carrying_boundary_gains_a_concentration_value(self) -> None:
        model = compile_project(
            project(
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[1], rows=[1], columns=[1]),
                            rate=ConstantSeries(value=1.0),
                            concentration=ConstantSeries(value=0.25),
                        )
                    ]
                )
            )
        )

        boundary = model.boundary("w")
        assert boundary.carries_solute
        assert boundary.spd[0][0] == ((0, 0, 0), 1.0, 0.25)

    def test_an_unstated_concentration_becomes_zero(self) -> None:
        """Water with no stated chemistry carries no solute, not undefined solute."""
        model = compile_project(
            project(
                flow=FlowModel(
                    packages=[
                        ConstantHeadPackage(
                            id="c",
                            cells=CellRange(layers=[1], rows=[1], columns=[1]),
                            head=ConstantSeries(value=0.0),
                        )
                    ]
                )
            )
        )

        assert model.boundary("c").spd[0][0][2] == 0.0

    def test_recharge_without_named_cells_covers_the_top_layer(self) -> None:
        model = compile_project(
            project(
                grid=StructuredGrid(
                    columns=AxisSpacing(ncells=4, total_length=4.0),
                    rows=AxisSpacing(ncells=3, total_length=3.0),
                    top=0.0,
                    layers=[LayerSpec(bottom=-1.0, sublayers=2)],
                ),
                flow=FlowModel(packages=[RechargePackage(id="r", rate=ConstantSeries(value=1e-4))]),
            )
        )

        boundary = model.boundary("r")
        assert boundary.cell_count == 12
        assert all(cell[0] == 0 for cell, *_ in boundary.spd[0])
