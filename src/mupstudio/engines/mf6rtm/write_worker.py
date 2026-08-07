"""Attaching chemistry to a written MODFLOW 6 simulation, in its own process.

Run as ``python -m mupstudio.engines.mf6rtm.write_worker spec.json``.

This is a separate process on purpose, and the reason is not tidiness:

* PhreeqcRM is a SWIG wrapper over global C++ state. Two models in one
  interpreter share it, and the second one silently gets the first one's
  chemistry.
* mf6rtm calls ``os.chdir`` while it writes and runs. A server that did that
  would break every other request in flight.
* Equilibration is where a bad database or an impossible solution shows up, and
  a crash there should cost a subprocess rather than the application.

The contract is JSON in, JSON out. Everything the parent needs — the component
list, the files written, any PHREEQC complaint — comes back on stdout as a
single object on the last line, so log noise before it does no harm.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

RESULT_MARKER = "MUPSTUDIO_RESULT"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} spec.json", file=sys.stderr)
        return 2

    spec = json.loads(Path(argv[1]).read_text())

    try:
        result = attach_chemistry(spec)
    except Exception as error:
        result = {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }

    # On its own line and marked, because mf6rtm and PhreeqcRM both print
    # freely and the parent has to find this among it.
    print(f"{RESULT_MARKER} {json.dumps(result)}")
    return 0 if result.get("ok") else 1


def attach_chemistry(spec: dict[str, Any]) -> dict[str, Any]:
    """Build the reactive model and write it, returning what came out.

    The simulation is loaded from disk rather than rebuilt: the flow and tracer
    transport models were already written by the non-reactive path, and reading
    them back means the reactive run is demonstrably the same model with
    chemistry added.
    """
    import flopy
    from mf6rtm import mup3d

    workdir = Path(spec["workdir"])
    chemistry = spec["chemistry"]

    simulation = flopy.mf6.MFSimulation.load(sim_ws=str(workdir), verbosity_level=0, load_only=None)

    solutions = mup3d.Solutions(_floats(chemistry["solutions"]["data"]))
    solutions.set_ic(_conditions(chemistry["solutions"]["ic"], spec["shape"]))

    model = mup3d.Mup3d.from_mf6(  # type: ignore[no-untyped-call]
        simulation,
        solutions,
        name=_safe_name(chemistry["name"]),
        gwf_name=spec["flowName"],
        gwt_name=spec["transportName"],
    )
    model.set_wd(str(workdir))
    model.set_database(str(_stage_database(chemistry, workdir)))
    model.set_initial_temp(chemistry["temperature"])

    _attach_blocks(mup3d, model, chemistry, spec["shape"])

    postfix = _write_postfix(chemistry, workdir)
    if postfix is not None:
        model.set_postfix(str(postfix))

    # Equilibration. Until this runs there is no component list, and so no way
    # to know how many transport models the simulation will have. It also has to
    # come before the boundary chemistry: assigning a solution to a boundary
    # runs the generated PHREEQC input, which does not exist until now.
    model.initialize()
    _attach_boundaries(mup3d, model, chemistry)
    model.write_simulation()

    components = [str(name) for name in getattr(model, "components", [])]
    return {
        "ok": True,
        "components": components,
        "componentCount": len(components),
        "files": sorted(path.name for path in workdir.iterdir() if path.is_file()),
        "workdir": str(workdir),
    }


def _attach_blocks(mup3d: Any, model: Any, chemistry: dict[str, Any], shape: list[int]) -> None:
    """Every optional PHREEQC block the project defines."""
    if "equilibriumPhases" in chemistry:
        block = mup3d.EquilibriumPhases(_numbered(chemistry["equilibriumPhases"]["data"]))
        block.set_ic(_conditions(chemistry["equilibriumPhases"]["ic"], shape))
        model.set_equilibrium_phases(block)

    if "exchange" in chemistry:
        spec = chemistry["exchange"]
        block = mup3d.ExchangePhases(_numbered(spec["data"]))
        block.set_ic(_conditions(spec["ic"], shape))
        if any(spec["equilibrateSolutions"]):
            block.set_equilibrate_solutions(spec["equilibrateSolutions"])
        model.set_exchange_phases(block)

    if "surface" in chemistry:
        spec = chemistry["surface"]
        block = mup3d.Surfaces(_numbered(spec["data"]))
        block.set_ic(_conditions(spec["ic"], shape))
        if spec["options"]:
            block.set_options(spec["options"])
        model.set_phases(block)

    if "kinetics" in chemistry:
        spec = chemistry["kinetics"]
        block = mup3d.KineticPhases(_numbered(spec["data"]))
        block.set_ic(_conditions(spec["ic"], shape))
        model.set_phases(block)

    if "gasPhase" in chemistry:
        spec = chemistry["gasPhase"]
        block = mup3d.GasPhase(_numbered(spec["data"]))
        block.set_ic(_conditions(spec["ic"], shape))
        model.set_phases(block)


def _attach_boundaries(mup3d: Any, model: Any, chemistry: dict[str, Any]) -> None:
    """Which solution each flow boundary injects.

    ``aux`` routes the chemistry through the auxiliary variable already declared
    on the flow package, which is why the non-reactive writer declares it even
    for a tracer run.
    """
    for package_id, solution_numbers in chemistry["boundaries"].items():
        if not solution_numbers:
            continue
        stress = mup3d.ChemStress(package_id, type="aux")
        stress.set_spd(solution_numbers)
        model.set_chem_stress(stress)


def _write_postfix(chemistry: dict[str, Any], workdir: Path) -> Path | None:
    """The SELECTED_OUTPUT block, as a file mf6rtm appends to its input."""
    lines = chemistry.get("postfix") or []
    if not lines:
        return None
    path = workdir / "postfix.phqr"
    path.write_text("\n".join(lines) + "\n")
    return path


def _stage_database(chemistry: dict[str, Any], workdir: Path) -> Path:
    """Where to read the database from.

    mf6rtm copies it next to the model itself, and refuses to copy a file over
    itself, so re-writing into a directory that already holds the database has
    to hand it a different source. Copying to a scratch name is enough, and it
    keeps a rewrite working the same as a first write.
    """
    import shutil
    import tempfile

    from mupstudio.chemdb import cache

    source = (
        Path(chemistry["databasePath"])
        if chemistry.get("databasePath")
        else _find_database(cache, chemistry["database"])
    )
    if source.parent.resolve() != workdir.resolve():
        return source

    scratch = Path(tempfile.mkdtemp(prefix="mupstudio-db-")) / source.name
    shutil.copyfile(source, scratch)
    return scratch


def _find_database(cache: Any, name: str) -> Path:
    if not name.endswith(".dat"):
        name = f"{name}.dat"
    for path in cache.available():
        if path.name == name:
            return Path(path)
    known = ", ".join(sorted(path.name for path in cache.available())) or "none"
    raise FileNotFoundError(f"no database named {name!r}; found: {known}")


def _conditions(values: Any, shape: list[int]) -> Any:
    """Per-cell assemblage numbers, as a single value or an array."""
    if isinstance(values, int):
        return values

    import numpy as np

    return np.asarray(values, dtype=float).reshape(shape)


def _numbered(data: dict[str, Any]) -> dict[int, Any]:
    """JSON object keys back to the ints mf6rtm indexes blocks by."""
    return {int(key): value for key, value in data.items()}


def _floats(data: dict[str, Any]) -> dict[str, list[float]]:
    return {key: [float(value) for value in values] for key, values in data.items()}


def _safe_name(name: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in name.lower())
    return cleaned.strip("_")[:16] or "model"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
