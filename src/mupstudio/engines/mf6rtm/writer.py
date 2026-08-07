"""Writing MODFLOW 6 input from a compiled model.

What this produces is a flow model plus one conservative transport model. That
is deliberately short of a reactive run: mf6rtm clones the transport model once
per PHREEQC component, and the component list only exists after the chemistry
has been equilibrated. So this writes the model that chemistry will later be
attached to, and which already runs on its own as a tracer simulation.

The binary grid file is always requested, because that is what the results
reader builds the renderable mesh from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from mupstudio.compile.compiler import CompiledModel

log = logging.getLogger(__name__)

FLOW_NAME = "gwf"
TRANSPORT_NAME = "trans"
# The tracer's name in a conservative run. mf6rtm renames per component.
TRACER = "tracer"


@dataclass
class WriteManifest:
    """What was written, and anything the user should know about it."""

    workdir: Path
    files: list[str]
    flow_name: str
    transport_name: str
    warnings: list[str]

    @property
    def file_count(self) -> int:
        return len(self.files)


def write_mf6(model: CompiledModel, workdir: Path) -> WriteManifest:
    """Write a runnable MODFLOW 6 simulation.

    Returns the manifest rather than the FloPy objects: nothing downstream
    should hold a live FloPy simulation, since the run happens in a subprocess.
    """
    import flopy

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    project = model.project
    warnings = list(model.warnings)

    simulation = flopy.mf6.MFSimulation(
        sim_name=_safe_name(project.meta.name),
        sim_ws=str(workdir),
        exe_name="mf6",
        version="mf6",
    )

    flopy.mf6.ModflowTdis(
        simulation,
        time_units=project.meta.time_unit.upper(),
        nper=project.time.nper,
        perioddata=[(period.perlen, period.nstp, period.tsmult) for period in project.time.periods],
    )

    gwf = _write_flow(simulation, model, warnings)
    gwt = _write_transport(simulation, model, gwf)

    flopy.mf6.ModflowGwfgwt(
        simulation,
        exgtype="GWF6-GWT6",
        exgmnamea=gwf.name,
        exgmnameb=gwt.name,
        filename=f"{_safe_name(project.meta.name)}.gwfgwt",
    )

    simulation.write_simulation(silent=True)

    files = sorted(path.name for path in workdir.iterdir() if path.is_file())
    return WriteManifest(
        workdir=workdir,
        files=files,
        flow_name=gwf.name,
        transport_name=gwt.name,
        warnings=warnings,
    )


def _write_flow(simulation, model: CompiledModel, warnings: list[str]):  # type: ignore[no-untyped-def]
    import flopy

    project = model.project
    grid = model.grid
    properties = model.properties

    gwf = flopy.mf6.ModflowGwf(
        simulation,
        modelname=FLOW_NAME,
        save_flows=True,
        newtonoptions="NEWTON" if project.flow.properties.icelltype != 0 else None,
    )

    flopy.mf6.ModflowIms(
        simulation,
        complexity=project.flow.solver.complexity.upper(),
        outer_maximum=project.flow.solver.outer_maximum,
        inner_maximum=project.flow.solver.inner_maximum,
        outer_dvclose=project.flow.solver.outer_dvclose,
        inner_dvclose=project.flow.solver.inner_dvclose,
        filename=f"{FLOW_NAME}.ims",
    )
    simulation.register_ims_package(simulation.get_package(f"{FLOW_NAME}.ims"), [gwf.name])

    flopy.mf6.ModflowGwfdis(
        gwf,
        length_units=project.meta.length_unit.upper(),
        nlay=grid.nlay,
        nrow=grid.nrow,
        ncol=grid.ncol,
        delr=grid.delr,
        delc=grid.delc,
        top=grid.top,
        botm=grid.botm,
        xorigin=grid.origin_x,
        yorigin=grid.origin_y,
        angrot=grid.rotation,
    )

    flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=project.flow.properties.icelltype,
        k=properties["k"],
        k33=properties["k33"],
        save_specific_discharge=True,
        save_saturation=True,
    )
    flopy.mf6.ModflowGwfic(gwf, strt=properties["strt"])

    if any(not period.steady for period in project.time.periods):
        flopy.mf6.ModflowGwfsto(
            gwf,
            iconvert=project.flow.properties.icelltype,
            ss=properties["ss"],
            sy=properties["sy"],
            steady_state={
                index: period.steady for index, period in enumerate(project.time.periods)
            },
            transient={
                index: not period.steady for index, period in enumerate(project.time.periods)
            },
        )

    _write_boundaries(gwf, model, warnings)

    flopy.mf6.ModflowGwfoc(
        gwf,
        head_filerecord=f"{FLOW_NAME}.hds",
        budget_filerecord=f"{FLOW_NAME}.cbb",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")],
    )
    return gwf


def _write_boundaries(gwf, model: CompiledModel, warnings: list[str]) -> None:  # type: ignore[no-untyped-def]
    import flopy

    builders = {
        "well": flopy.mf6.ModflowGwfwel,
        "chd": flopy.mf6.ModflowGwfchd,
        "drn": flopy.mf6.ModflowGwfdrn,
        "riv": flopy.mf6.ModflowGwfriv,
        "ghb": flopy.mf6.ModflowGwfghb,
    }

    for boundary in model.boundaries:
        # SSM reads the inflow concentration from an auxiliary variable, so the
        # name has to be declared on the package that supplies it.
        auxiliary = [TRACER] if boundary.carries_solute else None

        if boundary.kind == "recharge":
            flopy.mf6.ModflowGwfrch(
                gwf,
                stress_period_data=boundary.spd,
                auxiliary=auxiliary,
                pname=boundary.id,
                filename=f"{FLOW_NAME}.{boundary.id}.rch",
            )
            continue

        builder = builders.get(boundary.kind)
        if builder is None:
            warnings.append(f"boundary {boundary.id!r} of kind {boundary.kind!r} was not written")
            continue

        builder(
            gwf,
            stress_period_data=boundary.spd,
            auxiliary=auxiliary,
            pname=boundary.id,
            filename=f"{FLOW_NAME}.{boundary.id}.{boundary.kind}",
        )


def _write_transport(simulation, model: CompiledModel, gwf):  # type: ignore[no-untyped-def]
    """One conservative transport model.

    mf6rtm clones this per PHREEQC component, so the packages here are the ones
    every component shares: the same grid, the same dispersion, the same
    sources. Only initial concentrations differ per component, and those come
    from the chemistry equilibration.
    """
    import flopy

    project = model.project
    grid = model.grid
    properties = model.properties

    gwt = flopy.mf6.ModflowGwt(simulation, modelname=TRANSPORT_NAME, save_flows=True)

    flopy.mf6.ModflowIms(
        simulation,
        complexity="MODERATE",
        # Transport is linear in concentration, so it converges on tighter
        # tolerances than flow without extra cost.
        outer_dvclose=1e-8,
        inner_dvclose=1e-8,
        filename=f"{TRANSPORT_NAME}.ims",
    )
    simulation.register_ims_package(simulation.get_package(f"{TRANSPORT_NAME}.ims"), [gwt.name])

    flopy.mf6.ModflowGwtdis(
        gwt,
        length_units=project.meta.length_unit.upper(),
        nlay=grid.nlay,
        nrow=grid.nrow,
        ncol=grid.ncol,
        delr=grid.delr,
        delc=grid.delc,
        top=grid.top,
        botm=grid.botm,
        xorigin=grid.origin_x,
        yorigin=grid.origin_y,
        angrot=grid.rotation,
    )

    flopy.mf6.ModflowGwtic(gwt, strt=0.0)
    flopy.mf6.ModflowGwtmst(gwt, porosity=properties["transport_porosity"])
    flopy.mf6.ModflowGwtadv(gwt, scheme=project.transport.advection_scheme.upper())

    if project.transport.dispersion.enabled:
        flopy.mf6.ModflowGwtdsp(
            gwt,
            alh=properties["alh"],
            # MODFLOW rejects a longitudinal dispersivity given without a
            # transverse one, so the compiler always supplies both.
            ath1=properties["ath1"],
            atv=properties["atv"],
            diffc=properties["diffc"],
        )

    # Every flow boundary that can carry solute becomes a source. AUX means the
    # concentration is read from an auxiliary variable, which is how mf6rtm
    # feeds per-component boundary chemistry; AUXMIXED would blend it.
    sources = [
        [boundary.id, "AUX", TRACER] for boundary in model.boundaries if boundary.carries_solute
    ]
    if sources:
        flopy.mf6.ModflowGwtssm(gwt, sources=sources)

    flopy.mf6.ModflowGwtoc(
        gwt,
        concentration_filerecord=f"{TRANSPORT_NAME}.ucn",
        budget_filerecord=f"{TRANSPORT_NAME}.cbb",
        saverecord=[("CONCENTRATION", "ALL"), ("BUDGET", "ALL")],
    )
    return gwt


def _safe_name(name: str) -> str:
    """A model name MODFLOW will accept as a filename stem."""
    cleaned = "".join(character if character.isalnum() else "_" for character in name.lower())
    return cleaned.strip("_")[:16] or "model"
