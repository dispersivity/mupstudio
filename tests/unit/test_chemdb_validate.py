"""Checking chemistry against a real database.

Run against the bundled phreeqc.dat rather than a stub, because the point of
these checks is that they agree with what PHREEQC will accept, and a stub would
only prove the code agrees with itself.
"""

from __future__ import annotations

import pytest

from mupstudio.chemdb import cache
from mupstudio.chemdb.parser import DatabaseIndex
from mupstudio.chemdb.validate import check
from mupstudio.schema.chemistry import (
    ChemistryModel,
    EquilibriumPhases,
    ExchangeAssemblage,
    GasPhaseAssemblage,
    KineticAssemblage,
    KineticReaction,
    PhaseTarget,
    SelectedOutput,
    Solution,
    SurfaceAssemblage,
    SurfaceSite,
)
from mupstudio.schema.templates import starter_chemistry


@pytest.fixture(scope="module")
def phreeqc() -> DatabaseIndex:
    return cache.load_by_name("phreeqc.dat")


@pytest.fixture(scope="module")
def pht3d() -> DatabaseIndex:
    return cache.load_by_name("pht3d_datab.dat")


def errors(problems: list) -> list[str]:  # type: ignore[type-arg]
    return [str(problem) for problem in problems if problem.severity == "error"]


def warnings(problems: list) -> list[str]:  # type: ignore[type-arg]
    return [str(problem) for problem in problems if problem.severity == "warning"]


def model(**fields: object) -> ChemistryModel:
    """Chemistry that passes on its own, so a test only adds what it is about."""
    base: dict[str, object] = {
        "enabled": True,
        "solutions": [Solution(id="w", concentrations={"Ca": 1e-3})],
        "selected_output": SelectedOutput(totals=["Ca"]),
    }
    return ChemistryModel(**{**base, **fields})  # type: ignore[arg-type]


def test_the_starter_chemistry_is_clean(phreeqc: DatabaseIndex) -> None:
    """The template a new project starts from must not open with complaints."""
    assert check(starter_chemistry(), phreeqc) == []


def test_disabled_chemistry_is_not_checked(phreeqc: DatabaseIndex) -> None:
    assert check(model(enabled=False, solutions=[Solution(id="w")]), phreeqc) == []


def test_an_unknown_species_is_an_error(phreeqc: DatabaseIndex) -> None:
    problems = check(model(solutions=[Solution(id="w", concentrations={"Nonsuch": 1.0})]), phreeqc)
    assert any("'Nonsuch' is not in the database" in message for message in errors(problems))


def test_a_near_miss_gets_a_suggestion(phreeqc: DatabaseIndex) -> None:
    """A typo is the usual cause, so the closest real name is offered."""
    problems = check(model(solutions=[Solution(id="w", concentrations={"Calcum": 1.0})]), phreeqc)
    assert any(
        "Did you mean 'Calcium'" in message or "Ca" in message for message in errors(problems)
    )


def test_redox_states_are_accepted(phreeqc: DatabaseIndex) -> None:
    chemistry = model(solutions=[Solution(id="w", concentrations={"C(+4)": 1e-3, "Fe(+2)": 1e-6})])
    assert errors(check(chemistry, phreeqc)) == []


def test_an_unknown_phase_is_an_error(phreeqc: DatabaseIndex) -> None:
    chemistry = model(
        equilibrium_phases=[EquilibriumPhases(id="e", phases=[PhaseTarget(phase="Calcte")])]
    )
    problems = errors(check(chemistry, phreeqc))
    assert any("'Calcte' is not in the database" in message for message in problems)
    assert any("Calcite" in message for message in problems)


def test_a_gas_in_an_equilibrium_assemblage_warns(phreeqc: DatabaseIndex) -> None:
    """Legal PHREEQC, but almost never what someone listing minerals meant."""
    chemistry = model(
        equilibrium_phases=[EquilibriumPhases(id="e", phases=[PhaseTarget(phase="CO2(g)")])]
    )
    problems = check(chemistry, phreeqc)
    assert errors(problems) == []
    assert any("fixes its partial pressure" in message for message in warnings(problems))


def test_a_mineral_named_as_a_gas_is_an_error(phreeqc: DatabaseIndex) -> None:
    chemistry = model(gas_phases=[GasPhaseAssemblage(id="g", partial_pressures={"Calcite": 0.1})])
    assert any(
        "is a mineral, not a gas" in message for message in errors(check(chemistry, phreeqc))
    )


def test_a_real_gas_passes(phreeqc: DatabaseIndex) -> None:
    chemistry = model(gas_phases=[GasPhaseAssemblage(id="g", partial_pressures={"CO2(g)": 0.01})])
    assert errors(check(chemistry, phreeqc)) == []


