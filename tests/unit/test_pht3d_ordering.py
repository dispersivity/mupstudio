"""The component order PHT3D imposes.

These are the cheapest tests in the project and among the most valuable. A
wrong order does not crash PHT3D; it produces a complete, plausible answer with
calcium's numbers under chloride's name. Nothing downstream can detect that, so
it has to be caught here.
"""

from __future__ import annotations

import pytest

from mupstudio.engines.pht3d.ordering import (
    ORDER,
    Group,
    OrderingError,
    count,
    mobile_count,
    names,
    order_components,
)


def test_ph_and_pe_are_added_last_among_the_aqueous() -> None:
    """Their position is part of the format, not the caller's choice."""
    components = order_components({Group.AQUEOUS: ["Ca", "Cl"]})

    assert [item.name for item in components] == ["Ca", "Cl", "pH", "pe"]


def test_giving_ph_yourself_is_refused() -> None:
    """It would otherwise be written twice and shift every later component."""
    with pytest.raises(OrderingError, match="must not be given"):
        order_components({Group.AQUEOUS: ["Ca", "pH"]})


def test_the_full_order_matches_what_pht3d_reads() -> None:
    components = order_components(
        {
            Group.MOBILE_KINETIC: ["Orgc"],
            Group.AQUEOUS: ["Ca", "Cl"],
            Group.IMMOBILE_KINETIC: ["Orgc_sed"],
            Group.GAS: ["CO2(g)"],
            Group.MINERAL: ["Calcite"],
            Group.EXCHANGE: ["CaX2"],
            Group.SURFACE: ["Hfo_w"],
            Group.KINETIC_MINERAL: ["Pyrite"],
        }
    )

    assert [item.name for item in components] == [
        "Orgc",
        "Ca",
        "Cl",
        "pH",
        "pe",
        "Orgc_sed",
        "CO2(g)",
        "Calcite",
        "CaX2",
        "Hfo_w",
        "Pyrite",
    ]


def test_numbering_starts_at_one_and_has_no_gaps() -> None:
    components = order_components(
        {Group.AQUEOUS: ["Ca", "Cl"], Group.MINERAL: ["Calcite", "Dolomite"]}
    )

    assert [item.number for item in components] == [1, 2, 3, 4, 5, 6]


def test_only_the_aqueous_and_mobile_kinetics_move() -> None:
    """Everything else is fixed to its cell, and MT3D has to be told which."""
    components = order_components(
        {
            Group.MOBILE_KINETIC: ["Orgc"],
            Group.AQUEOUS: ["Ca", "Cl"],
            Group.MINERAL: ["Calcite"],
        }
    )

    assert mobile_count(components) == 3  # Orgc, Ca, Cl
    assert [item.name for item in components if not item.is_mobile] == ["pH", "pe", "Calcite"]


def test_ph_and_pe_are_components_but_are_not_transported() -> None:
    """The exception that makes mobility a property rather than a group lookup.

    They are counted in the aqueous block of pht3d_ph.dat, so they occupy
    component numbers; but PHT3D recomputes them from the transported
    components every reaction step rather than moving them with the water.
    """
    components = order_components({Group.AQUEOUS: ["Ca"]})

    assert [item.name for item in components] == ["Ca", "pH", "pe"]
    assert mobile_count(components) == 1
    assert [item.name for item in components if not item.is_mobile] == ["pH", "pe"]


def test_every_mobile_component_comes_before_every_immobile_one() -> None:
    """MT3D reads MCOMP as a count, so the mobile ones have to be a leading run."""
    components = order_components(
        {
            Group.MOBILE_KINETIC: ["Orgc"],
            Group.AQUEOUS: ["Ca"],
            Group.IMMOBILE_KINETIC: ["Sed"],
            Group.MINERAL: ["Calcite"],
        }
    )

    flags = [item.is_mobile for item in components]
    assert flags == sorted(flags, reverse=True)


def test_the_order_constant_puts_the_mobile_groups_first() -> None:
    """A guard on ORDER itself: reordering it must not break the partition."""
    positions = [index for index, group in enumerate(ORDER) if group in {Group.AQUEOUS}]
    immobile = [
        index
        for index, group in enumerate(ORDER)
        if group not in {Group.AQUEOUS, Group.MOBILE_KINETIC}
    ]

    assert max(positions) < min(immobile)


def test_output_files_are_numbered_not_named() -> None:
    """The reason the order matters: nothing in the file says what it holds."""
    components = order_components({Group.AQUEOUS: ["Ca", "Cl"], Group.MINERAL: ["Calcite"]})

    assert components[0].ucn_file == "PHT3D001.UCN"
    assert components[-1].ucn_file == "PHT3D005.UCN"


def test_a_model_with_nothing_in_it_is_refused() -> None:
    with pytest.raises(OrderingError, match="at least one component"):
        order_components({})


def test_names_and_counts_read_back_per_group() -> None:
    components = order_components(
        {Group.AQUEOUS: ["Ca", "Cl"], Group.MINERAL: ["Calcite", "Dolomite"]}
    )

    assert names(components, Group.MINERAL) == ["Calcite", "Dolomite"]
    assert count(components, Group.AQUEOUS) == 4
    assert count(components, Group.SURFACE) == 0


def test_the_engesgaard_column_reproduces_its_benchmark_deck() -> None:
    """The published PHT3D deck for this problem is the reference.

    Its BTN declares NCOMP 8 and MCOMP 4, with C(+4), Ca, Cl, Mg, pH, pe,
    Calcite and Dolomite in that order. Matching it here is what says our
    ordering agrees with a deck PHT3D has actually run.
    """
    components = order_components(
        {
            Group.AQUEOUS: ["C(+4)", "Ca", "Cl", "Mg"],
            Group.MINERAL: ["Calcite", "Dolomite"],
        }
    )

    assert [item.name for item in components] == [
        "C(+4)",
        "Ca",
        "Cl",
        "Mg",
        "pH",
        "pe",
        "Calcite",
        "Dolomite",
    ]
    assert len(components) == 8
    # The deck declares NCOMP 8 and MCOMP 4: pH and pe are named but not moved.
    assert mobile_count(components) == 4
