"""The layered prismatic mesh every grid reduces to.

DIS and DISV models both land here. FloPy exposes a shared vertex/cell-vertex
view of either, so the renderer never needs to know which one it started as —
the only structural difference is how many corners a cell has.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DisvMesh:
    """A 2D cell footprint plus per-layer top and bottom elevations.

    Attributes:
        vertices: ``(nverts, 2)`` float32 xy of the footprint.
        cell_offsets: ``(ncpl + 1,)`` int32 CSR offsets into ``cell_indices``.
        cell_indices: ``(total_corners,)`` int32 vertex index per cell corner.
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
        """Stable identity, so a client can tell one grid from another."""
        digest = hashlib.sha256()
        for array in (self.vertices, self.cell_indices, self.top, self.botm):
            digest.update(np.ascontiguousarray(array).tobytes())
        return digest.hexdigest()[:16]

    @property
    def thin_axis(self) -> str | None:
        """Which horizontal axis has only one cell across it, if either does.

        A model discretised as a single row or column is a 1D or 2D profile, but
        its width is a real number chosen by whoever built it — often 1 m,
        because it makes hand-checking geometry easy. That width can exceed the
        modelled length, so the profile renders as a slab. Reporting the thin
        axis lets a client offer to squash it.
        """
        unique_x = len(np.unique(np.round(self.cell_centers[:, 0].astype(np.float64), 6)))
        unique_y = len(np.unique(np.round(self.cell_centers[:, 1].astype(np.float64), 6)))

        if unique_y == 1 and unique_x > 1:
            return "y"
        if unique_x == 1 and unique_y > 1:
            return "x"
        return None

    def axis_extents(self) -> tuple[float, float, float]:
        """World extent along x, y and z."""
        xmin, ymin, zmin, xmax, ymax, zmax = self.bounds
        return (xmax - xmin, ymax - ymin, zmax - zmin)

    def validate(self) -> None:
        """Check the invariants the renderer relies on."""
        if self.cell_offsets.shape != (self.ncpl + 1,):
            raise ValueError(
                f"cell_offsets should have {self.ncpl + 1} entries, has {self.cell_offsets.shape}"
            )
        if int(self.cell_offsets[-1]) != int(self.cell_indices.size):
            raise ValueError("the last CSR offset does not match the index count")
        if self.cell_indices.size and int(self.cell_indices.max()) >= self.vertices.shape[0]:
            raise ValueError("a cell references a vertex that does not exist")
        if self.top.shape != self.botm.shape:
            raise ValueError(f"top {self.top.shape} and botm {self.botm.shape} disagree")
        if np.any(np.diff(self.cell_offsets) < 3):
            raise ValueError("every cell needs at least three corners")


def csr_from_iverts(iverts: list[list[int]]) -> tuple[np.ndarray, np.ndarray]:
    """Turn FloPy's ragged cell-vertex lists into CSR offsets and indices.

    FloPy sometimes repeats the first vertex at the end to close the ring;
    that duplicate is dropped, since the renderer closes polygons itself and a
    repeated corner would produce a degenerate triangle.
    """
    offsets = np.zeros(len(iverts) + 1, dtype=np.int32)
    flat: list[int] = []

    for index, corners in enumerate(iverts):
        ring = list(corners)
        if len(ring) > 3 and ring[0] == ring[-1]:
            ring = ring[:-1]
        flat.extend(ring)
        offsets[index + 1] = len(flat)

    return offsets, np.asarray(flat, dtype=np.int32)
