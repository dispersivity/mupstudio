"""The MODFLOW-2005 flow model PHT3D transports through.

PHT3D is built on the MODFLOW-2005 and MT3DMS stack, so a project that runs on
MF6RTM cannot hand its flow solution over directly. The flow has to be solved
again by MODFLOW-2005, which then writes a flow-transport link file — the FTL —
that MT3DMS and PHT3D read cell face flows from.

The same compiled model feeds this and the MODFLOW 6 writer, so the two engines
solve the same problem rather than two models that merely look alike. What
differs is only what each version of MODFLOW can express, and where it cannot,
this says so rather than quietly approximating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mupstudio.compile.compiler import CompiledModel

log = logging.getLogger(__name__)

MODEL_NAME = "flow"
FTL_NAME = "mt3d_link.ftl"

# MODFLOW-2005 names its units by number rather than by word.
TIME_UNITS = {"seconds": 1, "minutes": 2, "hours": 3, "days": 4, "years": 5}
LENGTH_UNITS = {"feet": 1, "meters": 2, "centimeters": 3}

# The packages MODFLOW-2005 has that we compile to. A drain, river or general
# head boundary all exist here under the same names they have in MODFLOW 6.
BUILDERS = ("wel", "chd", "drn", "riv", "ghb", "rch")


class Pht3dFlowError(Exception):
    """The flow model cannot be expressed for MODFLOW-2005."""


@dataclass
class FlowTwin:
    """What was written, and what MODFLOW-2005 could not take with it."""

    workdir: Path
    name: str
    files: list[str]
    ftl: str = FTL_NAME
    warnings: list[str] = field(default_factory=list)


def write_flow(model: CompiledModel, workdir: Path) -> FlowTwin:
    """Write a MODFLOW-2005 model that produces an FTL for PHT3D."""
    import flopy

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    project = model.project
    grid = model.grid
    properties = model.properties
    warnings: list[str] = list(model.warnings)

    # The executable is resolved here only to keep FloPy quiet: this function
    # writes files and never runs anything, but FloPy warns at construction if
    # it cannot find the program. The runner supplies the real path later.
    from mupstudio.doctor import find_executable

    mf = flopy.modflow.Modflow(
        MODEL_NAME,
        model_ws=str(workdir),
        version="mf2005",
        exe_name=str(find_executable("mf2005") or "mf2005"),
    )

    periods = project.time.periods
    flopy.modflow.ModflowDis(
        mf,
        nlay=grid.nlay,
        nrow=grid.nrow,
        ncol=grid.ncol,
        delr=grid.delr,
        delc=grid.delc,
        top=grid.top,
        botm=grid.botm,
        nper=len(periods),
        perlen=[period.perlen for period in periods],
        nstp=[period.nstp for period in periods],
        tsmult=[period.tsmult for period in periods],
        steady=[period.steady for period in periods],
        itmuni=TIME_UNITS.get(project.meta.time_unit, 4),
        lenuni=LENGTH_UNITS.get(project.meta.length_unit, 2),
    )

    flopy.modflow.ModflowBas(mf, ibound=1, strt=properties["strt"])
    flopy.modflow.ModflowLpf(
        mf,
        hk=properties["k"],
        vka=properties["k33"],
        laytyp=_layer_types(project.flow.properties.icelltype, grid.nlay),
        ss=properties["ss"],
        sy=properties["sy"],
        ipakcb=53,
    )

    _write_boundaries(mf, model, warnings)

    solver = project.flow.solver
    flopy.modflow.ModflowPcg(
        mf,
        hclose=solver.outer_dvclose,
        rclose=solver.inner_dvclose,
        mxiter=solver.outer_maximum,
        iter1=solver.inner_maximum,
    )
    flopy.modflow.ModflowOc(
        mf,
        stress_period_data={
            (period, step.nstp - 1): ["save head", "save budget"]
            for period, step in enumerate(periods)
        },
    )

    # The point of the whole model: LMT writes the cell face flows that MT3DMS
    # and PHT3D transport through. Without it there is nothing to hand over.
    flopy.modflow.ModflowLmt(mf, output_file_name=FTL_NAME)

    mf.write_input()

    return FlowTwin(
        workdir=workdir,
        name=MODEL_NAME,
        files=sorted(path.name for path in workdir.iterdir() if path.is_file()),
        warnings=warnings,
    )


def _layer_types(icelltype: int, nlay: int) -> np.ndarray:
    """MODFLOW-2005 sets confinement per layer, not per cell.

    MODFLOW 6 allows a cell to be convertible while its neighbour is not.
    Nothing in the schema uses that yet — icelltype is one number for the whole
    model — so the collapse is exact rather than an approximation.
    """
    return np.full(nlay, 1 if icelltype != 0 else 0, dtype=int)


def _write_boundaries(mf: Any, model: CompiledModel, warnings: list[str]) -> None:
    """Every boundary, as MODFLOW-2005 spells it.

    MODFLOW-2005 has no per-package names, so two wells become one WEL package
    with both sets of cells. The identity of each is kept for the SSM writer,
    which still needs to know which cells carry which water.
    """
    import flopy

    combined: dict[str, dict[int, list[list[Any]]]] = {}
    recharge: dict[int, np.ndarray] = {}

    for boundary in model.boundaries:
        if boundary.kind == "recharge":
            _accumulate_recharge(boundary, model, recharge)
            continue

        package = {"well": "wel", "chd": "chd", "drn": "drn", "riv": "riv", "ghb": "ghb"}.get(
            boundary.kind
        )
        if package is None:
            warnings.append(
                f"boundary {boundary.id!r} of kind {boundary.kind!r} was not written for PHT3D"
            )
            continue

        target = combined.setdefault(package, {})
        for period, records in boundary.spd.items():
            rows = target.setdefault(period, [])
            for record in records:
                layer, row, column = record[0]
                # The trailing auxiliary concentration is dropped here: PHT3D
                # carries boundary chemistry in the SSM package instead, one
                # value per component rather than one for a single tracer.
                values = _values_for(package, record[1:])
                rows.append([layer, row, column, *values])

    builders = {
        "wel": flopy.modflow.ModflowWel,
        "chd": flopy.modflow.ModflowChd,
        "drn": flopy.modflow.ModflowDrn,
        "riv": flopy.modflow.ModflowRiv,
        "ghb": flopy.modflow.ModflowGhb,
    }
    for package, spd in combined.items():
        builders[package](mf, stress_period_data=spd, ipakcb=53)

    if recharge:
        flopy.modflow.ModflowRch(mf, rech=recharge, ipakcb=53)


def _values_for(package: str, values: tuple[Any, ...]) -> list[float]:
    """The numbers this package needs, from the compiled record.

    A constant head takes a start and an end value in MODFLOW-2005 where
    MODFLOW 6 takes one; within a stress period they are the same head, so the
    single value is written twice rather than interpolated.
    """
    numbers = [float(value) for value in values]
    if package == "chd":
        return [numbers[0], numbers[0]]
    return numbers[: _EXPECTED[package]]


_EXPECTED = {"wel": 1, "chd": 2, "drn": 2, "riv": 3, "ghb": 2}


def _accumulate_recharge(
    boundary: Any, model: CompiledModel, recharge: dict[int, np.ndarray]
) -> None:
    """Recharge as a rate per cell of the top layer.

    MODFLOW-2005's RCH package is an array over rows and columns, not a cell
    list, so the compiled records are painted onto that array.
    """
    grid = model.grid
    for period, records in boundary.spd.items():
        array = recharge.setdefault(period, np.zeros((grid.nrow, grid.ncol), dtype=np.float64))
        for record in records:
            _, row, column = record[0]
            # Divided by the cell's area: MODFLOW 6 takes a rate per unit area
            # already, and so does MODFLOW-2005, so this is a straight copy.
            array[row, column] = float(record[1])
