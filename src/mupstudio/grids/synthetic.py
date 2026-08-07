"""Synthetic DISV grids for the viewport milestone.

Real grids come from the builder later; the viewport has to be proven against
half a million cells before any of that exists. These grids have the same shape
as real DISV output — a 2D cell footprint mesh plus per-cell top and bottom
elevations per layer — so the rendering path this exercises is the real one.

The footprint is a hex tiling: cells have a uniform vertex count like a
quadtree grid but non-rectangular topology like a Voronoi grid, which is the
awkward case the renderer must handle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

SQRT3 = float(np.sqrt(3.0))


@dataclass(frozen=True)
class DisvMesh:
    """A layered prismatic mesh, in the form the viewport uploads.

    Attributes:
        vertices: ``(nverts, 2)`` float32 xy of the 2D footprint.
        cell_offsets: ``(ncpl + 1,)`` int32 CSR offsets into ``cell_indices``.
        cell_indices: ``(total_cell_verts,)`` int32 vertex index per cell corner,
            counter-clockwise.
        cell_centers: ``(ncpl, 2)`` float32.
        top: ``(nlay, ncpl)`` float32 elevation of each cell's top face.
        botm: ``(nlay, ncpl)`` float32 elevation of each cell's bottom face.
    """

    vertices: np.ndarray
    cell_offsets: np.ndarray
    cell_indices: np.ndarray
    cell_centers: np.ndarray
    top: np.ndarray
    botm: np.ndarray

    @property
    def ncpl(self) -> int:
        """Cells per layer."""
        return int(self.cell_centers.shape[0])

    @property
    def nlay(self) -> int:
        return int(self.top.shape[0])

    @property
    def ncells(self) -> int:
        return self.nlay * self.ncpl

    @property
    def bounds(self) -> tuple[float, float, float, float, float, float]:
        """(xmin, ymin, zmin, xmax, ymax, zmax)."""
        return (
            float(self.vertices[:, 0].min()),
            float(self.vertices[:, 1].min()),
            float(self.botm.min()),
            float(self.vertices[:, 0].max()),
            float(self.vertices[:, 1].max()),
            float(self.top.max()),
        )

    @property
    def grid_hash(self) -> str:
        """Stable identity, so the client can tell one grid from another."""
        digest = hashlib.sha256()
        for array in (self.vertices, self.cell_indices, self.top, self.botm):
            digest.update(np.ascontiguousarray(array).tobytes())
        return digest.hexdigest()[:16]


def hex_footprint(
    nx: int, ny: int, size: float = 1.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build a flat-topped hexagonal tiling with ``nx * ny`` cells.

    Returns deduplicated vertices, the CSR index array (6 per cell), and cell
    centers. Vertices are shared between neighbouring cells, as in a real DISV
    grid, so vertex count is roughly 2x cell count rather than 6x.
    """
    # All geometry is built in float64 and only narrowed at the end. In float32
    # the spacing between representable values across a large domain exceeds the
    # tolerance used to match shared corners, so corners that are the same point
    # fail to merge and the vertex buffer balloons.
    col_grid, row_grid = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")

    # Odd columns are pushed down half a row so the hexagons interlock.
    cx = col_grid * (1.5 * size)
    cy = row_grid * (SQRT3 * size) + (col_grid % 2) * (SQRT3 * size / 2.0)
    centers = np.column_stack([cx.ravel(order="F"), cy.ravel(order="F")])

    angles = np.arange(6) * (np.pi / 3.0)
    corners = np.empty((centers.shape[0], 6, 2))
    corners[:, :, 0] = centers[:, 0, None] + (size * np.cos(angles))[None, :]
    corners[:, :, 1] = centers[:, 1, None] + (size * np.sin(angles))[None, :]

    # Merge shared corners by snapping to a grid far finer than any real
    # feature but far coarser than the accumulated floating point error.
    flat = corners.reshape(-1, 2)
    quantised = np.round(flat / (size * 1e-6)).astype(np.int64)
    _, first_index, inverse = np.unique(quantised, axis=0, return_index=True, return_inverse=True)

    vertices = flat[first_index].astype(np.float32)
    cell_indices = inverse.astype(np.int32).ravel()
    cell_offsets = (np.arange(centers.shape[0] + 1) * 6).astype(np.int32)

    return vertices, cell_offsets, cell_indices, centers.astype(np.float32)


def synthetic_disv(
    ncpl_target: int = 50_000,
    nlay: int = 10,
    *,
    size: float = 1.0,
    surface_relief: float = 30.0,
    layer_thickness: float = 10.0,
) -> DisvMesh:
    """Build a layered hex grid with roughly ``ncpl_target`` cells per layer.

    The top surface undulates so extrusion is visibly doing something and so
    every cell has a distinct elevation, which stops the renderer from
    accidentally passing on degenerate geometry.
    """
    if ncpl_target < 1:
        raise ValueError("ncpl_target must be at least 1")
    if nlay < 1:
        raise ValueError("nlay must be at least 1")

    # Aspect-correct so the domain stays roughly square.
    nx = max(1, round(float(np.sqrt(ncpl_target / (SQRT3 / 1.5)))))
    ny = max(1, round(ncpl_target / nx))

    vertices, cell_offsets, cell_indices, centers = hex_footprint(nx, ny, size)

    span_x = max(float(np.ptp(centers[:, 0])), 1.0)
    span_y = max(float(np.ptp(centers[:, 1])), 1.0)
    wave = np.sin(centers[:, 0] / span_x * 4.0 * np.pi) * np.cos(
        centers[:, 1] / span_y * 3.0 * np.pi
    )
    surface = (wave * surface_relief).astype(np.float32)

    ncpl = centers.shape[0]
    top = np.empty((nlay, ncpl), dtype=np.float32)
    botm = np.empty((nlay, ncpl), dtype=np.float32)
    for layer in range(nlay):
        top[layer] = surface - layer * layer_thickness
        botm[layer] = surface - (layer + 1) * layer_thickness

    return DisvMesh(
        vertices=vertices,
        cell_offsets=cell_offsets,
        cell_indices=cell_indices,
        cell_centers=centers,
        top=top,
        botm=botm,
    )


def synthetic_scalars(
    mesh: DisvMesh,
    ntimes: int = 40,
    *,
    name: str = "concentration",
    seed: int = 0,
) -> np.ndarray:
    """A plume spreading from a corner, as ``(ntimes, nlay, ncpl)`` float32.

    Deterministic given the same mesh and seed so perf runs and pixel
    comparisons are reproducible.
    """
    del name, seed  # kept for signature stability; the field is fully determined

    centers = mesh.cell_centers
    origin = centers.min(axis=0)
    extent = np.maximum(np.ptp(centers, axis=0), 1.0)
    normalised = (centers - origin) / extent
    distance = np.sqrt(normalised[:, 0] ** 2 + normalised[:, 1] ** 2)

    layer_depth = (np.arange(mesh.nlay, dtype=np.float32) / max(mesh.nlay - 1, 1))[:, None]

    values = np.empty((ntimes, mesh.nlay, mesh.ncpl), dtype=np.float32)
    for step in range(ntimes):
        front = 0.15 + 1.6 * (step / max(ntimes - 1, 1))
        # Smooth front, attenuated with depth: a plausible-looking plume.
        values[step] = np.exp(-(((distance[None, :] - 0.0) / front) ** 2)) * (
            1.0 - 0.6 * layer_depth
        )

    return values
