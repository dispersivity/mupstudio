"""The order PHT3D numbers components in.

This module is the sole authority on that order, and everything else in the
PHT3D writer asks it rather than deciding for itself. That is not tidiness: the
same sequence has to appear in four unrelated places — the BTN package's initial
concentrations, the SSM package's per-source concentration strings, the blocks
of ``pht3d_ph.dat``, and the numbering of the ``PHT3D00n.UCN`` output files. If
any one of them disagrees, PHT3D still runs, and the answer is silently wrong:
calcium transported as chloride, a mineral read as a pH.

The order is not ours to choose. PHT3D assigns component numbers as it reads the
blocks of ``pht3d_ph.dat``, so the order below is the order those blocks appear
in that file:

    1. mobile kinetic reactants
    2. aqueous components under local equilibrium, with pH and pe last
    3. immobile kinetic reactants
    4. gas phase components
    5. equilibrium minerals
    6. exchange species
    7. surface species
    8. kinetic minerals

Only groups 1 and 2 are transported; everything from 3 on stays where it is.
MT3D calls the transported count MCOMP and the total NCOMP, and expects the
mobile ones to come first, which is why the order above is also a partition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# What PHREEQC reports for a solution beyond its dissolved species. They are
# read and written as components, but they are recomputed by the chemistry
# rather than carried by the flow, so they do not move.
SOLUTION_HEADS = ("pH", "pe")


class Group(Enum):
    """A kind of component, named by the block it comes from.

    The values are the ORTi3D shorthand for each group, kept because the PHT3D
    literature and the reference implementations both use those letters, and a
    reader checking this against a paper should not have to translate.
    """

    MOBILE_KINETIC = "k"
    AQUEOUS = "i"
    IMMOBILE_KINETIC = "kim"
    GAS = "g"
    MINERAL = "p"
    EXCHANGE = "e"
    SURFACE = "s"
    KINETIC_MINERAL = "kp"


# The order PHT3D reads the blocks in, and so the order it numbers components.
ORDER: tuple[Group, ...] = (
    Group.MOBILE_KINETIC,
    Group.AQUEOUS,
    Group.IMMOBILE_KINETIC,
    Group.GAS,
    Group.MINERAL,
    Group.EXCHANGE,
    Group.SURFACE,
    Group.KINETIC_MINERAL,
)

# Groups the flow model carries. The rest are fixed to their cell.
MOBILE: frozenset[Group] = frozenset({Group.MOBILE_KINETIC, Group.AQUEOUS})


@dataclass(frozen=True)
class Component:
    """One transported or stored quantity, and where it came from."""

    name: str
    group: Group
    #: Where this sits in PHT3D's numbering, counting from one.
    number: int

    @property
    def is_mobile(self) -> bool:
        """Whether the flow carries this component.

        pH and pe are the exception that makes this a property rather than a
        lookup on the group. They sit inside the aqueous block — the block count
        in ``pht3d_ph.dat`` includes them — but PHT3D does not transport them:
        they are recomputed from the transported components at every reaction
        step. The published Engesgaard deck shows both facts at once, declaring
        six aqueous names and four mobile components.
        """
        return self.group in MOBILE and self.name not in SOLUTION_HEADS

    @property
    def ucn_file(self) -> str:
        """The output file PHT3D writes this component to.

        Numbered rather than named, which is the whole reason this order has to
        be right: nothing in ``PHT3D007.UCN`` says it holds calcite.
        """
        return f"PHT3D{self.number:03d}.UCN"


class OrderingError(Exception):
    """The component lists cannot be ordered as PHT3D requires."""


def order_components(members: dict[Group, list[str]]) -> list[Component]:
    """Number every component, in the order PHT3D will read them.

    ``members`` gives the names in each group, already in the order they should
    appear within it. pH and pe are appended to the aqueous group here rather
    than by the caller, because their position — last among the aqueous
    components, before anything immobile — is part of the format and not a
    choice a caller should be able to get wrong.
    """
    if not any(members.get(group) for group in ORDER):
        # Checked before pH and pe are added, which would otherwise make an
        # empty model look like a model with two components in it.
        raise OrderingError("a PHT3D model needs at least one component")

    aqueous = list(members.get(Group.AQUEOUS, []))
    for head in SOLUTION_HEADS:
        if head in aqueous:
            raise OrderingError(
                f"{head} is added by the writer and must not be given as an aqueous "
                "component; it would otherwise appear twice"
            )
    aqueous.extend(SOLUTION_HEADS)

    ordered: list[Component] = []
    for group in ORDER:
        names = aqueous if group is Group.AQUEOUS else members.get(group, [])
        for name in names:
            ordered.append(Component(name=name, group=group, number=len(ordered) + 1))

    _check_mobile_come_first(ordered)
    return ordered


def _check_mobile_come_first(components: list[Component]) -> None:
    """MT3D requires the transported components to be a leading run.

    Guaranteed by ORDER, so a failure here means ORDER was edited into something
    MT3D cannot express — worth catching at the point of the mistake rather than
    in a Fortran read.
    """
    seen_immobile = False
    for component in components:
        if component.is_mobile and seen_immobile:
            raise OrderingError(
                f"{component.name!r} is mobile but follows an immobile component; "
                "MT3D needs every mobile component before every immobile one"
            )
        seen_immobile = seen_immobile or not component.is_mobile


def mobile_count(components: list[Component]) -> int:
    """MT3D's MCOMP: how many components the flow actually carries."""
    return sum(1 for component in components if component.is_mobile)


def names(components: list[Component], group: Group) -> list[str]:
    """The names in one group, in order."""
    return [component.name for component in components if component.group is group]


def count(components: list[Component], group: Group) -> int:
    return sum(1 for component in components if component.group is group)
