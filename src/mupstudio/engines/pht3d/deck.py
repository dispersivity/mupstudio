"""Assembling a complete PHT3D run directory.

Three writers produce the pieces — the MODFLOW-2005 flow twin, the MT3DMS
transport packages, and the chemistry file — and this puts them together and
writes the name file that ties them into one run.

The name file is written here rather than by FloPy because FloPy has no PHC
entry: that is the line pointing at ``pht3d_ph.dat``, and without it the model
runs as plain MT3DMS with no chemistry at all. It is the one difference between
a transport deck and a reactive one, and it is a single line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from mupstudio.compile.compiler import CompiledModel
from mupstudio.engines.pht3d import flow as flow_writer
from mupstudio.engines.pht3d import ph_dat, transport
from mupstudio.engines.pht3d.ordering import Component

log = logging.getLogger(__name__)

NAME_FILE = "pht3d.nam"
LIST_FILE = "pht3d.out"

# Fortran unit numbers. PHT3D opens files by the unit given here, and the
# numbers are conventional rather than arbitrary: the published decks use these
# and the FTL unit in particular has to match what MODFLOW's LMT package wrote.
UNITS = {
    "list": 7,
    "ftl": 66,
    "btn": 41,
    "adv": 42,
    "dsp": 43,
    "ssm": 44,
    "gcg": 45,
    "phc": 64,
}


@dataclass
class Pht3dDeck:
    """A directory PHT3D can be run in."""

    workdir: Path
    name_file: str
    components: list[Component]
    files: list[str]
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        moving = sum(1 for item in self.components if item.is_mobile)
        return f"{len(self.components)} components, {moving} transported, {len(self.files)} files"


def write_pht3d(
    model: CompiledModel,
    workdir: Path,
    components: list[Component],
    chemistry: ph_dat.Chemistry,
    initial: dict[str, np.ndarray],
    boundary: dict[str, dict[str, float]],
) -> Pht3dDeck:
    """Write the whole run: flow, transport and chemistry.

    Everything is driven by one ordered component list, which is what keeps the
    three files describing the same model. The BTN's species, the SSM's
    concentration strings and the blocks of pht3d_ph.dat are the same sequence
    because they are built from the same object.
    """
    workdir = Path(workdir)
    _check_agrees(components, chemistry)

    twin = flow_writer.write_flow(model, workdir)
    deck = transport.write_transport(model, workdir, components, initial, boundary, ftl=twin.ftl)
    ph_dat.write_ph_dat(chemistry, workdir / ph_dat.FILENAME)
    write_name_file(workdir, transport_name=deck.name, ftl=twin.ftl)

    return Pht3dDeck(
        workdir=workdir,
        name_file=NAME_FILE,
        components=components,
        files=sorted(path.name for path in workdir.iterdir() if path.is_file()),
        warnings=[*twin.warnings, *deck.warnings],
    )


def write_name_file(workdir: Path, *, transport_name: str, ftl: str) -> Path:
    """The name file, including the PHC entry that makes the run reactive.

    Without the PHC line PHT3D is MT3DMS: it transports the components and
    never reacts them. Nothing warns about that — the run finishes and the
    minerals never change.
    """
    entries = [
        ("List", UNITS["list"], LIST_FILE),
        ("FTL", UNITS["ftl"], ftl),
        ("btn", UNITS["btn"], f"{transport_name}.btn"),
        ("adv", UNITS["adv"], f"{transport_name}.adv"),
        ("dsp", UNITS["dsp"], f"{transport_name}.dsp"),
        ("ssm", UNITS["ssm"], f"{transport_name}.ssm"),
        ("gcg", UNITS["gcg"], f"{transport_name}.gcg"),
        ("PHC", UNITS["phc"], ph_dat.FILENAME),
    ]
    # Files PHT3D produces or is handed later, so their absence now says
    # nothing. The link file in particular is written by MODFLOW when the flow
    # twin runs, which is after this: leaving it out because it does not exist
    # yet gives a deck that runs, finishes, and transports nothing.
    always = {"List", "FTL", "PHC"}
    present = [
        (kind, unit, name)
        for kind, unit, name in entries
        # An input package the model does not have — dispersion, most often —
        # is left out rather than named and missing, which PHT3D treats as an
        # error.
        if kind in always or (workdir / name).exists()
    ]

    path = workdir / NAME_FILE
    path.write_text("\n".join(f" {kind}  {unit}  {name}" for kind, unit, name in present) + "\n")
    return path


def _check_agrees(components: list[Component], chemistry: ph_dat.Chemistry) -> None:
    """The transport deck and the chemistry file must describe one model.

    They are written by different functions from different inputs, and PHT3D
    checks neither against the other: it takes the counts from the chemistry
    file and the arrays from the transport file, and reads whichever is shorter
    off the end of the other.
    """
    total = ph_dat.total_components(chemistry)
    if total != len(components):
        raise ph_dat.PhDatError(
            f"the chemistry declares {total} components and the transport deck has "
            f"{len(components)}; they have to be the same model"
        )
