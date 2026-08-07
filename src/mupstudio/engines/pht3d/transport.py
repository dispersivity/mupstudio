"""The MT3DMS packages PHT3D transports with.

PHT3D is MT3DMS with a reaction step, so its transport input is MT3DMS input:
BTN for the discretisation and initial concentrations, ADV, DSP and GCG for the
solution scheme. FloPy writes those.

The exception is SSM. MT3DMS gives a source one concentration per component,
and FloPy's writer expects the single-species form. PHT3D needs the full list
on every record — a well injecting water carries a value for calcium, for
chloride, for pH and for every mineral, in the component order — so that file
is written here directly.

Every concentration is floored rather than left at zero. PHREEQC works in log
activity, and a component at exactly zero is a logarithm of nothing; the
published decks use 1e-18 and so does this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from mupstudio.compile.compiler import CompiledModel
from mupstudio.engines.pht3d.ordering import Component, Group, mobile_count

log = logging.getLogger(__name__)

MODEL_NAME = "trans"

# The smallest concentration PHT3D is given. Zero is not a value PHREEQC can
# take the logarithm of, and the published decks all use this floor.
TRACE = 1e-18

# MT3DMS names each kind of source by a number, and SSM needs the right one per
# cell: it decides whether the record sets a concentration or adds mass.
ITYPE = {"chd": 1, "well": 2, "drn": 3, "riv": 4, "ghb": 5, "recharge": 2}

# Which flow packages SSM's header flags refer to, in the order it reads them.
SSM_FLAGS = ("well", "drn", "recharge", "evt", "riv", "ghb")


class Pht3dTransportError(Exception):
    """The transport model cannot be written for PHT3D."""


@dataclass
class TransportDeck:
    """What was written, and what it holds."""

    workdir: Path
    name: str
    files: list[str]
    components: list[Component]
    warnings: list[str] = field(default_factory=list)

    @property
    def ncomp(self) -> int:
        return len(self.components)

    @property
    def mcomp(self) -> int:
        return mobile_count(self.components)


def write_transport(
    model: CompiledModel,
    workdir: Path,
    components: list[Component],
    initial: dict[str, np.ndarray],
    boundary: dict[str, dict[str, float]],
    *,
    ftl: str,
) -> TransportDeck:
    """Write BTN, ADV, DSP, GCG and SSM.

    ``initial`` gives each component's starting concentration as an array over
    the grid, and ``boundary`` gives the concentration each flow package
    injects, keyed by package id then component name. Both come from
    equilibrating the chemistry, which is why they are passed in rather than
    derived here.
    """
    import flopy

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    project = model.project
    grid = model.grid
    properties = model.properties
    warnings: list[str] = []

    from mupstudio.doctor import find_executable

    mt = flopy.mt3d.Mt3dms(
        modelname=MODEL_NAME,
        model_ws=str(workdir),
        version="mt3dms",
        exe_name=str(find_executable("pht3d") or "pht3d"),
        ftlfilename=ftl,
    )

    periods = project.time.periods
    flopy.mt3d.Mt3dBtn(
        mt,
        nlay=grid.nlay,
        nrow=grid.nrow,
        ncol=grid.ncol,
        nper=len(periods),
        ncomp=len(components),
        mcomp=mobile_count(components),
        # PHT3D reads species names from pht3d_ph.dat, but writing them here as
        # well is what makes the BTN readable by a person checking the deck.
        species_names=[component.name for component in components],
        delr=grid.delr,
        delc=grid.delc,
        htop=grid.top,
        dz=_layer_thicknesses(grid),
        prsity=properties["transport_porosity"],
        icbund=1,
        # FloPy takes the first component's initial concentration as ``sconc``
        # and every later one as ``sconc2``, ``sconc3`` and so on, rather than
        # as a list.
        **_initial_concentrations(components, initial),
        perlen=[period.perlen for period in periods],
        nstp=[period.nstp for period in periods],
        tsmult=[period.tsmult for period in periods],
        # One transport step per flow step: the reaction is applied between
        # them, so a longer transport step would react less often than the
        # flow changes.
        dt0=[period.perlen / period.nstp for period in periods],
        nprs=0,
        laycon=project.flow.properties.icelltype,
    )

    scheme = project.transport.advection_scheme.lower()
    flopy.mt3d.Mt3dAdv(mt, mixelm=_mixelm(scheme, warnings), percel=0.75, nadvfd=1)

    if project.transport.dispersion.enabled:
        flopy.mt3d.Mt3dDsp(
            mt,
            al=properties["alh"],
            # MT3DMS takes the transverse dispersivities as ratios to the
            # longitudinal one, where MODFLOW 6 takes them as lengths; and it
            # takes one value per layer where MODFLOW 6 takes one per cell.
            trpt=_per_layer(
                _ratio(properties["ath1"], properties["alh"]),
                "the horizontal transverse dispersivity ratio",
                warnings,
            ),
            trpv=_per_layer(
                _ratio(properties["atv"], properties["alh"]),
                "the vertical transverse dispersivity ratio",
                warnings,
            ),
            # The diffusion coefficient is read as a column of one value per
            # layer rather than as a flat list, unlike the ratios above.
            dmcoef=_per_layer(properties["diffc"], "the diffusion coefficient", warnings).reshape(
                -1, 1
            ),
        )

    flopy.mt3d.Mt3dGcg(mt, mxiter=1, iter1=40, isolve=2, cclose=1e-11)

    mt.write_input()

    # Written last and by hand: FloPy's SSM cannot carry a concentration per
    # component, which is the whole of what PHT3D needs from this file.
    write_ssm(workdir / f"{MODEL_NAME}.ssm", model, components, boundary)

    return TransportDeck(
        workdir=workdir,
        name=MODEL_NAME,
        files=sorted(path.name for path in workdir.iterdir() if path.is_file()),
        components=components,
        warnings=warnings,
    )


def _initial_concentrations(
    components: list[Component], initial: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    """Starting concentrations, named the way FloPy's BTN expects them.

    A component missing from ``initial`` is an equilibration that did not
    produce it, which means the component list and the chemistry disagree —
    worth failing on rather than starting the model at the trace floor and
    letting it look like a legitimate near-zero.
    """
    missing = [component.name for component in components if component.name not in initial]
    if missing:
        raise Pht3dTransportError(
            f"no initial concentration for {', '.join(missing)}; the chemistry and the "
            "component list disagree"
        )

    return {
        ("sconc" if index == 0 else f"sconc{index + 1}"): _floor(initial[component.name])
        for index, component in enumerate(components)
    }


def _layer_thicknesses(grid: Any) -> np.ndarray:
    """Each layer's thickness, which is what BTN takes instead of bottoms."""
    tops = np.concatenate([grid.top[None, :, :], grid.botm[:-1]])
    return np.asarray(tops - grid.botm, dtype=np.float64)


