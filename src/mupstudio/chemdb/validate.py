"""Checking chemistry against the database it will be run with.

The schema can only check that a project refers to things it defines itself. It
cannot know whether ``Calcite`` is a real phase or whether a rate law wants two
parameters or five — that is in the database, and it differs between them.

Reported as a list rather than raised, because chemistry is edited incrementally
and a half-finished model should show every problem at once instead of the first
one. A dangling species is an error; something merely unusual is a warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from typing import Literal

from mupstudio.chemdb.parser import DatabaseIndex
from mupstudio.schema.chemistry import ChemistryModel

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Problem:
    """One thing wrong with the chemistry, and where to find it."""

    severity: Severity
    where: str
    message: str
    suggestion: str | None = None

    def __str__(self) -> str:
        text = f"{self.where}: {self.message}"
        return f"{text} Did you mean {self.suggestion!r}?" if self.suggestion else text


def check(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    """Every problem the database can reveal, worst first."""
    if not chemistry.enabled:
        return []

    problems: list[Problem] = []
    problems += _check_solutions(chemistry, database)
    problems += _check_phases(chemistry, database)
    problems += _check_exchange(chemistry, database)
    problems += _check_surface(chemistry, database)
    problems += _check_kinetics(chemistry, database)
    problems += _check_gases(chemistry, database)
    problems += _check_output(chemistry, database)

    return sorted(problems, key=lambda problem: problem.severity != "error")


def _missing(name: str, known: list[str], where: str, kind: str) -> Problem:
    """One unknown name, with the closest thing in the database offered.

    A typo is by far the most common cause — ``Calcte`` for ``Calcite``, ``Fe+2``
    for ``Fe(+2)`` — so the near match usually is the fix.
    """
    close = get_close_matches(name, known, n=1, cutoff=0.7)
    return Problem(
        severity="error",
        where=where,
        message=f"{kind} {name!r} is not in the database.",
        suggestion=close[0] if close else None,
    )


def _check_solutions(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    # Both the redox states and the bare elements are accepted: a database that
    # lists C(+4) also accepts C, and PHREEQC resolves it.
    known = sorted({item.name for item in database.master_species})
    problems: list[Problem] = []

    for solution in chemistry.solutions:
        where = f"solution {solution.id!r}"
        for species in solution.concentrations:
            if species not in known:
                problems.append(_missing(species, known, where, "species"))
        if solution.charge_balance and solution.charge_balance not in known:
            problems.append(_missing(solution.charge_balance, known, where, "species"))

    return problems


def _check_phases(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    known = sorted(phase.name for phase in database.phases)
    gases = {phase.name for phase in database.gases}
    problems: list[Problem] = []

    for assemblage in chemistry.equilibrium_phases:
        where = f"equilibrium phases {assemblage.id!r}"
        for target in assemblage.phases:
            if target.phase not in known:
                problems.append(_missing(target.phase, known, where, "phase"))
            elif target.phase in gases:
                # A gas in an equilibrium assemblage fixes its partial pressure,
                # which is legal but is almost never what someone means when
                # they are listing minerals.
                problems.append(
                    Problem(
                        severity="warning",
                        where=where,
                        message=(
                            f"{target.phase!r} is a gas, so listing it here fixes its "
                            "partial pressure. Use a gas phase to let it accumulate."
                        ),
                    )
                )

    return problems


def _check_exchange(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    known = sorted(set(database.exchange_species) | set(database.exchange_sites))
    problems: list[Problem] = []

    for assemblage in chemistry.exchange:
        where = f"exchange {assemblage.id!r}"
        for species in assemblage.sites:
            if species not in known:
                problems.append(_missing(species, known, where, "exchange species"))

    return problems


def _check_surface(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    known = sorted(database.surface_sites)
    problems: list[Problem] = []

    for assemblage in chemistry.surface:
        where = f"surface {assemblage.id!r}"
        for site in assemblage.sites:
            # SURFACE_MASTER_SPECIES names sites in full, underscore and all:
            # Hfo_w and Hfo_s are two distinct sites, not one site named Hfo.
            if known and site.site not in known:
                problems.append(_missing(site.site, known, where, "surface site"))
            if assemblage.edl_model != "no_edl" and not (site.specific_area and site.mass):
                problems.append(
                    Problem(
                        severity="error",
                        where=where,
                        message=(
                            f"site {site.site!r} needs a specific area and a mass, because "
                            f"the {assemblage.edl_model} double layer is calculated from them."
                        ),
                    )
                )

    return problems


def _check_kinetics(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    known = sorted(rate.name for rate in database.rates)
    problems: list[Problem] = []

    for assemblage in chemistry.kinetics:
        where = f"kinetics {assemblage.id!r}"
        for reaction in assemblage.reactions:
            rate = database.rate(reaction.rate)
            if rate is None:
                problems.append(_missing(reaction.rate, known, where, "rate law"))
                continue

            # The rate's BASIC reads PARM(1..n); giving fewer is an out-of-range
            # error deep inside PHREEQC, giving more is silently ignored.
            given, wanted = len(reaction.parms), rate.parm_count
            if given < wanted:
                problems.append(
                    Problem(
                        severity="error",
                        where=f"{where}, rate {reaction.rate!r}",
                        message=(
                            f"{wanted} parameters are used by this rate law but {given} "
                            f"{'was' if given == 1 else 'were'} given."
                        ),
                    )
                )
            elif given > wanted:
                problems.append(
                    Problem(
                        severity="warning",
                        where=f"{where}, rate {reaction.rate!r}",
                        message=(
                            f"{given} parameters were given but the rate law uses "
                            f"{wanted}; the rest are ignored."
                        ),
                    )
                )

            # A kinetic reaction with no formula has to take its stoichiometry
            # from a phase of the same name, so that phase must exist.
            if reaction.formula is None and database.phase(reaction.rate) is None:
                problems.append(
                    Problem(
                        severity="error",
                        where=f"{where}, rate {reaction.rate!r}",
                        message=(
                            "no phase of this name exists, so the reaction needs an "
                            "explicit formula to say what it dissolves."
                        ),
                    )
                )

    return problems


def _check_gases(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    known = sorted(phase.name for phase in database.gases)
    all_phases = {phase.name for phase in database.phases}
    problems: list[Problem] = []

    for assemblage in chemistry.gas_phases:
        where = f"gas phase {assemblage.id!r}"
        for gas in assemblage.partial_pressures:
            if gas in all_phases and gas not in known:
                problems.append(
                    Problem(
                        severity="error",
                        where=where,
                        message=f"{gas!r} is a mineral, not a gas. Gases are named like 'CO2(g)'.",
                    )
                )
            elif gas not in known:
                problems.append(_missing(gas, known, where, "gas"))

    return problems


def _check_output(chemistry: ChemistryModel, database: DatabaseIndex) -> list[Problem]:
    """What is asked for on the way out has to exist too.

    An unknown name here does not stop the run; PHREEQC writes an empty column,
    and the missing results are only noticed afterwards.
    """
    output = chemistry.selected_output
    if output.is_empty:
        return [
            Problem(
                severity="error",
                where="selected output",
                message="nothing is selected, so the run would produce no chemistry to look at.",
            )
        ]

    elements = sorted({item.element for item in database.master_species})
    species = sorted(database.aqueous_species)
    phases = sorted(phase.name for phase in database.phases)
    rates = sorted(rate.name for rate in database.rates)

    checks = (
        (output.totals, elements, "total"),
        (output.molalities, species, "species"),
        (output.saturation_indices, phases, "phase"),
        (output.equilibrium_phases, phases, "phase"),
        (output.kinetic_reactants, rates, "rate law"),
        (output.gases, [phase.name for phase in database.gases], "gas"),
    )

    problems: list[Problem] = []
    for requested, known, kind in checks:
        for name in requested:
            if known and name not in known:
                problem = _missing(name, known, "selected output", kind)
                problems.append(
                    Problem(
                        severity="warning",
                        where=problem.where,
                        message=f"{problem.message} It would be written as an empty column.",
                        suggestion=problem.suggestion,
                    )
                )

    return problems
