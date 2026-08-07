"""Writing pht3d_ph.dat, checked against a deck PHT3D has run.

This format has no separators and no comments: the header counts are the only
thing that says where one block ends and the next begins. A file one line short
still parses, and every component after the short block is misidentified — the
model runs and reports a plausible wrong answer.

So the tests here are mostly about line counts and positions rather than values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mupstudio.engines.pht3d.ordering import Group, mobile_count, order_components
from mupstudio.engines.pht3d.ph_dat import (
    Chemistry,
    KineticBlock,
    PhDatError,
    chemistry_from_components,
    mobile_components,
    phreeqc_name,
    total_components,
    write_ph_dat,
)

GOLDEN = Path(__file__).parent.parent / "fixtures" / "pht3d_golden" / "ex1"


def engesgaard() -> Chemistry:
    """The chemistry of the published calcite and dolomite column."""
    return chemistry_from_components(
        order_components(
            {
                Group.AQUEOUS: ["C(+4)", "Ca", "Cl", "Mg"],
                Group.MINERAL: ["Calcite", "Dolomite"],
            }
        )
    )


def written(chemistry: Chemistry, tmp_path: Path) -> list[str]:
    return write_ph_dat(chemistry, tmp_path / "pht3d_ph.dat").splitlines()


def field(token: str) -> float | str:
    """A field as PHT3D reads it: a number where it can be, else a name.

    The file is whitespace delimited and every numeric read is an sscanf with
    no field width, so "25" and "25.0" are the same field and "1e-10" and
    "0.0000000001" are too. Comparing text would fail on differences PHT3D
    cannot see.
    """
    try:
        return float(token)
    except ValueError:
        return token


def test_it_reproduces_the_published_deck(tmp_path: Path) -> None:
    """Field for field against the file PHT3D itself read.

    The strongest check we have on this format: same problem, same chemistry,
    and every line has to say the same thing. Column positions are ours to
    choose and are not compared; the values and their order are not ours.
    """
    theirs = [
        [field(token) for token in line.split()]
        for line in GOLDEN.joinpath("Pht3d_ph.dat").read_text().splitlines()
    ]
    ours = [[field(token) for token in line.split()] for line in written(engesgaard(), tmp_path)]

    assert len(ours) == len(theirs), "the file has a different number of lines"
    for index, (mine, published) in enumerate(zip(ours, theirs, strict=True)):
        assert mine == published, f"line {index + 1} differs"


def test_the_header_has_exactly_eight_fields(tmp_path: Path) -> None:
    """The count selects the dialect, and seven is silently misread.

    A seven-field line does not fail: it falls through to the newer format's
    parser, which succeeds and assigns every value to the wrong variable.
    """
    assert len(written(engesgaard(), tmp_path)[0].split()) == 8


def test_ph_and_pe_must_end_the_aqueous_block(tmp_path: Path) -> None:
    """PHT3D finds them by position, computed from the counts, never by name."""
    chemistry = engesgaard()
    chemistry.aqueous = ["Ca", "pe", "pH"]

    with pytest.raises(PhDatError, match="last two aqueous components"):
        write_ph_dat(chemistry, tmp_path / "ph.dat")


def test_aqueous_components_without_ph_at_all_are_refused(tmp_path: Path) -> None:
    chemistry = engesgaard()
    chemistry.aqueous = ["Ca", "Cl"]

    with pytest.raises(PhDatError, match="last two aqueous components"):
        write_ph_dat(chemistry, tmp_path / "ph.dat")


def test_redox_states_lose_the_charge_sign(tmp_path: Path) -> None:
    """This file spells them C(4) where the MT3D packages use C(+4)."""
    assert phreeqc_name("C(+4)") == "C(4)"
    assert phreeqc_name("Fe(+2)") == "Fe(2)"
    # A negative state keeps its sign; only the plus is dropped.
    assert phreeqc_name("S(-2)") == "S(-2)"
    assert "C(4)" in written(engesgaard(), tmp_path)


def test_a_surface_forces_an_extra_line(tmp_path: Path) -> None:
    """PHT3D reads one options line whenever there is a surface.

    Empty is how "no options" is spelled. Omitting the line entirely would feed
    the first kinetic mineral to the option reader and shift the rest.
    """
    chemistry = engesgaard()
    chemistry.surfaces = [("Hfo_w", 600.0, 1.0)]
    chemistry.kinetic_minerals = [KineticBlock(name="Pyrite", parms=[1.0, 2.0])]

    lines = written(chemistry, tmp_path)
    surface = lines.index("Hfo_w 600.0 1.0")

    assert lines[surface + 1] == ""
    assert lines[surface + 2] == "Pyrite    2"


def test_no_extra_line_without_a_surface(tmp_path: Path) -> None:
    chemistry = engesgaard()
    chemistry.kinetic_minerals = [KineticBlock(name="Pyrite", parms=[1.0])]

    lines = written(chemistry, tmp_path)

    assert "" not in lines
    assert lines[-2:] == ["Pyrite    1", "1.0"]


def test_a_kinetic_block_writes_one_parameter_per_line(tmp_path: Path) -> None:
    """Only the first token of a line is read, so two on one would lose one."""
    chemistry = engesgaard()
    chemistry.mobile_kinetic = [
        KineticBlock(name="Orgc", parms=[9.5e-10, 0.0, 0.0], formula="Orgc -1.0 C 1.0")
    ]

    lines = written(chemistry, tmp_path)
    start = lines.index("Orgc    3")

    assert lines[start + 1 : start + 5] == ["9.5e-10", "0.0", "0.0", "-formula Orgc -1.0 C 1.0"]


def test_a_kinetic_mineral_gets_no_formula_line(tmp_path: Path) -> None:
    """This dialect does not read one, so writing it would shift the file.

    The difference between the two dialects, and the one most likely to be got
    wrong: a mobile kinetic reactant does take a formula line, a kinetic
    mineral in this dialect does not.
    """
    chemistry = engesgaard()
    chemistry.kinetic_minerals = [KineticBlock(name="Calcite", parms=[1e2, 0.6], formula="ignored")]

    lines = written(chemistry, tmp_path)

    assert lines[-3:] == ["Calcite    2", "100.0", "0.6"]


def test_the_initial_amount_is_written_only_when_given(tmp_path: Path) -> None:
    """Left out, PHT3D uses ten — a real amount, not a placeholder."""
    chemistry = engesgaard()
    chemistry.mobile_kinetic = [KineticBlock(name="Orgc", parms=[], initial_moles=4.0)]
    assert written(chemistry, tmp_path)[8] == "Orgc    0 4.0"

    chemistry.mobile_kinetic = [KineticBlock(name="Orgc", parms=[])]
    assert written(chemistry, tmp_path)[8] == "Orgc    0"


def test_an_exchanger_asks_to_be_equilibrated(tmp_path: Path) -> None:
    """-1 keeps the name as given and equilibrates it with the cell's water."""
    chemistry = engesgaard()
    chemistry.exchange = ["CaX2", "NaX"]

    lines = written(chemistry, tmp_path)

    assert "CaX2 -1" in lines
    assert "NaX -1" in lines