def _floor(values: np.ndarray) -> np.ndarray:
    """No concentration below the trace floor.

    Zero is a legal number and an illegal concentration: PHREEQC takes its
    logarithm. Clipping rather than rejecting, because zero is what a modeller
    naturally types for "none of this here".
    """
    return np.maximum(np.asarray(values, dtype=np.float64), TRACE)


def _mixelm(scheme: str, warnings: list[str]) -> int:
    """MT3DMS's advection scheme number.

    MODFLOW 6 offers upstream, central and TVD. MT3DMS numbers TVD -1 and pure
    finite difference 0; there is no central-in-space option, so a project
    asking for it is told what it got instead.
    """
    if scheme == "tvd":
        return -1
    if scheme == "upstream":
        return 0
    warnings.append(
        f"MT3DMS has no {scheme} advection scheme; the model was written with "
        "TVD, which is the closest it offers"
    )
    return -1


def _ratio(part: np.ndarray, whole: np.ndarray) -> np.ndarray:
    """Transverse dispersivity as a fraction of the longitudinal one.

    Where the longitudinal dispersivity is zero the ratio is undefined, and
    MT3DMS multiplies it by zero anyway, so it is reported as zero rather than
    as a division warning.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(whole > 0, part / np.where(whole > 0, whole, 1.0), 0.0)
    return np.asarray(ratio, dtype=np.float64)


def _per_layer(values: np.ndarray, what: str, warnings: list[str]) -> np.ndarray:
    """One value per layer, which is all MT3DMS will read.

    MODFLOW 6 allows these to vary cell by cell. Where a layer is not uniform
    the mean is used and the loss is reported, because silently taking the
    first cell's value would make a zoned model run as an unzoned one.
    """
    layers = np.asarray(values, dtype=np.float64).reshape(values.shape[0], -1)
    spread = layers.max(axis=1) - layers.min(axis=1)
    if np.any(spread > 0):
        warnings.append(
            f"MT3DMS takes {what} once per layer, but it varies within "
            f"{int(np.count_nonzero(spread))} of them; the layer mean was written"
        )
    return np.asarray(layers.mean(axis=1), dtype=np.float64)


def write_ssm(
    path: Path,
    model: CompiledModel,
    components: list[Component],
    boundary: dict[str, dict[str, float]],
) -> None:
    """The source and sink mixing package, with a concentration per component.

    This is the file FloPy cannot write. Each record names a cell, the kind of
    source it is, and then one concentration for every component in PHT3D's
    order — including the immobile ones, which are given as zero because a
    boundary cannot inject a mineral.

    A package with no chemistry assigned injects the trace floor rather than
    nothing, which is how PHT3D reads "water with none of this in it".
    """
    boundaries = [item for item in model.boundaries if item.kind in ITYPE]
    nper = model.project.time.nper

    per_period: list[list[str]] = []
    for period in range(nper):
        records: list[str] = []
        for item in boundaries:
            values = _concentrations(boundary.get(item.id, {}), components)
            for record in item.spd.get(period, []):
                layer, row, column = record[0]
                records.append(
                    _ssm_record(layer + 1, row + 1, column + 1, ITYPE[item.kind], values)
                )
        per_period.append(records)

    flags = " ".join(
        "T" if any(item.kind == kind for item in boundaries) else "F" for kind in SSM_FLAGS
    )
    # MXSS is the most records any one period holds. MT3DMS allocates from it,
    # so it has to cover the worst period rather than the first.
    mxss = max((len(records) for records in per_period), default=0)

    lines = [f" {flags}", f"{mxss:>10d}"]
    for records in per_period:
        lines.append(f"{len(records):>10d}")
        lines.extend(records)

    path.write_text("\n".join(lines) + "\n")


def _concentrations(assigned: dict[str, float], components: list[Component]) -> list[float]:
    """One value per component, in order.

    The split is by block, not by mobility. Everything in the aqueous block is
    a property of the water arriving, so it is written — and that includes pH
    and pe, which PHT3D does not transport but does need in order to speciate
    the inflow. A mineral or an exchanger is not something water can carry, so
    it is written as zero; the published decks show exactly this, with the
    inflow's pH and pe alongside zeros for calcite and dolomite.
    """
    return [
        max(float(assigned.get(component.name, 0.0)), TRACE)
        if component.group is Group.AQUEOUS
        else 0.0
        for component in components
    ]


def _ssm_record(layer: int, row: int, column: int, itype: int, values: list[float]) -> str:
    """One SSM line.

    The single CSS field before ITYPE is ignored once the per-component list is
    given, but MT3DMS still reads it, so the first component's value goes there
    rather than a placeholder that would confuse anyone reading the file.
    """
    head = f"{layer:>9d}{row:>10d}{column:>10d}{values[0]:>10.5g}{itype:>10d}"
    tail = "".join(f" {value:.5e}" for value in values)
    return f"{head}{tail}"
