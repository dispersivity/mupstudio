"""Detecting a grid that is one cell across.

A single-row or single-column model is a profile, but its width is a real
number someone chose — 1 m is common because it makes geometry easy to check by
hand. That width can exceed the modelled length, so the profile renders as a
slab unless the client is told which axis to offer squashing.
"""

from __future__ import annotations

import numpy as np
import pytest

from mupstudio.grids.mesh import DisvMesh
from mupstudio.grids.synthetic import synthetic_disv


def strip(ncells: int, *, along: str, length: float = 0.5, width: float = 1.0) -> DisvMesh:
    """A row of quads one cell across, laid out along x or y."""
    positions = np.linspace(0, length, ncells + 1)
    centers = []
    vertices: list[list[float]] = []
    offsets = [0]
    indices: list[int] = []

    for index in range(ncells):
        low, high = positions[index], positions[index + 1]
        corners = (
            [(low, 0.0), (high, 0.0), (high, width), (low, width)]
            if along == "x"
            else [(0.0, low), (width, low), (width, high), (0.0, high)]
        )
        base = len(vertices)
        vertices.extend([list(corner) for corner in corners])
        indices.extend([base, base + 1, base + 2, base + 3])
        offsets.append(len(indices))
        centers.append(
            [(low + high) / 2, width / 2] if along == "x" else [width / 2, (low + high) / 2]
        )

    ncpl = ncells
    return DisvMesh(
        vertices=np.asarray(vertices, dtype=np.float32),
        cell_offsets=np.asarray(offsets, dtype=np.int32),
        cell_indices=np.asarray(indices, dtype=np.int32),
        cell_centers=np.asarray(centers, dtype=np.float32),
        top=np.zeros((1, ncpl), dtype=np.float32),
        botm=np.full((1, ncpl), -1.0, dtype=np.float32),
    )


def test_a_row_of_cells_is_thin_across_y() -> None:
    mesh = strip(50, along="x")

    assert mesh.thin_axis == "y"


def test_a_column_of_cells_is_thin_across_x() -> None:
    mesh = strip(50, along="y")

    assert mesh.thin_axis == "x"


def test_a_full_grid_has_no_thin_axis() -> None:
    mesh = synthetic_disv(ncpl_target=400, nlay=2)

    assert mesh.thin_axis is None


def test_a_single_cell_has_no_thin_axis() -> None:
    """One cell is thin both ways, so neither axis is the interesting one."""
    mesh = strip(1, along="x")

    assert mesh.thin_axis is None


def test_detection_survives_float_noise_in_cell_centers() -> None:
    """Centers computed by MODFLOW are not bit-identical across a row."""
    mesh = strip(20, along="x")
    jittered = mesh.cell_centers.copy()
    jittered[:, 1] += np.float32(1e-9)

    noisy = DisvMesh(
        vertices=mesh.vertices,
        cell_offsets=mesh.cell_offsets,
        cell_indices=mesh.cell_indices,
        cell_centers=jittered,
        top=mesh.top,
        botm=mesh.botm,
    )

    assert noisy.thin_axis == "y"


def test_extents_report_the_world_size() -> None:
    mesh = strip(50, along="x", length=0.5, width=1.0)

    x, y, z = mesh.axis_extents()

    assert x == pytest.approx(0.5)
    assert y == pytest.approx(1.0)
    assert z == pytest.approx(1.0)


def test_the_case_that_prompted_this() -> None:
    """A 50-cell column 0.5 m long but 1 m wide: wider than it is long."""
    mesh = strip(50, along="x", length=0.5, width=1.0)
    x, y, _ = mesh.axis_extents()

    assert y > x, "this is why the profile needs squashing to be readable"
    assert mesh.thin_axis == "y"
