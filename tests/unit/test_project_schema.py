"""The project schema, and the validation that makes a loaded project trustworthy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mupstudio.schema.common import (
    ConstantSeries,
    PerPeriodSeries,
    StressPeriod,
    TimeDiscretisation,
    constant,
)
from mupstudio.schema.flow import CellRange, ConstantHeadPackage, FlowModel, WellPackage
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid, column_grid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.transport import DualPorosity, TransportModel


def project(**overrides) -> Project:
    """A minimal valid project, with fields replaced as needed."""
    defaults = {
        "meta": ProjectMeta(name="test", engine="mf6rtm"),
        "grid": column_grid(ncells=50, length=0.5),
        "time": TimeDiscretisation(periods=[StressPeriod(perlen=1.0)]),
    }
    return Project(**{**defaults, **overrides})


class TestAxisSpacing:
    def test_equal_cells_from_a_count_and_a_length(self) -> None:
        spacing = AxisSpacing(ncells=4, total_length=2.0)

        assert spacing.resolve() == [0.5, 0.5, 0.5, 0.5]
        assert spacing.count == 4
        assert spacing.length == pytest.approx(2.0)

    def test_graded_cells_from_explicit_widths(self) -> None:
        spacing = AxisSpacing(widths=[0.1, 0.2, 0.4])

        assert spacing.count == 3
        assert spacing.length == pytest.approx(0.7)

    def test_rejects_describing_it_both_ways(self) -> None:
        with pytest.raises(ValidationError, match="but not both"):
            AxisSpacing(ncells=4, total_length=2.0, widths=[1.0])

    def test_rejects_describing_it_neither_way(self) -> None:
        with pytest.raises(ValidationError, match="either ncells"):
            AxisSpacing()

    def test_rejects_a_zero_width_cell(self) -> None:
        with pytest.raises(ValidationError, match="must be positive"):
            AxisSpacing(widths=[0.5, 0.0])


class TestStructuredGrid:
    def test_a_column_is_one_row_and_one_layer(self) -> None:
        grid = column_grid(ncells=50, length=0.5)

        assert (grid.nlay, grid.nrow, grid.ncol) == (1, 1, 50)
        assert grid.ncells == 50

    def test_a_column_defaults_to_unit_width_and_thickness(self) -> None:
        """1 m makes cell volume equal cell length, which is why people use it."""
        grid = column_grid(ncells=10, length=1.0)

        assert grid.rows.length == pytest.approx(1.0)
        assert grid.top.value - grid.layers[0].bottom.value == pytest.approx(1.0)

    def test_sublayers_multiply_the_layer_count(self) -> None:
        grid = StructuredGrid(
            columns=AxisSpacing(ncells=2, total_length=2.0),
            rows=AxisSpacing(ncells=2, total_length=2.0),
            top=10.0,
            layers=[LayerSpec(bottom=5.0, sublayers=3), LayerSpec(bottom=0.0, sublayers=2)],
        )

        assert grid.nlay == 5
        assert grid.ncells == 5 * 4

    def test_rejects_layers_that_do_not_descend(self) -> None:
        with pytest.raises(ValidationError, match="must descend"):
            StructuredGrid(
                columns=AxisSpacing(ncells=1, total_length=1.0),
                rows=AxisSpacing(ncells=1, total_length=1.0),
                top=0.0,
                layers=[LayerSpec(bottom=-1.0), LayerSpec(bottom=-0.5)],
            )

    def test_rejects_a_layer_bottom_above_the_model_top(self) -> None:
        with pytest.raises(ValidationError, match="model top"):
            StructuredGrid(
                columns=AxisSpacing(ncells=1, total_length=1.0),
                rows=AxisSpacing(ncells=1, total_length=1.0),
                top=0.0,
                layers=[LayerSpec(bottom=5.0)],
            )


class TestTime:
    def test_reports_period_count_and_total(self) -> None:
        time = TimeDiscretisation(
            periods=[StressPeriod(perlen=1.0), StressPeriod(perlen=2.5, nstp=10)]
        )

        assert time.nper == 2
        assert time.total_time == pytest.approx(3.5)

    def test_rejects_a_model_with_no_periods(self) -> None:
        with pytest.raises(ValidationError):
            TimeDiscretisation(periods=[])

    def test_rejects_a_period_with_no_length(self) -> None:
        with pytest.raises(ValidationError):
            TimeDiscretisation(periods=[StressPeriod(perlen=0)])


class TestCrossReferences:
    def test_catches_a_cell_index_outside_the_grid(self) -> None:
        with pytest.raises(ValidationError, match="but the grid has 50"):
            project(
                flow=FlowModel(
                    packages=[
                        ConstantHeadPackage(
                            id="inflow",
                            cells=CellRange(layers=[1], rows=[1], columns=[99]),
                            head=ConstantSeries(value=0.0),
                        )
                    ]
                )
            )

    def test_catches_a_zero_cell_index(self) -> None:
        """Indices are 1-based to match MODFLOW input, so 0 is a mistake."""
        with pytest.raises(ValidationError, match="indices start at 1"):
            project(
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[0], rows=[1], columns=[1]),
                            rate=ConstantSeries(value=-1.0),
                        )
                    ]
                )
            )

    def test_catches_two_packages_with_the_same_id(self) -> None:
        cells = CellRange(layers=[1], rows=[1], columns=[1])
        with pytest.raises(ValidationError, match="share the id"):
            project(
                flow=FlowModel(
                    packages=[
                        WellPackage(id="w", cells=cells, rate=ConstantSeries(value=1.0)),
                        WellPackage(id="w", cells=cells, rate=ConstantSeries(value=2.0)),
                    ]
                )
            )

    def test_catches_a_series_that_does_not_cover_every_period(self) -> None:
        with pytest.raises(ValidationError, match="but the model has 3 stress periods"):
            project(
                time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0)] * 3),
                flow=FlowModel(
                    packages=[
                        WellPackage(
                            id="w",
                            cells=CellRange(layers=[1], rows=[1], columns=[1]),
                            rate=PerPeriodSeries(values=[1.0, 2.0]),
                        )
                    ]
                ),
            )

    def test_accepts_a_series_covering_every_period(self) -> None:
        built = project(
            time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0)] * 3),
            flow=FlowModel(
                packages=[
                    WellPackage(
                        id="w",
                        cells=CellRange(layers=[1], rows=[1], columns=[1]),
                        rate=PerPeriodSeries(values=[1.0, 2.0, 3.0]),
                    )
                ]
            ),
        )

        assert built.package_ids == ["w"]

    def test_a_constant_series_needs_no_period_count(self) -> None:
        built = project(
            time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0)] * 9),
            flow=FlowModel(
                packages=[
                    WellPackage(
                        id="w",
                        cells=CellRange(layers=[1], rows=[1], columns=[1]),
                        rate=ConstantSeries(value=-5.0),
                    )
                ]
            ),
        )

        assert built.time.nper == 9


class TestEngineCapabilities:
    def test_pht3d_rejects_dual_porosity_nowhere_but_accepts_it(self) -> None:
        built = project(
            meta=ProjectMeta(name="dp", engine="pht3d"),
            transport=TransportModel(
                dual_porosity=DualPorosity(
                    immobile_porosity=constant(0.1), transfer_rate=constant(1e-3)
                )
            ),
        )

        assert built.transport.dual_porosity is not None

    def test_mf6rtm_rejects_dual_porosity_until_upstream_supports_it(self) -> None:
        with pytest.raises(ValidationError, match="not supported by MF6RTM"):
            project(
                transport=TransportModel(
                    dual_porosity=DualPorosity(
                        immobile_porosity=constant(0.1), transfer_rate=constant(1e-3)
                    )
                )
            )


class TestPropertyFields:
    def test_a_constant_is_the_default_shape(self) -> None:
        assert project().flow.properties.k.kind == "constant"

    def test_dispersion_reports_itself_disabled_when_all_zero(self) -> None:
        """A pure-advection benchmark wants no dispersion package at all."""
        assert TransportModel().dispersion.enabled is False

    def test_dispersion_reports_itself_enabled_once_set(self) -> None:
        transport = TransportModel()
        transport.dispersion.longitudinal = constant(0.01)

        assert transport.dispersion.enabled is True


def test_describe_summarises_the_model() -> None:
    assert project().describe() == "test: mf6rtm, 1x1x50 (50 cells), 1 stress period"
