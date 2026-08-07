"""Reading what a PHT3D run leaves behind.

PHT3D writes one ``PHT3D00n.UCN`` per component, numbered rather than named.
Nothing inside the file says what it holds, so the only way to know that
``PHT3D007.UCN`` is calcite is to have written the deck — which is why the
component order is a single constant and why a run's component list is recorded
beside its output.

There is also ``PHT3D001.ACN`` and the selected output PHREEQC writes, both read
the same way MT3DMS output always is.
"""

from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from mupstudio.engines.pht3d.ordering import Component

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)

# The line PHT3D prints per transport step. Scraping it is the only progress
# signal there is: PHT3D has no callback and writes nothing structured.
PROGRESS = re.compile(
    r"STRESS PERIOD\s+NO\.\s*(?P<kper>\d+).*?TIME STEP\s+NO\.\s*(?P<kstp>\d+)",
    re.IGNORECASE | re.DOTALL,
)

UCN_PATTERN = re.compile(r"^PHT3D(\d{3})\.UCN$", re.IGNORECASE)


class Pht3dOutputError(Exception):
    """The directory does not hold readable PHT3D output."""


def discover_output(workdir: Path) -> dict[int, Path]:
    """Every component output file, keyed by the number PHT3D gave it."""
    found: dict[int, Path] = {}
    for path in sorted(Path(workdir).iterdir()):
        match = UCN_PATTERN.match(path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def read_component(workdir: Path, component: Component) -> tuple[list[float], np.ndarray]:
    """One component's values through time, as ``(ntimes, nlay, ncpl)``.

    Found by number, not by name. If the deck that produced this output was
    written with a different component order, this returns the wrong quantity
    with no sign of trouble — which is the whole reason the order lives in one
    place and is tested against a published deck.
    """
    import flopy

    path = Path(workdir) / component.ucn_file
    if not path.exists():
        available = ", ".join(sorted(item.name for item in discover_output(workdir).values()))
        raise Pht3dOutputError(
            f"no output for {component.name} at {path.name}; this run wrote: {available or 'none'}"
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ucn = flopy.utils.UcnFile(str(path))
        times = [float(time) for time in ucn.get_times()]
        if not times:
            raise Pht3dOutputError(f"{path.name} holds no complete timesteps")
        stack = np.stack([ucn.get_data(totim=time) for time in times])

    values = stack.reshape(len(times), stack.shape[1], -1).astype(np.float32)
    return times, values


def read_all(workdir: Path, components: list[Component]) -> dict[str, np.ndarray]:
    """Every component that was written, named.

    A component the run did not get to is skipped rather than failing: a model
    that died partway still wrote the ones it reached, and those are usually
    what tells you why it died.
    """
    values: dict[str, np.ndarray] = {}
    for component in components:
        try:
            _, array = read_component(workdir, component)
        except Pht3dOutputError as error:
            log.warning("%s", error)
            continue
        values[component.name] = array
    return values


def read_selected_output(workdir: Path) -> pd.DataFrame | None:
    """The table PHREEQC's SELECTED_OUTPUT block produced, if there is one."""
    import pandas as pd

    for name in ("out.dat", "selected.out", "phout.dat"):
        path = Path(workdir) / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        try:
            # Whitespace separated with a heading line, which is what PHREEQC
            # writes unless the deck asked for something else.
            return pd.read_csv(path, sep=r"\s+", engine="python")
        except Exception as error:
            log.warning("could not read %s: %s", path.name, error)
    return None


def looks_like_run_output(workdir: Path) -> bool:
    return Path(workdir).is_dir() and bool(discover_output(workdir))


def parse_progress(line: str) -> tuple[int, int] | None:
    """The stress period and time step a log line reports, if it reports one."""
    match = PROGRESS.search(line)
    if match is None:
        return None
    return int(match.group("kper")), int(match.group("kstp"))
