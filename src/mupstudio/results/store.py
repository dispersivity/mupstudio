"""The normalized form results take once a run is collected.

Engine output formats differ; what the viewport reads does not. Collecting a
run writes:

    results/
      catalog.json        what exists: components, times, ranges, mesh summary
      mesh.npz            the renderable grid
      scalars/<name>.npy  float32 (ntimes, nlay, ncpl), one file per component
      sout.parquet        selected output, when the run produced any

One file per component holding every timestep is what makes the viewport's
preload cheap: a whole component is one contiguous read, and a single timestep
is a slice of it. The files are memory-mapped, so serving a timestep never
loads the rest.

Collection is deliberately tolerant. A run that died at stress period 40 still
has 40 stress periods worth of output, and that is usually the most useful
thing to look at.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from mupstudio.grids.mesh import DisvMesh

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)

CATALOG_NAME = "catalog.json"
MESH_NAME = "mesh.npz"
SCALARS_DIR = "scalars"
SOUT_NAME = "sout.parquet"

# Concentrations are stored in whatever units the engine reported. Recording
# the unit rather than converting keeps collection lossless; conversion belongs
# where a user asks for it.
DEFAULT_UNIT = "mol/L"
# A conservative tracer has no chemistry behind it, so its concentration is in
# whatever the modeller meant when they typed the boundary value.
TRACER_UNIT = "concentration"


@dataclass
class Catalog:
    """What a collected run contains."""

    run_id: str
    engine: str
    status: str
    ncpl: int
    nlay: int
    ncells: int
    nverts: int
    grid_hash: str
    bounds: dict[str, list[float]]
    times: list[float]
    components: list[dict[str, object]] = field(default_factory=list)
    has_sout: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_path(cls, path: Path) -> Catalog:
        return cls(**json.loads(path.read_text()))


def write_mesh(directory: Path, mesh: DisvMesh) -> None:
    np.savez(
        directory / MESH_NAME,
        vertices=mesh.vertices,
        cell_offsets=mesh.cell_offsets,
        cell_indices=mesh.cell_indices,
        cell_centers=mesh.cell_centers,
        top=mesh.top,
        botm=mesh.botm,
    )


def read_mesh(directory: Path) -> DisvMesh:
    with np.load(directory / MESH_NAME) as data:
        return DisvMesh(
            vertices=data["vertices"],
            cell_offsets=data["cell_offsets"],
            cell_indices=data["cell_indices"],
            cell_centers=data["cell_centers"],
            top=data["top"],
            botm=data["botm"],
        )


class ResultsStore:
    """Read access to one collected run."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        catalog_path = self.directory / CATALOG_NAME
        if not catalog_path.exists():
            raise FileNotFoundError(f"no results catalog at {catalog_path}")
        self.catalog = Catalog.from_path(catalog_path)
        self._mesh: DisvMesh | None = None
        self._open: dict[str, np.ndarray] = {}

    @property
    def mesh(self) -> DisvMesh:
        if self._mesh is None:
            self._mesh = read_mesh(self.directory)
        return self._mesh

    @property
    def component_names(self) -> list[str]:
        return [str(entry["name"]) for entry in self.catalog.components]

    def scalars(self, component: str) -> np.ndarray:
        """Every timestep of one component, memory-mapped.

        Mapped rather than loaded: a large run's component file can be
        hundreds of megabytes and the caller usually wants one slice of it.
        """
        if component not in self._open:
            path = self.directory / SCALARS_DIR / f"{component}.npy"
            if not path.exists():
                known = ", ".join(self.component_names) or "none"
                raise KeyError(f"no component {component!r} in this run (have: {known})")
            self._open[component] = np.load(path, mmap_mode="r")
        return self._open[component]

    def timestep(self, component: str, index: int) -> np.ndarray:
        values = self.scalars(component)
        if not 0 <= index < values.shape[0]:
            raise IndexError(f"timeIdx {index} outside 0..{values.shape[0] - 1}")
        return np.ascontiguousarray(values[index])

    def sout(self) -> pd.DataFrame | None:
        import pandas as pd

        path = self.directory / SOUT_NAME
        return pd.read_parquet(path) if path.exists() else None


