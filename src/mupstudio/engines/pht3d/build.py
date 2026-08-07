"""Turning a project's chemistry into a PHT3D deck.

The two engines learn their component list in opposite ways. MF6RTM has to
equilibrate the chemistry with PhreeqcRM first and read the list back, because
PHREEQC decides what the components are. PHT3D is told: the deck declares the
list, and PHT3D speciates against it.

That makes this the simpler path of the two, and an entirely offline one — no
subprocess, no PHREEQC, no waiting. What the chemistry says is what gets
written.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

import numpy as np
from pydantic import BaseModel

from mupstudio.compile.compiler import CompiledModel
from mupstudio.engines.pht3d import ph_dat
from mupstudio.engines.pht3d.deck import Pht3dDeck, write_pht3d
from mupstudio.engines.pht3d.ordering import Component, Group, order_components
from mupstudio.schema.chemistry import ChemistryModel, Composition

log = logging.getLogger(__name__)


class Pht3dBuildError(Exception):
    """The chemistry cannot be expressed as a PHT3D deck."""


def component_groups(chemistry: ChemistryModel) -> dict[Group, list[str]]:
    """What goes in each block, from what the chemistry defines.

    Sorted within each group so the same project always produces the same
    component numbering. That is not cosmetic: the numbering is what the output
    files are named by, and a project whose component 7 changed between runs
    would silently relabel every result.
    """
    aqueous = sorted({name for item in chemistry.solutions for name in item.concentrations})

    minerals = sorted(
        {target.phase for item in chemistry.equilibrium_phases for target in item.phases}
    )
    exchange = sorted({name for item in chemistry.exchange for name in item.sites})
    surfaces = sorted({site.site for item in chemistry.surface for site in item.sites})
    gases = sorted({name for item in chemistry.gas_phases for name in item.partial_pressures})

    # Every kinetic reaction is treated as acting on a mineral where the model
    # also lists that mineral, and as a mobile reactant otherwise. PHT3D reads
    # the two from different blocks and gives them different numbers.
    rates = sorted({item.rate for group in chemistry.kinetics for item in group.reactions})
    kinetic_minerals = [name for name in rates if name in set(minerals)]
    mobile_kinetic = [name for name in rates if name not in set(minerals)]

    return {
        Group.MOBILE_KINETIC: mobile_kinetic,
        Group.AQUEOUS: aqueous,
        Group.GAS: gases,
        Group.MINERAL: [name for name in minerals if name not in set(kinetic_minerals)],
        Group.EXCHANGE: exchange,
        Group.SURFACE: surfaces,
        Group.KINETIC_MINERAL: kinetic_minerals,
    }


def initial_conditions(model: CompiledModel, components: list[Component]) -> dict[str, np.ndarray]:
    """Each component's starting value in every cell.

    Painted from the compositions: a cell's solution gives its dissolved
    concentrations, its mineral assemblage gives the amounts present, and so on.
    Anything a composition does not name is absent there, which is zero and is
    floored later.
    """
    compiled = model.chemistry
    chemistry = model.project.chemistry
    if compiled is None:
        raise Pht3dBuildError("this project has no chemistry to write")

    shape = model.grid.shape
    values = {component.name: np.zeros(shape, dtype=np.float64) for component in components}

    for composition_id in _composition_order(chemistry):
        composition = chemistry.composition(composition_id)
        # Cells assigned this composition, found from any one of its blocks: a
        # composition always names a solution, so that map is the definitive one.
        where = compiled.assemblages["solution"] == compiled.number_of(
            "solution", composition.solution
        )

        for name, amount in _amounts(chemistry, composition).items():
            if name in values:
                values[name][where] = amount

    return values


def _composition_order(chemistry: ChemistryModel) -> list[str]:
    """Compositions in painting order: background first, then the zones.

    The same order the cell maps were built in, so a later zone overwrites an
    earlier one here exactly as it did there.
    """
    order = [chemistry.background] if chemistry.background else []
    order.extend(zone.composition for zone in chemistry.zones)
    return [item for item in order if item]


_Named = TypeVar("_Named", bound=BaseModel)


def _find(items: Sequence[_Named], wanted: str | None) -> _Named | None:
    """The assemblage a composition names, if it names one."""
    if wanted is None:
        return None
    return next((item for item in items if getattr(item, "id", None) == wanted), None)


def _amounts(chemistry: ChemistryModel, composition: Composition) -> dict[str, float]:
    """Every starting value one composition implies.

    Each block is looked up separately rather than in one loop: they are
    different types that happen to share an id, and merging them would hide a
    field name that exists on one and not another.
    """
    solution = chemistry.solution(composition.solution)
    amounts: dict[str, float] = {
        **solution.concentrations,
        "pH": solution.ph,
        "pe": solution.pe,
    }

    if (
        minerals := _find(chemistry.equilibrium_phases, composition.equilibrium_phases)
    ) is not None:
        amounts.update({target.phase: target.moles for target in minerals.phases})

    if (exchanger := _find(chemistry.exchange, composition.exchange)) is not None:
        amounts.update(exchanger.sites)

    if (surface := _find(chemistry.surface, composition.surface)) is not None:
        amounts.update({site.site: site.moles for site in surface.sites})

    if (gas := _find(chemistry.gas_phases, composition.gas_phase)) is not None:
        amounts.update(gas.partial_pressures)

    if (rates := _find(chemistry.kinetics, composition.kinetics)) is not None:
        amounts.update({reaction.rate: reaction.initial_moles for reaction in rates.reactions})

    return amounts


def boundary_chemistry(chemistry: ChemistryModel) -> dict[str, dict[str, float]]:
    """The water each flow boundary injects, by component."""
    assignments: dict[str, dict[str, float]] = {}

    for package_id, solution_id in chemistry.boundary_solutions.items():
        solution = chemistry.solution(solution_id)
        assignments[package_id] = {
            **solution.concentrations,
            "pH": solution.ph,
            "pe": solution.pe,
        }

    return assignments


def chemistry_file(chemistry: ChemistryModel, components: list[Component]) -> ph_dat.Chemistry:
    """The contents of pht3d_ph.dat for this project."""
    saturation = {
        target.phase: target.saturation_index
        for item in chemistry.equilibrium_phases
        for target in item.phases
    }
    rates = {
        reaction.rate: ph_dat.KineticBlock(
            name=reaction.rate,
            parms=list(reaction.parms),
            formula=reaction.formula,
            initial_moles=reaction.initial_moles or None,
        )
        for group in chemistry.kinetics
        for reaction in group.reactions
    }
    surfaces = {
        site.site: (site.specific_area, site.mass)
        for item in chemistry.surface
        for site in item.sites
    }
    # mf6rtm applies one double layer model to every surface, and so does this
    # file: PHT3D reads a single options line for all of them.
    models = {item.edl_model for item in chemistry.surface}
    option = "" if models == {"diffuse_layer"} else f"-{models.pop()}" if models else ""

    return ph_dat.chemistry_from_components(
        components,
        temperature=chemistry.solutions[0].temperature if chemistry.solutions else 25.0,
        saturation_indices=saturation,
        kinetics=rates,
        surfaces=surfaces,
        surface_option=option,
        charge_balance=_charge_balance(chemistry),
    )


def _charge_balance(chemistry: ChemistryModel) -> str | None:
    """The component PHREEQC adjusts to balance charge, if the solutions agree.

    PHT3D declares it once for the whole model, not per solution, so solutions
    that disagree cannot be written and say so rather than having one of them
    silently applied to all.
    """
    chosen = {item.charge_balance for item in chemistry.solutions if item.charge_balance}
    if len(chosen) > 1:
        raise Pht3dBuildError(
            "the solutions balance charge on different components "
            f"({', '.join(sorted(chosen))}); PHT3D applies one to the whole model"
        )
    return chosen.pop() if chosen else None


def build_deck(model: CompiledModel, workdir: Path) -> Pht3dDeck:
    """Write a complete PHT3D run from a project.

    The whole path, offline: no equilibration step and no subprocess, because
    PHT3D takes the component list rather than deriving it.
    """
    chemistry = model.project.chemistry
    if not chemistry.enabled or not chemistry.solutions:
        raise Pht3dBuildError("PHT3D runs reactive models; this project has no chemistry defined")

    components = order_components(component_groups(chemistry))

    return write_pht3d(
        model,
        Path(workdir),
        components,
        chemistry_file(chemistry, components),
        initial_conditions(model, components),
        boundary_chemistry(chemistry),
    )
