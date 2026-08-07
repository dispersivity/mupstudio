"""Drawing a model that has not been run.

The point of this path is to make an input mistake visible before a run rather
than after one, so the tests are about the two things that would defeat that: a
mesh that does not match the grid, and a field whose absent cells are
indistinguishable from real values.
"""

from __future__ import annotations

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.results.datasets import catalog_of
from mupstudio.results.preview import ABSENT, PreviewDataset, preview_of, structured_mesh
from mupstudio.schema.chemistry import CellRange, ChemZone, Composition
from mupstudio.schema.common import ConstantSeries, StressPeriod, TimeDiscretisation, constant
from mupstudio.schema.flow import (
    CellRange as FlowCells,
)
from mupstudio.schema.flow import (
    FlowModel,
    FlowProperties,
    RechargePackage,
    WellPackage,
)
from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.templates import starter_chemistry, starter_column


def box(nlay: int = 2, nrow: int = 3, ncol: int = 4) -> StructuredGrid:
    return StructuredGrid(
        columns=AxisSpacing(ncells=ncol, total_length=float(ncol) * 10),
        rows=AxisSpacing(ncells=nrow, total_length=float(nrow) * 10),
        top=0.0,
        layers=[LayerSpec(bottom=float(-index - 1)) for index in range(nlay)],
    )


def project(grid: StructuredGrid | None = None, **flow: object) -> Project:
    return Project(
        meta=ProjectMeta(name="preview", engine="mf6rtm"),
        grid=grid or box(),
        time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0, nstp=1)]),
        flow=FlowModel(
            properties=FlowProperties(k=constant(5.0), starting_head=constant(1.0)),
            **flow,  # type: ignore[arg-type]
        ),
    )


# --- the mesh ---------------------------------------------------------------


def test_the_mesh_has_one_footprint_per_cell_in_a_layer() -> None:
    mesh = structured_mesh(compile_project(project()).grid)

    assert mesh.ncpl == 12
    assert mesh.nlay == 2
    assert mesh.ncells == 24


def test_every_footprint_is_a_quadrilateral() -> None:
    mesh = structured_mesh(compile_project(project()).grid)

    sizes = np.diff(mesh.cell_offsets)
    assert set(sizes.tolist()) == {4}


def test_the_mesh_is_valid_geometry() -> None:
    """The same check the results reader's meshes go through."""
    structured_mesh(compile_project(project()).grid).validate()


def test_rows_run_from_the_top_down() -> None:
    """MODFLOW numbers row one at the top, and a listing file is read that way.

    Drawn the other way, a boundary in row 1 would appear at the bottom of the
    picture and every check against a listing file would be inverted.
    """
    mesh = structured_mesh(compile_project(project()).grid)
    centers = mesh.cell_centers

    first_row = centers[0][1]
    last_row = centers[-1][1]
    assert first_row > last_row


def test_the_origin_moves_the_mesh() -> None:
    grid = box()
    placed = grid.model_copy(update={"origin_x": 1000.0, "origin_y": 2000.0})

    mesh = structured_mesh(compile_project(project(placed)).grid)

    assert mesh.vertices[:, 0].min() == pytest.approx(1000.0)
    assert mesh.vertices[:, 1].min() == pytest.approx(2000.0)


def test_layer_tops_stack_on_the_layer_above() -> None:
    mesh = structured_mesh(compile_project(project()).grid)

    # The second layer's top is the first layer's bottom.
    np.testing.assert_allclose(mesh.top[1], mesh.botm[0])
    assert np.all(mesh.top[0] == 0.0)


# --- the fields -------------------------------------------------------------


def test_properties_are_drawable() -> None:
    preview = preview_of(project())

    assert "k" in preview.component_names()
    assert preview.component_range("k") == (5.0, 5.0)
    assert preview.component_unit("k") == "length/time"


def test_a_boundary_is_drawn_where_it_acts_and_nowhere_else() -> None:
    """One cell of twelve, which is the case the whole feature exists for."""
    preview = preview_of(
        project(
            packages=[
                WellPackage(
                    id="pump",
                    cells=FlowCells(layers=[1], rows=[2], columns=[3]),
                    rate=ConstantSeries(value=-25.0),
                )
            ]
        )
    )

    values = preview.timestep("boundary:pump", 0)
    assert values.shape == (2, 12)
    # Row 2, column 3 of a four-column grid is index 6 within the layer.
    assert values[0, 6] == pytest.approx(-25.0)
    assert int(np.count_nonzero(values != np.float32(ABSENT))) == 1