def test_an_unknown_exchange_species_is_an_error(phreeqc: DatabaseIndex) -> None:
    chemistry = model(exchange=[ExchangeAssemblage(id="x", sites={"Zz": 0.1})])
    assert any("exchange species 'Zz'" in message for message in errors(check(chemistry, phreeqc)))


def test_a_real_exchange_site_passes(phreeqc: DatabaseIndex) -> None:
    chemistry = model(exchange=[ExchangeAssemblage(id="x", sites={"X": 0.1})])
    assert errors(check(chemistry, phreeqc)) == []


def test_a_double_layer_needs_an_area_and_a_mass(phreeqc: DatabaseIndex) -> None:
    """PHREEQC computes the layer from them, so leaving them out fails deep in."""
    chemistry = model(
        surface=[
            SurfaceAssemblage(
                id="s",
                edl_model="diffuse_layer",
                sites=[SurfaceSite(site="Hfo_w", moles=1e-3)],
            )
        ]
    )
    problems = errors(check(chemistry, phreeqc))
    assert any("needs a specific area and a mass" in message for message in problems)


def test_a_surface_without_a_double_layer_does_not_need_them(phreeqc: DatabaseIndex) -> None:
    chemistry = model(
        surface=[SurfaceAssemblage(id="s", sites=[SurfaceSite(site="Hfo_w", moles=1e-3)])]
    )
    assert errors(check(chemistry, phreeqc)) == []


def test_too_few_rate_parameters_is_an_error(pht3d: DatabaseIndex) -> None:
    """A rate law reading PARM(2) with one parameter given fails inside PHREEQC."""
    rate = next(item for item in pht3d.rates if item.parm_count >= 2)
    chemistry = model(
        kinetics=[
            KineticAssemblage(
                id="k", reactions=[KineticReaction(rate=rate.name, parms=[1.0], formula="x")]
            )
        ]
    )
    problems = errors(check(chemistry, pht3d))
    assert any(f"{rate.parm_count} parameters are used" in message for message in problems)


def test_too_many_rate_parameters_only_warns(pht3d: DatabaseIndex) -> None:
    rate = next(item for item in pht3d.rates if item.parm_count >= 1)
    chemistry = model(
        kinetics=[
            KineticAssemblage(
                id="k",
                reactions=[
                    KineticReaction(
                        rate=rate.name, parms=[1.0] * (rate.parm_count + 3), formula="x"
                    )
                ],
            )
        ]
    )
    problems = check(chemistry, pht3d)
    assert errors(problems) == []
    assert any("the rest are ignored" in message for message in warnings(problems))


def test_a_kinetic_reaction_with_no_phase_needs_a_formula(pht3d: DatabaseIndex) -> None:
    """Without a phase of the same name there is nothing to take stoichiometry from."""
    rate = next(
        item for item in pht3d.rates if pht3d.phase(item.name) is None and item.parm_count == 0
    )
    chemistry = model(
        kinetics=[KineticAssemblage(id="k", reactions=[KineticReaction(rate=rate.name)])]
    )
    problems = errors(check(chemistry, pht3d))
    assert any("needs an explicit formula" in message for message in problems)


def test_a_kinetic_mineral_needs_no_formula(pht3d: DatabaseIndex) -> None:
    name = pht3d.kinetic_minerals[0]
    rate = pht3d.rate(name)
    assert rate is not None
    chemistry = model(
        kinetics=[
            KineticAssemblage(
                id="k", reactions=[KineticReaction(rate=name, parms=[1.0] * rate.parm_count)]
            )
        ]
    )
    assert errors(check(chemistry, pht3d)) == []


def test_an_unknown_rate_law_is_an_error(phreeqc: DatabaseIndex) -> None:
    chemistry = model(kinetics=[KineticAssemblage(id="k", reactions=[KineticReaction(rate="Zzz")])])
    assert any("rate law 'Zzz'" in message for message in errors(check(chemistry, phreeqc)))


def test_empty_selected_output_is_an_error(phreeqc: DatabaseIndex) -> None:
    """A run reporting nothing has to be repeated to learn anything from it."""
    chemistry = model(selected_output=SelectedOutput())
    assert any("nothing is selected" in message for message in errors(check(chemistry, phreeqc)))


def test_an_unknown_output_name_only_warns(phreeqc: DatabaseIndex) -> None:
    """It does not stop the run; it writes an empty column nobody notices."""
    chemistry = model(selected_output=SelectedOutput(totals=["Ca", "Qq"]))
    problems = check(chemistry, phreeqc)
    assert errors(problems) == []
    assert any("empty column" in message for message in warnings(problems))


def test_errors_are_reported_before_warnings(phreeqc: DatabaseIndex) -> None:
    chemistry = model(
        solutions=[Solution(id="w", concentrations={"Nope": 1.0})],
        selected_output=SelectedOutput(totals=["Alsonope"]),
    )
    severities = [problem.severity for problem in check(chemistry, phreeqc)]
    assert severities == sorted(severities, key=lambda item: item != "error")
