"""Writing ``pht3d_ph.dat``, the file that tells PHT3D what the chemistry is.

The format is unusual and unforgiving, so it is worth saying plainly what it is
before the code assumes it.

The file has no comments, no blank lines, no section keywords and no record
separators. PHT3D reads it with one ``fgets`` per line, in a fixed order, and
the counts in the header are the only thing that says where one block ends and
the next begins. A block written one line short does not fail: the reader takes
the first line of the next block as its own, and every component after that
point is misidentified. The model then runs and gives a confident wrong answer.

Fields within a line are whitespace separated, not fixed-column — every read is
an ``sscanf`` with no field widths. The columns here match what the published
decks use, so a diff against one is readable, but nothing depends on them.

Two things do matter and are easy to get wrong:

* The header line's field count selects a dialect. Eight fields means the older
  format, five or six the newer one. Seven fields parses as the newer one with
  every field silently misassigned, so the count is fixed rather than computed.
* When there is a surface, one extra line follows the surface block to carry its
  options. It is often empty, and it is not optional: leaving it out feeds the
  next block's first line to the option reader.

Written against the PHT3D 2.17 reader, and checked against decks it has run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mupstudio.engines.pht3d.ordering import Component, Group, names

FILENAME = "pht3d_ph.dat"

# The older of the two header dialects: eight fields on the first line, and one
# extra line after the counts. Every published deck we check against uses it,
# and unlike the newer one it does not expect a formula line after a kinetic
# mineral, which is the difference most likely to shift a file by a line.
DIALECT_FIELDS = 8

# Header defaults. Only the temperature is normally worth changing; the rest are
# the values the reference decks use, and two of the fields are read and then
# ignored by this version of PHT3D.
OPERATOR_SPLITTING = 2
UNUSED_FILE_MODE = 1
UNUSED_REDOX_MODE = 0
WRITE_ASCII_OUTPUT = 0
MIN_CONCENTRATION_CHANGE = 1e-10
MIN_PH_CHANGE = 1e-3
UNUSED_PACKET_SIZE = 4000

# PHT3D's reader for kinetic surface species is missing its line read, so a file
# declaring any would desynchronise. None of the reference decks use them.
KINETIC_SURFACES = 0


class PhDatError(Exception):
    """The chemistry cannot be written as PHT3D input."""


@dataclass
class KineticBlock:
    """One rate law, as PHT3D reads it.

    ``initial_moles`` is left out of the file when it is None, and PHT3D then
    uses ten — which is a real amount, not a placeholder, and is what every deck
    written by ORTi3D silently runs with.
    """

    name: str
    parms: list[float]
    formula: str | None = None
    initial_moles: float | None = None


@dataclass
class Chemistry:
    """Everything ``pht3d_ph.dat`` needs, already ordered.

    Separate from the schema's ChemistryModel: by this point the assemblages
    have been flattened into the per-block lists PHT3D reads, and the names are
    the ones PHREEQC will see.
    """

    temperature: float = 25.0
    charge_balance_offset: float = 0.0

    mobile_kinetic: list[KineticBlock] = field(default_factory=list)
    #: Aqueous components, pH and pe last. Each may carry a trailing keyword,
    #: which PHT3D appends to the PHREEQC solution line: "Cl charge".
    aqueous: list[str] = field(default_factory=list)
    immobile_kinetic: list[KineticBlock] = field(default_factory=list)
    #: Gases first, then minerals: PHT3D counts and reads them as one block.
    gases: list[tuple[str, float]] = field(default_factory=list)
    minerals: list[tuple[str, float]] = field(default_factory=list)
    exchange: list[str] = field(default_factory=list)
    surfaces: list[tuple[str, float, float]] = field(default_factory=list)
    surface_option: str = ""
    kinetic_minerals: list[KineticBlock] = field(default_factory=list)


def phreeqc_name(name: str) -> str:
    """A component name as PHREEQC spells it in this file.

    Redox states are written without the sign of the charge here — ``C(4)``,
    not ``C(+4)`` — while the MT3D packages use the signed form. The difference
    is real and is what the reference decks do.
    """
    return name.replace("(+", "(")


def write_ph_dat(chemistry: Chemistry, path: Path) -> str:
    """Write the file, and return what was written.

    Returned as text as well as written so a caller can show it: this is the
    file a chemist reads before believing a GUI, and the one they will compare
    against a deck they wrote by hand.
    """
    _check(chemistry)

    lines: list[str] = [
        _header(chemistry),
        f"{chemistry.charge_balance_offset:>10}",
        f"{len(chemistry.aqueous):9d}",
        # The second number on this line is a gas count that this version of
        # PHT3D reads and ignores; the block itself is sized by the first.
        f"{len(chemistry.gases) + len(chemistry.minerals):9d} {len(chemistry.gases):9d}",
        f"{len(chemistry.exchange):9d} {0:9d}",
        f"{len(chemistry.surfaces):9d}",
        f"{len(chemistry.mobile_kinetic):9d} {len(chemistry.kinetic_minerals):9d} "
        f"{KINETIC_SURFACES:9d} {len(chemistry.immobile_kinetic):9d}",
        # Obsolete, and read only by this dialect. Its contents are discarded,
        # but the line has to be there or every block shifts up by one.
        f"{0:9d} {0:9d}",
    ]

    for block in chemistry.mobile_kinetic:
        lines.extend(_kinetic_lines(block, with_formula=True))

    lines.extend(phreeqc_name(name) for name in chemistry.aqueous)

    for block in chemistry.immobile_kinetic:
        lines.extend(_kinetic_lines(block, with_formula=True))

    for name, saturation_index in [*chemistry.gases, *chemistry.minerals]:
        # The number is a saturation index, not an amount. How much is present
        # comes from the starting concentration in the BTN package.
        lines.append(f"{phreeqc_name(name)}  {saturation_index}")

    # -1 does two jobs: it says the name is already a complete exchange species
    # rather than one to be built from an element, and it asks PHREEQC to
    # equilibrate the exchanger with the water in the cell.
    lines.extend(f"{phreeqc_name(name)} -1" for name in chemistry.exchange)

    for name, area, mass in chemistry.surfaces:
        lines.append(f"{phreeqc_name(name)} {area} {mass}")
    if chemistry.surfaces:
        # Not optional. PHT3D reads one line here whenever there is a surface,
        # so an empty string is how "no options" is spelled.
        lines.append(chemistry.surface_option)

    for block in chemistry.kinetic_minerals:
        # This dialect reads no formula line for a kinetic mineral; the
        # stoichiometry comes from the phase of the same name in the database.
        lines.extend(_kinetic_lines(block, with_formula=False))

    text = "\n".join(lines) + "\n"
    # Written as bytes with explicit newlines: a carriage return would be read
    # as part of the last name on every line, giving components called
    # "Calcite\r" that match nothing in the database.
    Path(path).write_bytes(text.encode("ascii"))
    return text


def _header(chemistry: Chemistry) -> str:
    """The first line, whose field count selects how the rest is read."""
    fields = [
        OPERATOR_SPLITTING,
        UNUSED_FILE_MODE,
        UNUSED_REDOX_MODE,
        chemistry.temperature,
        WRITE_ASCII_OUTPUT,
        MIN_CONCENTRATION_CHANGE,
        MIN_PH_CHANGE,
        UNUSED_PACKET_SIZE,
    ]
    assert len(fields) == DIALECT_FIELDS
    return "".join(f"{value:>10}" for value in fields)


def _kinetic_lines(block: KineticBlock, *, with_formula: bool) -> list[str]:
    """One rate law: a header, one parameter per line, then its formula.

    The parameters are positional and are read one to a line, first token only.
    Writing two on one line would lose the second and leave the block a line
    short, which shifts everything after it.
    """
    head = f"{phreeqc_name(block.name)}    {len(block.parms)}"
    if block.initial_moles is not None:
        head += f" {block.initial_moles}"

    lines = [head, *(f"{value}" for value in block.parms)]
    if with_formula:
        formula = block.formula or phreeqc_name(block.name)
        lines.append(formula if formula.startswith("-") else f"-formula {formula}")
    return lines


def _check(chemistry: Chemistry) -> None:
    """Refuse anything PHT3D would read as something else.

    Each of these is a case where the file stays syntactically valid and the
    meaning changes, which is the failure mode this format invites.
    """
    if not chemistry.aqueous:
        raise PhDatError("a PHT3D model needs aqueous components, including pH and pe")

    tail = [item.split()[0] for item in chemistry.aqueous[-2:]]
    if tail != ["pH", "pe"]:
        # PHT3D finds them by position, never by name: it computes their
        # component numbers from the counts alone.
        raise PhDatError(
            "pH and pe must be the last two aqueous components, in that order; "
            f"this list ends with {', '.join(tail) or 'nothing'}"
        )

    for group in (
        chemistry.mobile_kinetic,
        chemistry.immobile_kinetic,
        chemistry.kinetic_minerals,
    ):
        for block in group:
            if any("\n" in str(parm) for parm in block.parms):
                raise PhDatError(f"a parameter of {block.name!r} spans a line")

    for text in (*(item for item in chemistry.aqueous), chemistry.surface_option):
        if "\n" in text or "\r" in text:
            raise PhDatError(f"{text!r} contains a line break, which would shift the file")


def chemistry_from_components(
    components: list[Component],
    *,
    temperature: float = 25.0,
    saturation_indices: dict[str, float] | None = None,
    kinetics: dict[str, KineticBlock] | None = None,
    surfaces: dict[str, tuple[float, float]] | None = None,
    surface_option: str = "",
    charge_balance: str | None = None,
) -> Chemistry:
    """Build the file's contents from an ordered component list.

    Taking the ordered list rather than the schema is what keeps this honest:
    the blocks written here are the same sequence the BTN and SSM packages
    used, because they came from the same object.
    """
    saturation_indices = saturation_indices or {}
    kinetics = kinetics or {}
    surfaces = surfaces or {}

    aqueous = list(names(components, Group.AQUEOUS))
    if charge_balance:
        # PHREEQC adjusts this one component to balance the solution's charge.
        # It is written as a keyword after the name, which PHT3D passes through.
        if charge_balance not in aqueous:
            raise PhDatError(
                f"charge is balanced on {charge_balance!r}, which is not an aqueous component"
            )
        aqueous = [f"{name} charge" if name == charge_balance else name for name in aqueous]

    def rate(name: str) -> KineticBlock:
        return kinetics.get(name, KineticBlock(name=name, parms=[]))

    return Chemistry(
        temperature=temperature,
        mobile_kinetic=[rate(name) for name in names(components, Group.MOBILE_KINETIC)],
        aqueous=aqueous,
        immobile_kinetic=[rate(name) for name in names(components, Group.IMMOBILE_KINETIC)],
        gases=[(name, saturation_indices.get(name, 0.0)) for name in names(components, Group.GAS)],
        minerals=[
            (name, saturation_indices.get(name, 0.0)) for name in names(components, Group.MINERAL)
        ],
        exchange=list(names(components, Group.EXCHANGE)),
        surfaces=[
            (name, *surfaces.get(name, (0.0, 0.0))) for name in names(components, Group.SURFACE)
        ],
        surface_option=surface_option,
        kinetic_minerals=[rate(name) for name in names(components, Group.KINETIC_MINERAL)],
    )


def block_counts(chemistry: Chemistry) -> dict[str, int]:
    """What the header declares, for checking against a deck."""
    return {
        "aqueous": len(chemistry.aqueous),
        "minerals": len(chemistry.gases) + len(chemistry.minerals),
        "exchange": len(chemistry.exchange),
        "surfaces": len(chemistry.surfaces),
        "mobileKinetic": len(chemistry.mobile_kinetic),
        "kineticMinerals": len(chemistry.kinetic_minerals),
        "immobileKinetic": len(chemistry.immobile_kinetic),
    }


def total_components(chemistry: Chemistry) -> int:
    """MT3DMS's NCOMP: every component, transported or not."""
    return sum(block_counts(chemistry).values())


def mobile_components(chemistry: Chemistry) -> int:
    """MT3DMS's MCOMP.

    pH and pe are counted in the aqueous block but are not transported, so they
    come off the end.
    """
    return len(chemistry.mobile_kinetic) + len(chemistry.aqueous) - 2
