from __future__ import annotations

import numpy as np
import pytest

from mupstudio.grids.synthetic import DisvMesh, hex_footprint, synthetic_disv, synthetic_scalars


@pytest.fixture(scope="module")
def mesh() -> DisvMesh:
    return synthetic_disv(ncpl_target=400, nlay=4)


def test_cell_count_is_close_to_the_target(mesh: DisvMesh) -> None:
    assert 350 <= mesh.ncpl <= 450
    assert mesh.nlay == 4
    assert mesh.ncells == mesh.nlay * mesh.ncpl


def test_arrays_have_the_dtypes_the_gpu_expects(mesh: DisvMesh) -> None:
    assert mesh.vertices.dtype == np.float32
    assert mesh.cell_centers.dtype == np.float32
    assert mesh.top.dtype == np.float32
    assert mesh.botm.dtype == np.float32
    assert mesh.cell_offsets.dtype == np.int32
    assert mesh.cell_indices.dtype == np.int32


def test_csr_offsets_describe_six_sided_cells(mesh: DisvMesh) -> None:
    assert mesh.cell_offsets.shape == (mesh.ncpl + 1,)
    assert mesh.cell_offsets[0] == 0
    assert mesh.cell_offsets[-1] == mesh.cell_indices.size
    assert np.all(np.diff(mesh.cell_offsets) == 6)


def test_every_index_points_at_a_real_vertex(mesh: DisvMesh) -> None:
    assert mesh.cell_indices.min() >= 0
    assert mesh.cell_indices.max() < mesh.vertices.shape[0]


def test_vertices_are_shared_between_neighbours(mesh: DisvMesh) -> None:
    """Deduplication is what keeps the vertex buffer small; without it this is 6x."""
    assert mesh.vertices.shape[0] < mesh.ncpl * 6
    assert mesh.vertices.shape[0] < mesh.ncpl * 3


def test_interior_corners_are_shared_by_three_cells() -> None:
    """In a honeycomb every interior corner meets three cells.

    Float error in the corner maths once left duplicates that looked like
    distinct vertices, inflating the buffer by 60% and breaking nothing
    visibly, so this asserts the topology rather than just the size.
    """
    mesh = synthetic_disv(ncpl_target=3600, nlay=1)
    sharing = np.bincount(mesh.cell_indices, minlength=mesh.vertices.shape[0])

    assert sharing.max() == 3
    # Boundary corners are shared by one or two, so the mean sits below three
    # but must be close to it once the interior dominates.
    assert sharing.mean() > 2.8
    assert mesh.vertices.shape[0] < mesh.ncpl * 2.2


def test_no_cell_repeats_a_vertex(mesh: DisvMesh) -> None:
    """A repeated corner means a degenerate polygon, which renders as a gap."""
    per_cell = mesh.cell_indices.reshape(-1, 6)
    unique_per_cell = np.array([np.unique(cell).size for cell in per_cell])

    assert np.all(unique_per_cell == 6)


def test_cells_have_positive_thickness(mesh: DisvMesh) -> None:
    assert np.all(mesh.top > mesh.botm)


def test_layers_stack_without_gaps_or_overlap(mesh: DisvMesh) -> None:
    for layer in range(mesh.nlay - 1):
        np.testing.assert_allclose(mesh.botm[layer], mesh.top[layer + 1], rtol=1e-6)


def test_top_surface_varies_across_the_domain(mesh: DisvMesh) -> None:
    """A flat surface would let a broken extrusion shader look correct."""
    assert mesh.top[0].std() > 1.0


def test_bounds_cover_the_geometry(mesh: DisvMesh) -> None:
    xmin, ymin, zmin, xmax, ymax, zmax = mesh.bounds

    assert xmin < xmax and ymin < ymax and zmin < zmax
    assert zmin == pytest.approx(float(mesh.botm.min()))
    assert zmax == pytest.approx(float(mesh.top.max()))


def test_grid_hash_is_stable_and_distinguishes_grids() -> None:
    a = synthetic_disv(ncpl_target=100, nlay=2)
    again = synthetic_disv(ncpl_target=100, nlay=2)
    different = synthetic_disv(ncpl_target=100, nlay=3)

    assert a.grid_hash == again.grid_hash
    assert a.grid_hash != different.grid_hash


@pytest.mark.parametrize("ncpl_target", [1, 7, 1000])
def test_small_and_odd_sizes_still_build(ncpl_target: int) -> None:
    mesh = synthetic_disv(ncpl_target=ncpl_target, nlay=1)

    assert mesh.ncpl >= 1
    assert mesh.cell_offsets[-1] == mesh.cell_indices.size


@pytest.mark.parametrize(("ncpl", "nlay"), [(0, 1), (10, 0)])
def test_rejects_empty_grids(ncpl: int, nlay: int) -> None:
    with pytest.raises(ValueError):
        synthetic_disv(ncpl_target=ncpl, nlay=nlay)


def test_hex_footprint_produces_one_cell_per_position() -> None:
    vertices, offsets, indices, centers = hex_footprint(4, 3)

    assert centers.shape == (12, 2)
    assert offsets.shape == (13,)
    assert indices.size == 72
    assert vertices.shape[1] == 2


class TestScalars:
    def test_shape_matches_the_mesh(self, mesh: DisvMesh) -> None:
        values = synthetic_scalars(mesh, ntimes=5)

        assert values.shape == (5, mesh.nlay, mesh.ncpl)
        assert values.dtype == np.float32

    def test_values_are_finite_and_bounded(self, mesh: DisvMesh) -> None:
        values = synthetic_scalars(mesh, ntimes=5)

        assert np.all(np.isfinite(values))
        assert values.min() >= 0.0
        assert values.max() <= 1.0

    def test_the_plume_grows_over_time(self, mesh: DisvMesh) -> None:
        values = synthetic_scalars(mesh, ntimes=10)

        totals = values.sum(axis=(1, 2))
        assert np.all(np.diff(totals) > 0)

    def test_is_deterministic(self, mesh: DisvMesh) -> None:
        np.testing.assert_array_equal(
            synthetic_scalars(mesh, ntimes=4), synthetic_scalars(mesh, ntimes=4)
        )
