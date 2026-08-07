"""One interface over everything the viewport can draw.

The viewport does not care whether it is showing a synthetic grid or a
collected run: both are a mesh, a set of named components, and a time axis.
This module is where those two become the same thing, so the websocket and the
client stay unaware of the difference.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from mupstudio.grids.mesh import DisvMesh
from mupstudio.grids.synthetic import synthetic_disv, synthetic_scalars
from mupstudio.results.store import ResultsStore
from mupstudio.server.ws.frames import encode

# Time-decimation budget. Every timestep is preloaded into a GPU buffer so
# scrubbing is a buffer swap, which means a large field can exceed what the GPU
# will hold. Whole timesteps are then dropped at a fixed stride and the client
# is told the stride, rather than the run being silently truncated.
DEFAULT_MAX_BYTES = 1_500 * 1024 * 1024


class Dataset(Protocol):
    """What the websocket needs from anything drawable."""

    name: str
    mesh: DisvMesh
    times: list[float]

    def component_names(self) -> list[str]: ...
    def component_range(self, component: str) -> tuple[float, float]: ...
    def component_unit(self, component: str) -> str: ...
    def all_timesteps(self, component: str) -> np.ndarray: ...
    def timestep(self, component: str, index: int) -> np.ndarray: ...
    def describe(self) -> dict[str, Any]: ...


class SyntheticDataset:
    """A generated grid and plume, used to exercise the viewport at any scale."""

    def __init__(self, ncpl: int, nlay: int, ntimes: int):
        self.name = "demo"
        self.mesh = synthetic_disv(ncpl_target=ncpl, nlay=nlay)
        self.times = [float(step) for step in range(ntimes)]
        self._values = synthetic_scalars(self.mesh, ntimes=ntimes)

    def component_names(self) -> list[str]:
        return ["concentration"]

    def component_unit(self, component: str) -> str:
        self._require(component)
        return "mol/L"

    def component_range(self, component: str) -> tuple[float, float]:
        self._require(component)
        return float(self._values.min()), float(self._values.max())

    def all_timesteps(self, component: str) -> np.ndarray:
        self._require(component)
        return np.asarray(self._values)

    def timestep(self, component: str, index: int) -> np.ndarray:
        self._require(component)
        if not 0 <= index < self._values.shape[0]:
            raise IndexError(f"timeIdx {index} outside 0..{self._values.shape[0] - 1}")
        return np.asarray(self._values[index])

    def describe(self) -> dict[str, Any]:
        return {"kind": "synthetic", "status": "demo"}

    def _require(self, component: str) -> None:
        if component != "concentration":
            raise KeyError(f"no component {component!r} in the demo dataset (have: concentration)")


class RunDataset:
    """A collected run on disk."""

    def __init__(self, store: ResultsStore):
        self._store = store
        self.name = store.catalog.run_id
        self.mesh = store.mesh
        self.times = list(store.catalog.times)

    def component_names(self) -> list[str]:
        return self._store.component_names

    def component_unit(self, component: str) -> str:
        return str(self._entry(component).get("unit", "mol/L"))

    def component_range(self, component: str) -> tuple[float, float]:
        entry = self._entry(component)
        return float(entry["vmin"]), float(entry["vmax"])

    def all_timesteps(self, component: str) -> np.ndarray:
        return np.asarray(self._store.scalars(component))

    def timestep(self, component: str, index: int) -> np.ndarray:
        return self._store.timestep(component, index)

    def describe(self) -> dict[str, Any]:
        catalog = self._store.catalog
        return {
            "kind": "run",
            "status": catalog.status,
            "engine": catalog.engine,
            "warnings": catalog.warnings,
            "hasSout": catalog.has_sout,
        }

    def _entry(self, component: str) -> dict[str, Any]:
        for entry in self._store.catalog.components:
            if entry["name"] == component:
                return dict(entry)
        known = ", ".join(self.component_names()) or "none"
        raise KeyError(f"no component {component!r} in {self.name} (have: {known})")


def catalog_of(dataset: Dataset) -> dict[str, Any]:
    """The metadata a client needs before requesting any arrays."""
    mesh = dataset.mesh
    xmin, ymin, zmin, xmax, ymax, zmax = mesh.bounds

    return {
        "dataset": dataset.name,
        "gridHash": mesh.grid_hash,
        "ncpl": mesh.ncpl,
        "nlay": mesh.nlay,
        "ncells": mesh.ncells,
        "nverts": int(mesh.vertices.shape[0]),
        "bounds": {"min": [xmin, ymin, zmin], "max": [xmax, ymax, zmax]},
        # Present when the grid is one cell across: the client offers to squash
        # that axis so a 1D or 2D profile does not render as a slab.
        "thinAxis": mesh.thin_axis,
        "times": dataset.times,
        "components": [
            {
                "name": name,
                "unit": dataset.component_unit(name),
                "vmin": low,
                "vmax": high,
            }
            for name, (low, high) in (
                (name, dataset.component_range(name)) for name in dataset.component_names()
            )
        ],
        **dataset.describe(),
    }


def mesh_frames(dataset: Dataset, req_id: int) -> list[bytes]:
    """Geometry, as the frames the viewport uploads once."""
    mesh = dataset.mesh
    common: dict[str, Any] = {"reqId": req_id, "gridHash": mesh.grid_hash}
    return [
        encode("mesh_vertices", mesh.vertices, **common),
        encode("mesh_cell_offsets", mesh.cell_offsets, **common),
        encode("mesh_cell_indices", mesh.cell_indices, **common),
        encode("mesh_cell_centers", mesh.cell_centers, **common),
        # Top and bottom stacked into what the extrusion shader binds:
        # (2, nlay, ncpl), index 0 = top, 1 = bottom.
        encode(
            "cell_elevations",
            np.stack([mesh.top, mesh.botm]),
            nlay=mesh.nlay,
            ncpl=mesh.ncpl,
            **common,
        ),
    ]


def scalar_block_frame(
    dataset: Dataset, req_id: int, component: str, *, max_bytes: int | None = None
) -> bytes:
    """Every timestep of one component, decimated if it will not fit."""
    values = dataset.all_timesteps(component)
    stride = time_stride(values, max_bytes if max_bytes is not None else DEFAULT_MAX_BYTES)
    decimated = np.ascontiguousarray(values[::stride])
    low, high = dataset.component_range(component)

    return encode(
        "scalar_block",
        decimated,
        reqId=req_id,
        gridHash=dataset.mesh.grid_hash,
        component=component,
        timeStride=stride,
        times=dataset.times[::stride],
        ntimes=int(decimated.shape[0]),
        vmin=low,
        vmax=high,
    )


def scalar_frame(dataset: Dataset, req_id: int, component: str, time_idx: int) -> bytes:
    """One timestep at full resolution."""
    values = dataset.timestep(component, time_idx)
    low, high = dataset.component_range(component)

    return encode(
        "scalar",
        np.ascontiguousarray(values),
        reqId=req_id,
        gridHash=dataset.mesh.grid_hash,
        component=component,
        timeIdx=time_idx,
        time=dataset.times[time_idx] if time_idx < len(dataset.times) else float(time_idx),
        vmin=low,
        vmax=high,
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
def demo_dataset(ncpl: int = 20_000, nlay: int = 6, ntimes: int = 40) -> SyntheticDataset:
    """Build and cache the demo dataset.

    Cached because the viewport asks for the mesh and the scalars in separate
    requests and must get the same grid both times.
    """
    return SyntheticDataset(ncpl, nlay, ntimes)


def open_run(directory: Path) -> RunDataset:
    return RunDataset(ResultsStore(directory))
