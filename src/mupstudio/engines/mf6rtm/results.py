"""Read what an mf6rtm run leaves behind.

A finished run is a directory of MODFLOW 6 output: a binary grid file, one UCN
per transported component, and (when the model defines a selected output) a
long-format ``sout`` table of the chemistry PHREEQC was asked to report.

Nothing here assumes the run succeeded. Reactive runs fail often enough —
non-convergence, a phase exhausting — that a reader which only handles complete
output is a reader you cannot use when you most need to look.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from mupstudio.grids.mesh import DisvMesh, csr_from_iverts

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)

# UCN files whose stem is one of these are not transported components.
NOT_COMPONENTS = frozenset({"gwf", "flow"})


class RunOutputError(Exception):
    """The directory does not hold readable run output."""


def discover_components(workdir: Path) -> list[str]:
    """Names of the transported components, from the UCN files present.

    mf6rtm writes one ``<Component>.ucn`` per PHREEQC component, so the file
    listing is the component list. Sorted for a stable order.
    """
    names = sorted(
        path.stem for path in workdir.glob("*.ucn") if path.stem.lower() not in NOT_COMPONENTS
    )
    return names


def find_grid_file(workdir: Path) -> Path:
    """Locate the binary grid file the flow model wrote."""
    candidates = sorted(workdir.glob("*.grb"))
    if not candidates:
        raise RunOutputError(
            f"no .grb grid file in {workdir}; the flow model must be run with "
            "BINARY_GRID enabled in its options"
        )
    return candidates[0]


def read_mesh(workdir: Path) -> DisvMesh:
    """Build the renderable mesh from the run's binary grid file.

    FloPy exposes the same vertex and cell-vertex view for DIS and DISV grids,
    so both arrive here as the same prismatic mesh and the renderer needs only
    one path.
    """
    import flopy

    grid_file = find_grid_file(workdir)
    with warnings.catch_warnings():
        # FloPy's grid reader still assigns to ndarray.shape, which numpy 2.5
        # deprecates. Not ours to fix and not worth surfacing on every read.
        warnings.simplefilter("ignore", DeprecationWarning)
        grid = flopy.mf6.utils.MfGrdFile(str(grid_file)).modelgrid

        vertices = np.asarray(grid.verts, dtype=np.float32)
        cell_offsets, cell_indices = csr_from_iverts(grid.iverts)

        centers = np.column_stack(
            [
                np.asarray(grid.xcellcenters, dtype=np.float32).ravel(),
                np.asarray(grid.ycellcenters, dtype=np.float32).ravel(),
            ]
        ).astype(np.float32)

        nlay = int(grid.nlay)
        ncpl = centers.shape[0]
        surface = np.asarray(grid.top, dtype=np.float32).ravel()
        botm = np.asarray(grid.botm, dtype=np.float32).reshape(nlay, ncpl)

    # A cell's top is the model top for layer 0 and the layer above's bottom
    # below that, which is how MODFLOW defines the vertical discretisation.
    top = np.empty((nlay, ncpl), dtype=np.float32)
    top[0] = surface
    if nlay > 1:
        top[1:] = botm[:-1]

    mesh = DisvMesh(
        vertices=vertices,
        cell_offsets=cell_offsets,
        cell_indices=cell_indices,
        cell_centers=centers,
        top=top,
        botm=botm,
    )
    mesh.validate()
    return mesh


def is_reactive_run(workdir: Path) -> bool:
    """Whether mf6rtm drove this run, rather than MODFLOW alone.

    mf6rtm writes its run configuration next to the model, and only ever for a
    reactive run. It matters because it changes what the concentrations mean:
    PHREEQC works in mol per litre and MODFLOW transports mass per cubic metre,
    so mf6rtm multiplies by a thousand on the way in.
    """
    return (Path(workdir) / "mf6rtm.toml").is_file()


# Litres in a cubic metre. mf6rtm transports in mol/m3 because that is what
# MODFLOW's mass balance wants with lengths in metres; chemistry is read and
# written in mol/L, so results are converted back on the way out.
LITRES_PER_CUBIC_METRE = 1000.0


def read_component(workdir: Path, component: str) -> tuple[list[float], np.ndarray]:
    """Read one component's concentrations as ``(ntimes, nlay, ncpl)`` float32.

    A run killed mid-write leaves a truncated final record; FloPy reports only
    the records it can read, so a partial run yields fewer times rather than an
    error.
    """
    import flopy

    path = workdir / f"{component}.ucn"
    if not path.exists():
        raise RunOutputError(f"no output for component {component!r} at {path}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ucn = flopy.utils.HeadFile(str(path), text="CONCENTRATION")
        times = [float(time) for time in ucn.get_times()]
        if not times:
            raise RunOutputError(f"{path} holds no complete timesteps")
        stack = np.stack([ucn.get_data(totim=time) for time in times])

    # UCN records are (nlay, nrow, ncol) for DIS and (nlay, 1, ncpl) for DISV;
    # both flatten to (ntimes, nlay, ncpl).
    values = stack.reshape(len(times), stack.shape[1], -1).astype(np.float32)
    return times, values


def read_heads(workdir: Path) -> tuple[list[float], np.ndarray] | None:
    """Read the flow solution if it was saved, else None."""
    import flopy

    candidates = sorted(workdir.glob("*.hds"))
    if not candidates:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        heads = flopy.utils.HeadFile(str(candidates[0]))
        times = [float(time) for time in heads.get_times()]
        if not times:
            return None
        stack = np.stack([heads.get_data(totim=time) for time in times])

    return times, stack.reshape(len(times), stack.shape[1], -1).astype(np.float32)


def read_sout(workdir: Path) -> pd.DataFrame | None:
    """Read the selected-output table, if the model wrote one.

    Columns beyond the spatial ones come from the model's USER_PUNCH block, so
    they cannot be known before the run.
    """
    import pandas as pd

    csv = workdir / "sout.csv"
    if csv.exists():
        try:
            return pd.read_csv(csv)
        except pd.errors.EmptyDataError:
            log.warning("%s is empty", csv)
            return None

    for name in ("sout.h5", "sout.hdf", "sout.hdf5"):
        store = workdir / name
        if store.exists():
            return pd.read_hdf(store, key="sout")

    return None


def looks_like_run_output(workdir: Path) -> bool:
    """Cheap check that a directory holds something worth reading."""
    return workdir.is_dir() and any(workdir.glob("*.grb")) and any(workdir.glob("*.ucn"))
