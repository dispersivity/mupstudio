"""Translating chemistry into the shapes mf6rtm's blocks expect.

mf6rtm takes each PHREEQC block as a nested dict keyed by assemblage number,
which is what its CSV helpers produce. The schema instead keeps named
assemblages and named compositions, so this is where names become numbers.

Nothing here imports mf6rtm or phreeqcrm. It builds plain dicts and arrays, so
it can be tested without a chemistry engine and shipped to the write worker as
JSON. The worker does the importing.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from mupstudio.compile.compiler import CompiledChemistry, CompiledModel
from mupstudio.schema.chemistry import ChemistryModel

# What PHREEQC wants in a SOLUTION block ahead of the concentrations. mf6rtm
# passes these through as ordinary keys, so they sit in the same dict.
SOLUTION_HEADS = ("pH", "pe")


class ChemistryError(Exception):
    """The chemistry cannot be turned into PHREEQC input."""


def solutions_block(chemistry: ChemistryModel, order: list[str]) -> dict[str, list[float]]:
    """Solutions as species rows across numbered columns.

    mf6rtm reads ``{species: [value in solution 1, value in solution 2, ...]}``,
    the transpose of how they are edited. A species absent from one solution is
    zero there rather than missing, because the columns have to line up.
    """
    if not order:
        raise ChemistryError("a reactive model needs at least one solution")

    by_id = {item.id: item for item in chemistry.solutions}
    solutions = [by_id[item] for item in order]

    species = sorted({name for solution in solutions for name in solution.concentrations})
    block: dict[str, list[float]] = {
        "pH": [solution.ph for solution in solutions],
        "pe": [solution.pe for solution in solutions],
    }
    for name in species:
        block[name] = [solution.concentrations.get(name, 0.0) for solution in solutions]
    return block


def equilibrium_block(
    chemistry: ChemistryModel, order: list[str]
) -> dict[int, dict[str, dict[str, float]]]:
    """Equilibrium phases as ``{number: {phase: {si, m0}}}``."""
    by_id = {item.id: item for item in chemistry.equilibrium_phases}
    return {
        number: {
            target.phase: {"si": target.saturation_index, "m0": target.moles}
            for target in by_id[item].phases
        }
        for number, item in enumerate(order, start=1)
    }


def exchange_block(chemistry: ChemistryModel, order: list[str]) -> dict[int, dict[str, Any]]:
    """Exchange sites as ``{number: {species: {m0}}}``."""
    by_id = {item.id: item for item in chemistry.exchange}
    return {
        number: {species: {"m0": moles} for species, moles in by_id[item].sites.items()}
        for number, item in enumerate(order, start=1)
    }


def exchange_equilibrations(
    chemistry: ChemistryModel, order: list[str], solutions: list[str]
) -> list[int]:
    """Which solution each exchanger starts in equilibrium with.

    Zero means the exchanger is given as fixed composition instead. mf6rtm wants
    one entry per assemblage in the same order as the block.
    """
    by_id = {item.id: item for item in chemistry.exchange}
    return [
        solutions.index(target) + 1 if (target := by_id[item].equilibrate_with) in solutions else 0
        for item in order
    ]


def surface_block(chemistry: ChemistryModel, order: list[str]) -> dict[int, dict[str, list[str]]]:
    """Surfaces as ``{number: {site: [name, switch, moles, area, mass]}}``.

    mf6rtm passes this row through to the SURFACE block as text, in the order
    PHREEQC reads it, so the values are strings by the time they get here.
    """
    by_id = {item.id: item for item in chemistry.surface}
    block: dict[int, dict[str, list[str]]] = {}

    for number, item in enumerate(order, start=1):
        assemblage = by_id[item]
        rows: dict[str, list[str]] = {}
        for site in assemblage.sites:
            # The site name doubles as the surface name where no separate one is
            # given, which is the common case for a single-site sorbent.
            rows[site.site] = [
                site.site,
                "equilibrium_phase",
                repr(site.moles),
                repr(site.specific_area),
                repr(site.mass),
            ]
        block[number] = rows

    return block


def surface_options(chemistry: ChemistryModel, order: list[str]) -> list[str]:
    """The double-layer keyword for the surfaces, if they agree on one.

    PHREEQC sets the double-layer model per SURFACE block, but mf6rtm applies
    options to all of them at once, so a project that mixes models cannot be
    written and says so rather than silently using the first.
    """
    by_id = {item.id: item for item in chemistry.surface}
    models = {by_id[item].edl_model for item in order}
    if len(models) > 1:
        raw = ", ".join(sorted(models))
        raise ChemistryError(
            f"the surfaces use different double layer models ({raw}); mf6rtm applies "
            "one to all of them, so they have to agree"
        )
    model = models.pop() if models else "no_edl"
    return [] if model == "diffuse_layer" else [model]


def kinetics_block(chemistry: ChemistryModel, order: list[str]) -> dict[int, dict[str, Any]]:
    """Kinetics as ``{number: {rate: {m0, parms, formula}}}``."""
    by_id = {item.id: item for item in chemistry.kinetics}
    block: dict[int, dict[str, Any]] = {}

    for number, item in enumerate(order, start=1):
        reactions: dict[str, Any] = {}
        for reaction in by_id[item].reactions:
            entry: dict[str, Any] = {
                "m0": reaction.initial_moles,
                "parms": list(reaction.parms),
            }
            if reaction.formula:
                entry["formula"] = reaction.formula
            if reaction.steps:
                entry["steps"] = list(reaction.steps)
            reactions[reaction.rate] = entry
        block[number] = reactions

    return block


def gas_block(chemistry: ChemistryModel, order: list[str]) -> dict[int, dict[str, Any]]:
    """Gas phases as ``{number: {gas: partial pressure}}``."""
    by_id = {item.id: item for item in chemistry.gas_phases}
    return {
        number: dict(by_id[item].partial_pressures) for number, item in enumerate(order, start=1)
    }


def boundary_solutions(model: CompiledModel, compiled: CompiledChemistry) -> dict[str, list[int]]:
    """The solution number each boundary's cells inject, per package.

    One number per cell in the package, which is what mf6rtm's ChemStress takes:
    the cells themselves come from the flow package's stress period data, so
    only the list has to line up with it.
    """
    chemistry = model.project.chemistry
    assignments: dict[str, list[int]] = {}

    for package_id, solution_id in chemistry.boundary_solutions.items():
        number = compiled.number_of("solution", solution_id)
        if number == 0:
            raise ChemistryError(
                f"boundary {package_id!r} carries solution {solution_id!r}, which is not "
                "one of the model's solutions"
            )
        assignments[package_id] = [number] * model.boundary(package_id).cell_count

    return assignments


def selected_output_lines(chemistry: ChemistryModel) -> list[str]:
    """A SELECTED_OUTPUT block, as the lines mf6rtm appends to the input.

    Written as PHREEQC text rather than through an API because that is what
    mf6rtm's postfix file is: everything here is appended verbatim after the
    generated blocks.
    """
    output = chemistry.selected_output
    lines = ["SELECTED_OUTPUT", "    -reset false", "    -high_precision true"]

    if output.ph:
        lines.append("    -pH true")
    if output.pe:
        lines.append("    -pe true")

    named = (
        ("-totals", output.totals),
        ("-molalities", output.molalities),
        ("-saturation_indices", output.saturation_indices),
        ("-equilibrium_phases", output.equilibrium_phases),
        ("-kinetic_reactants", output.kinetic_reactants),
        ("-gases", output.gases),
    )
    for keyword, names in named:
        if names:
            lines.append(f"    {keyword} {' '.join(names)}")

    return lines


def initial_conditions(compiled: CompiledChemistry, block: str) -> np.ndarray | int:
    """The per-cell assemblage numbers for one block.

    Collapsed to a single int when every cell has the same one, because that is
    both what mf6rtm's examples do and a smaller thing to send to the worker.
    """
    values = compiled.assemblages[block]
    unique = np.unique(values)
    return int(unique[0]) if unique.size == 1 else values


def build_spec(model: CompiledModel) -> dict[str, Any]:
    """Everything the write worker needs, as JSON-serialisable data.

    The worker runs in its own process because PhreeqcRM keeps global state
    through SWIG and mf6rtm changes the working directory, neither of which a
    long-lived server can survive. So the boundary between them is data, not
    objects.
    """
    compiled = model.chemistry
    if compiled is None:
        raise ChemistryError("this project has no chemistry to write")

    chemistry = model.project.chemistry
    order = compiled.numbering

    def conditions(block: str) -> Any:
        values = initial_conditions(compiled, block)
        return values if isinstance(values, int) else values.tolist()

    spec: dict[str, Any] = {
        "name": model.project.meta.name,
        "database": chemistry.database.name,
        "databasePath": chemistry.database.path,
        "shape": list(model.grid.shape),
        "solutions": {
            "data": solutions_block(chemistry, order["solution"]),
            "ic": conditions("solution"),
        },
        "boundaries": boundary_solutions(model, compiled),
        "postfix": selected_output_lines(chemistry),
        "temperature": _initial_temperature(chemistry, order["solution"]),
    }

    if order["equilibrium_phases"]:
        spec["equilibriumPhases"] = {
            "data": equilibrium_block(chemistry, order["equilibrium_phases"]),
            "ic": conditions("equilibrium_phases"),
        }
    if order["exchange"]:
        spec["exchange"] = {
            "data": exchange_block(chemistry, order["exchange"]),
            "ic": conditions("exchange"),
            "equilibrateSolutions": exchange_equilibrations(
                chemistry, order["exchange"], order["solution"]
            ),
        }
    if order["surface"]:
        spec["surface"] = {
            "data": surface_block(chemistry, order["surface"]),
            "ic": conditions("surface"),
            "options": surface_options(chemistry, order["surface"]),
        }
    if order["kinetics"]:
        spec["kinetics"] = {
            "data": kinetics_block(chemistry, order["kinetics"]),
            "ic": conditions("kinetics"),
        }
    if order["gas_phase"]:
        spec["gasPhase"] = {
            "data": gas_block(chemistry, order["gas_phase"]),
            "ic": conditions("gas_phase"),
        }

    return spec


def _initial_temperature(chemistry: ChemistryModel, order: list[str]) -> list[float]:
    by_id = {item.id: item for item in chemistry.solutions}
    return [by_id[item].temperature for item in order]