def collect_mf6rtm_run(
    workdir: Path,
    destination: Path,
    *,
    run_id: str,
    status: str = "succeeded",
) -> Catalog:
    """Read an mf6rtm working directory into the normalized store.

    Components that cannot be read are recorded as warnings rather than
    aborting the collection: one unreadable species should not cost you the
    other twenty.
    """
    from mupstudio.engines.mf6rtm import results as reader

    workdir = Path(workdir)
    destination = Path(destination)
    (destination / SCALARS_DIR).mkdir(parents=True, exist_ok=True)

    mesh = reader.read_mesh(workdir)
    write_mesh(destination, mesh)

    # A reactive run's concentrations arrive in mol/m3, which is what MODFLOW
    # transported; everything downstream, including the chemistry that produced
    # them, speaks mol/L. A conservative tracer carries whatever units the
    # modeller put in the boundary, so it is left alone and labelled as such.
    reactive = reader.is_reactive_run(workdir)
    scale = 1.0 / reader.LITRES_PER_CUBIC_METRE if reactive else 1.0
    unit = DEFAULT_UNIT if reactive else TRACER_UNIT

    warnings: list[str] = []
    components: list[dict[str, object]] = []
    times: list[float] = []

    for name in reader.discover_components(workdir):
        try:
            component_times, values = reader.read_component(workdir, name)
        except Exception as error:
            warnings.append(f"{name}: {error}")
            log.warning("could not read component %s: %s", name, error)
            continue

        if not times:
            times = component_times
        elif len(component_times) != len(times):
            # A run interrupted mid-write can leave components at different
            # lengths. Trim to the shortest so every component covers the same
            # time axis, and say so.
            shortest = min(len(times), len(component_times))
            warnings.append(
                f"{name} has {len(component_times)} timesteps against {len(times)}; "
                f"all components trimmed to {shortest}"
            )
            times = times[:shortest]

        if scale != 1.0:
            values = values * np.float32(scale)

        np.save(destination / SCALARS_DIR / f"{name}.npy", values)
        components.append(
            {
                "name": name,
                "unit": unit,
                "vmin": float(values.min()),
                "vmax": float(values.max()),
            }
        )

    if not components:
        raise reader.RunOutputError(f"no readable components in {workdir}")

    # Trim any component written before a shorter one was discovered.
    _trim_to_common_length(destination, [str(entry["name"]) for entry in components], len(times))

    sout = reader.read_sout(workdir)
    if sout is not None:
        try:
            sout.to_parquet(destination / SOUT_NAME, index=False)
        except ImportError as error:
            warnings.append(f"selected output not stored: {error}")

    xmin, ymin, zmin, xmax, ymax, zmax = mesh.bounds
    catalog = Catalog(
        run_id=run_id,
        engine="mf6rtm",
        status=status,
        ncpl=mesh.ncpl,
        nlay=mesh.nlay,
        ncells=mesh.ncells,
        nverts=int(mesh.vertices.shape[0]),
        grid_hash=mesh.grid_hash,
        bounds={"min": [xmin, ymin, zmin], "max": [xmax, ymax, zmax]},
        times=times,
        components=components,
        has_sout=(destination / SOUT_NAME).exists(),
        warnings=warnings,
    )
    (destination / CATALOG_NAME).write_text(catalog.to_json())
    return catalog


def _trim_to_common_length(destination: Path, names: list[str], ntimes: int) -> None:
    """Make every stored component span the same number of timesteps."""
    for name in names:
        path = destination / SCALARS_DIR / f"{name}.npy"
        values = np.load(path, mmap_mode="r")
        if values.shape[0] != ntimes:
            np.save(path, np.ascontiguousarray(values[:ntimes]))
