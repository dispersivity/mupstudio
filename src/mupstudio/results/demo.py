"""The demo dataset the viewport milestone renders.

Stands in for a real run's results store until the engine adapters exist. It
holds a synthetic DISV mesh and its scalar fields, and knows how to turn them
into the frames the client uploads to the GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from mupstudio.grids.synthetic import DisvMesh, synthetic_disv, synthetic_scalars
from mupstudio.server.ws.frames import encode

# Time decimation budget. All timesteps live in GPU buffers so scrubbing is a
# buffer swap, which means a large field can exceed what the GPU will hold.
# Rather than truncate the run, whole timesteps are dropped at a fixed stride
# and the client is told the stride so it can label the time axis honestly.
DEFAULT_MAX_BYTES = 1_500 * 1024 * 1024


@dataclass(frozen=True)
class ComponentInfo:
    name: str
    unit: str
    vmin: float
    vmax: float


@dataclass(frozen=True)
class Dataset:
    """A mesh plus its scalar fields, keyed by component name."""

    name: str
    mesh: DisvMesh
    times: list[float]
    scalars: dict[str, np.ndarray]

    @property
    def ntimes(self) -> int:
        return len(self.times)

    def component_info(self, component: str) -> ComponentInfo:
        values = self.require(component)
        return ComponentInfo(
            name=component,
            unit="mol/L",
            vmin=float(values.min()),
            vmax=float(values.max()),
        )

    def require(self, component: str) -> np.ndarray:
        try:
            return self.scalars[component]
        except KeyError:
            known = ", ".join(sorted(self.scalars)) or "none"
            raise KeyError(f"no component {component!r} in {self.name} (have: {known})") from None

    def catalog(self) -> dict[str, object]:
        """Metadata the client needs before requesting any arrays."""
        xmin, ymin, zmin, xmax, ymax, zmax = self.mesh.bounds
        return {
            "dataset": self.name,
            "gridHash": self.mesh.grid_hash,
            "ncpl": self.mesh.ncpl,
            "nlay": self.mesh.nlay,
            "ncells": self.mesh.ncells,
            "nverts": int(self.mesh.vertices.shape[0]),
            "bounds": {
                "min": [xmin, ymin, zmin],
                "max": [xmax, ymax, zmax],
            },
            "times": self.times,
            "components": [
                {
                    "name": info.name,
                    "unit": info.unit,
                    "vmin": info.vmin,
                    "vmax": info.vmax,
                }
                for info in (self.component_info(name) for name in sorted(self.scalars))
            ],
        }

    def mesh_frames(self, req_id: int) -> list[bytes]:
        """Geometry, as the sequence of frames the viewport uploads once."""
        common: dict[str, Any] = {"reqId": req_id, "gridHash": self.mesh.grid_hash}
        return [
            encode("mesh_vertices", self.mesh.vertices, **common),
            encode("mesh_cell_offsets", self.mesh.cell_offsets, **common),
            encode("mesh_cell_indices", self.mesh.cell_indices, **common),
            encode("mesh_cell_centers", self.mesh.cell_centers, **common),
            # Top and bottom stacked so one frame carries what the extrusion
            # shader binds: (2, nlay, ncpl), index 0 = top, 1 = bottom.
            encode(
                "cell_elevations",
                np.stack([self.mesh.top, self.mesh.botm]),
                nlay=self.mesh.nlay,
                ncpl=self.mesh.ncpl,
                **common,
            ),
        ]

    def scalar_block_frame(
        self, req_id: int, component: str, *, max_bytes: int | None = None
    ) -> bytes:
        """Every timestep of one component in one frame, decimated if oversized."""
        values = self.require(component)
        stride = time_stride(values, max_bytes if max_bytes is not None else DEFAULT_MAX_BYTES)
        decimated = values[::stride]
        info = self.component_info(component)

        return encode(
            "scalar_block",
            decimated,
            reqId=req_id,
            gridHash=self.mesh.grid_hash,
            component=component,
            timeStride=stride,
            times=self.times[::stride],
            ntimes=int(decimated.shape[0]),
            vmin=info.vmin,
            vmax=info.vmax,
        )

    def scalar_frame(self, req_id: int, component: str, time_idx: int) -> bytes:
        """One timestep at full resolution."""
        values = self.require(component)
        if not 0 <= time_idx < values.shape[0]:
            raise IndexError(f"timeIdx {time_idx} outside 0..{values.shape[0] - 1}")
        info = self.component_info(component)

        return encode(
            "scalar",
            values[time_idx],
            reqId=req_id,
            gridHash=self.mesh.grid_hash,
            component=component,
            timeIdx=time_idx,
            time=self.times[time_idx],
            vmin=info.vmin,
            vmax=info.vmax,
        )


def time_stride(values: np.ndarray, max_bytes: int) -> int:
    """Smallest stride that brings ``values`` within ``max_bytes``.

    Returns 1 when the whole block fits, which is the normal case. A single
    timestep larger than the budget still yields 1: dropping every timestep
    would leave nothing to draw, so the caller gets an oversized block and the
    honest option of refusing it.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    ntimes = int(values.shape[0])
    if ntimes <= 1:
        return 1

    per_step = values.nbytes // ntimes
    affordable = max(1, max_bytes // max(per_step, 1))
    return max(1, -(-ntimes // affordable))  # ceil division


@lru_cache(maxsize=4)
def demo_dataset(ncpl: int = 20_000, nlay: int = 6, ntimes: int = 40) -> Dataset:
    """Build (and cache) the demo dataset.

    Cached because the viewport asks for the mesh and the scalars in separate
    requests and must get the same grid both times.
    """
    mesh = synthetic_disv(ncpl_target=ncpl, nlay=nlay)
    return Dataset(
        name="demo",
        mesh=mesh,
        times=[float(step) for step in range(ntimes)],
        scalars={"concentration": synthetic_scalars(mesh, ntimes=ntimes)},
    )