def test_gases_are_counted_with_the_minerals_and_come_first(tmp_path: Path) -> None:
    """PHT3D reads them as one block sized by the first number on that line."""
    chemistry = engesgaard()
    chemistry.gases = [("CO2(g)", -3.5)]

    lines = written(chemistry, tmp_path)
    counts = lines[3].split()

    assert counts == ["3", "1"]  # three entries, of which one is a gas
    assert lines[14:17] == ["CO2(g)  -3.5", "Calcite  0.0", "Dolomite  0.0"]


def test_the_counts_line_up_with_the_blocks(tmp_path: Path) -> None:
    """The header is the only thing separating blocks, so it has to be right."""
    chemistry = chemistry_from_components(
        order_components(
            {
                Group.MOBILE_KINETIC: ["Orgc"],
                Group.AQUEOUS: ["Ca", "Cl"],
                Group.IMMOBILE_KINETIC: ["Sed"],
                Group.MINERAL: ["Calcite"],
                Group.EXCHANGE: ["CaX2"],
                Group.SURFACE: ["Hfo_w"],
                Group.KINETIC_MINERAL: ["Pyrite"],
            }
        )
    )
    lines = written(chemistry, tmp_path)

    assert int(lines[2]) == 4  # Ca, Cl, pH, pe
    assert lines[3].split()[0] == "1"  # Calcite
    assert lines[4].split()[0] == "1"  # CaX2
    assert int(lines[5]) == 1  # Hfo_w
    assert lines[6].split() == ["1", "1", "0", "1"]  # mobile, mineral, surface, immobile kinetics

    # Eight header lines, then every block, then the mandatory surface option.
    assert len(lines) == (
        8  # header
        + 2  # Orgc: a name line and a formula line, no parameters
        + 4  # Ca, Cl, pH, pe
        + 2  # Sed, likewise
        + 1  # Calcite
        + 1  # CaX2
        + 1  # Hfo_w
        + 1  # its options line, empty but present
        + 1  # Pyrite, with no formula line in this dialect
    )


def test_the_component_totals_agree_with_the_transport_deck() -> None:
    """The two files have to declare the same model.

    NCOMP and MCOMP are written into the BTN package from the ordered component
    list, and derived here from the blocks. They come from the same place, and
    this is what says so.
    """
    components = order_components(
        {Group.AQUEOUS: ["C(+4)", "Ca", "Cl", "Mg"], Group.MINERAL: ["Calcite", "Dolomite"]}
    )
    chemistry = chemistry_from_components(components)

    assert total_components(chemistry) == len(components) == 8
    assert mobile_components(chemistry) == mobile_count(components) == 4


def test_charge_can_be_balanced_on_a_component(tmp_path: Path) -> None:
    """Written as a keyword after the name, which PHT3D passes to PHREEQC."""
    chemistry = chemistry_from_components(
        order_components({Group.AQUEOUS: ["Ca", "Cl"]}), charge_balance="Cl"
    )

    assert "Cl charge" in written(chemistry, tmp_path)


def test_balancing_on_something_that_is_not_there_is_refused() -> None:
    with pytest.raises(PhDatError, match="not an aqueous component"):
        chemistry_from_components(order_components({Group.AQUEOUS: ["Ca"]}), charge_balance="Na")


def test_the_file_has_unix_line_endings(tmp_path: Path) -> None:
    """A carriage return would be read as part of the last name on the line."""
    path = tmp_path / "pht3d_ph.dat"
    write_ph_dat(engesgaard(), path)
    raw = path.read_bytes()

    assert b"\r" not in raw
    assert raw.endswith(b"\n")


def test_a_name_with_a_line_break_is_refused(tmp_path: Path) -> None:
    """It would add a line and shift every block after it."""
    chemistry = engesgaard()
    chemistry.aqueous = ["Ca\nCl", "pH", "pe"]

    with pytest.raises(PhDatError, match="line break"):
        write_ph_dat(chemistry, tmp_path / "ph.dat")