def test_absent_cells_carry_the_sentinel_and_not_a_nan() -> None:
    """NaN would be the obvious choice and the renderer cannot rely on it.

    The only portable test for NaN is self-inequality, and a driver told it may
    assume no NaN exists is free to optimise that away — Metal does. So a field
    that reached the GPU carrying NaN would draw its absent cells as real values
    at the bottom of the colour ramp, hiding the cells that matter.
    """
    preview = preview_of(
        project(
            packages=[
                WellPackage(
                    id="pump",
                    cells=FlowCells(layers=[1], rows=[1], columns=[1]),
                    rate=ConstantSeries(value=1.0),
                )
            ]
        )
    )

    values = preview.timestep("boundary:pump", 0)

    assert not np.any(np.isnan(values))
    assert np.count_nonzero(values == np.float32(ABSENT)) == values.size - 1


def test_the_range_ignores_the_cells_with_no_value() -> None:
    """Otherwise the sentinel becomes the minimum and the scale is unusable."""
    preview = preview_of(
        project(
            packages=[
                WellPackage(
                    id="pump",
                    cells=FlowCells(layers=[1], rows=[1], columns=[1]),
                    rate=ConstantSeries(value=-7.5),
                )
            ]
        )
    )

    assert preview.component_range("boundary:pump") == (-7.5, -7.5)


def test_a_field_that_covers_nothing_still_has_a_usable_range() -> None:
    """A recharge package of zero everywhere is drawable, not an error."""
    preview = preview_of(
        project(packages=[RechargePackage(id="rain", rate=ConstantSeries(value=0.0))])
    )

    low, high = preview.component_range("boundary:rain")
    assert low <= high


def test_a_boundary_reports_how_many_cells_it_covers() -> None:
    """A well on one cell and a property on every cell can share a value.

    The legend has to tell them apart, or a single well reads as a rate applied
    to the whole model.
    """
    preview = preview_of(
        project(packages=[RechargePackage(id="rain", rate=ConstantSeries(value=1e-4))])
    )
    described = {item["name"]: item for item in preview.describe()["fields"]}

    # Recharge is areal: every cell of the top layer, and none below it.
    assert described["boundary:rain"]["setCells"] == 12
    assert described["k"]["setCells"] == 24


def test_chemistry_zones_are_drawn_as_their_assemblage_numbers() -> None:
    base = starter_chemistry()
    chemistry = base.model_copy(
        update={
            "compositions": [*base.compositions, Composition(id="clean", solution="inflow")],
            "zones": [
                ChemZone(
                    id="patch",
                    composition="clean",
                    cells=CellRange(layers=[1], rows=[1], columns=[9, 10]),
                )
            ],
        }
    )
    reactive = Project.model_validate(
        {
            **starter_column("c", cells=10).model_dump(),
            "chemistry": chemistry.model_dump(),
        }
    )

    preview = preview_of(reactive)
    solutions = preview.timestep("chemistry:solution", 0)[0]

    assert list(solutions[:8]) == [1.0] * 8
    assert list(solutions[8:]) == [2.0, 2.0]


def test_a_block_nothing_uses_is_not_offered() -> None:
    """A flat picture of zeros is only clutter in the field list."""
    reactive = Project.model_validate(
        {
            **starter_column("c", cells=5).model_dump(),
            "chemistry": starter_chemistry().model_dump(),
        }
    )
    names = preview_of(reactive).component_names()

    assert "chemistry:solution" in names
    assert "chemistry:exchange" not in names


def test_a_project_without_chemistry_offers_no_chemistry_fields() -> None:
    assert not any(
        name.startswith("chemistry:") for name in preview_of(project()).component_names()
    )


# --- the catalog ------------------------------------------------------------


def test_the_catalog_says_the_model_has_not_been_run() -> None:
    """So the screen can say so, rather than looking like a result."""
    catalog = catalog_of(preview_of(project()))

    assert catalog["kind"] == "preview"
    assert catalog["status"] == "not run"
    assert catalog["ncells"] == 24


def test_the_catalog_carries_the_grouping_the_picker_needs() -> None:
    preview = preview_of(
        project(
            packages=[
                WellPackage(
                    id="pump",
                    cells=FlowCells(layers=[1], rows=[1], columns=[1]),
                    rate=ConstantSeries(value=1.0),
                )
            ]
        )
    )
    kinds = {item["name"]: item["kind"] for item in catalog_of(preview)["fields"]}

    assert kinds["k"] == "property"
    assert kinds["boundary:pump"] == "boundary"


def test_there_is_one_timestep_and_nothing_to_scrub() -> None:
    """These are inputs, not a history."""
    preview = preview_of(project())

    assert preview.times == [0.0]
    with pytest.raises(IndexError, match="nothing to scrub"):
        preview.timestep("k", 1)


def test_an_unknown_field_names_what_there_is() -> None:
    with pytest.raises(KeyError, match="have:"):
        preview_of(project()).timestep("nonsense", 0)


def test_a_column_is_reported_as_thin_so_it_can_be_squashed() -> None:
    """One cell across draws as a slab at true scale, hiding the length."""
    preview = PreviewDataset(compile_project(starter_column("c", cells=50)))

    assert preview.mesh.thin_axis == "y"
