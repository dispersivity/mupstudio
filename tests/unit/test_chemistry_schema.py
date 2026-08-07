"""Chemistry schema: the references it checks, and the ones it cannot."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mupstudio.schema.chemistry import (
    CellRange,
    ChemistryModel,
    ChemZone,
    Composition,
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
from mupstudio.schema.project import Project
from mupstudio.schema.templates import starter_chemistry, starter_column


def water(name: str = "w") -> Solution:
    return Solution(id=name, concentrations={"Ca": 1e-3, "Cl": 2e-3})


def test_a_disabled_model_is_not_checked() -> None:
    """Chemistry half-built should not block saving the project.

    Editing is incremental: a composition gets a name before it gets a solution,
    and the schema has to allow that intermediate state to exist on disk.
    """
    model = ChemistryModel(
        compositions=[Composition(id="c", solution="nothing")],
    )
    assert model.enabled is False


def test_a_composition_must_name_a_solution_that_exists() -> None:
    with pytest.raises(ValidationError, match="uses solution 'missing'"):
        ChemistryModel(
            enabled=True,
            solutions=[water()],
            compositions=[Composition(id="c", solution="missing")],
        )


def test_every_assemblage_slot_is_checked() -> None:
    for slot, message in (
        ("equilibrium_phases", "equilibrium_phases 'x'"),
        ("exchange", "exchange 'x'"),
        ("surface", "surface 'x'"),
        ("kinetics", "kinetics 'x'"),
        ("gas_phase", "gas_phase 'x'"),
    ):
        with pytest.raises(ValidationError, match=message):
            ChemistryModel(
                enabled=True,
                solutions=[water()],
                compositions=[Composition(id="c", solution="w", **{slot: "x"})],
            )


def test_a_zone_must_name_a_composition_that_exists() -> None:
    with pytest.raises(ValidationError, match="uses composition 'nope'"):
        ChemistryModel(
            enabled=True,
            solutions=[water()],
            compositions=[Composition(id="c", solution="w")],
            background="c",
            zones=[
                ChemZone(
                    id="z",
                    composition="nope",
                    cells=CellRange(layers=[1], rows=[1], columns=[1]),
                )
            ],
        )


def test_a_boundary_must_carry_a_solution_that_exists() -> None:
    with pytest.raises(ValidationError, match="carries solution 'ghost'"):
        ChemistryModel(
            enabled=True,
            solutions=[water()],
            boundary_solutions={"inflow": "ghost"},
        )


def test_an_exchanger_cannot_equilibrate_with_a_missing_solution() -> None:
    with pytest.raises(ValidationError, match="equilibrates with solution 'gone'"):
        ChemistryModel(
            enabled=True,
            solutions=[water()],
            exchange=[ExchangeAssemblage(id="x", sites={"X": 0.1}, equilibrate_with="gone")],
        )


def test_a_surface_cannot_equilibrate_with_a_missing_solution() -> None:
    with pytest.raises(ValidationError, match="equilibrates with solution 'gone'"):
        ChemistryModel(
            enabled=True,
            solutions=[water()],
            surface=[
                SurfaceAssemblage(
                    id="s",
                    sites=[SurfaceSite(site="Hfo_w", moles=1e-3)],
                    equilibrate_with="gone",
                )
            ],
        )


def test_charge_balance_must_name_a_species_in_the_solution() -> None:
    with pytest.raises(ValidationError, match="balances charge on 'Na'"):
        Solution(id="w", concentrations={"Ca": 1e-3}, charge_balance="Na")


def test_moles_cannot_be_negative() -> None:
    """Zero moles means dissolution only, which is meaningful; below zero is not."""
    assert PhaseTarget(phase="Calcite", moles=0.0).moles == 0.0
    with pytest.raises(ValidationError):
        PhaseTarget(phase="Calcite", moles=-1.0)


def test_selected_output_knows_when_it_is_empty() -> None:
    assert SelectedOutput().is_empty is True
    assert SelectedOutput(totals=["Ca"]).is_empty is False
    # pH alone is not nothing, but it is not what "is_empty" tracks: the check
    # exists to catch a run that reports no chemistry worth looking at.
    assert SelectedOutput(ph=True).is_empty is True


def test_lookup_helpers_raise_for_unknown_names() -> None:
    model = ChemistryModel(
        enabled=True,
        solutions=[water()],
        compositions=[Composition(id="c", solution="w")],
        background="c",
    )
    assert model.composition("c").solution == "w"
    assert model.solution("w").id == "w"
    with pytest.raises(KeyError):
        model.composition("nope")
    with pytest.raises(KeyError):
        model.solution("nope")


def test_kinetic_parms_accept_the_m0_alias() -> None:
    """Reading a project written by hand should not need the long field name."""
    reaction = KineticReaction.model_validate({"rate": "Calcite", "m0": 4.0, "parms": [1e2, 0.6]})
    assert reaction.initial_moles == 4.0


def test_a_gas_phase_defaults_to_fixed_pressure() -> None:
    gas = GasPhaseAssemblage(id="g", partial_pressures={"CO2(g)": 0.01})
    assert gas.fixed_pressure is True


def test_kinetics_hold_their_reactions_in_order() -> None:
    assemblage = KineticAssemblage(
        id="k",
        reactions=[
            KineticReaction(rate="Calcite", parms=[1.0]),
            KineticReaction(rate="Pyrite", parms=[1.0, 2.0]),
        ],
    )
    assert [item.rate for item in assemblage.reactions] == ["Calcite", "Pyrite"]


# --- how chemistry interacts with the rest of a project ---------------------


def reactive_project(**chemistry: object) -> Project:
    """The starter column with chemistry on it, revalidated.

    Rebuilt through ``model_validate`` rather than ``model_copy``: pydantic does
    not re-run validators on a copy, so a copy would never see the cross-checks
    these tests are about. The app takes the same route, validating whatever
    arrives from the editor before it reaches disk.
    """
    project = starter_column("column", cells=10)
    edited = starter_chemistry().model_copy(update=chemistry)
    return Project.model_validate({**project.model_dump(), "chemistry": edited.model_dump()})


def test_the_starter_chemistry_is_valid_on_the_starter_column() -> None:
    project = reactive_project()
    assert project.chemistry.enabled
    assert project.chemistry.background == "sand"


def test_a_zone_outside_the_grid_is_rejected() -> None:
    with pytest.raises(ValidationError, match="refers to column 99"):
        reactive_project(
            zones=[
                ChemZone(
                    id="z",
                    composition="sand",
                    cells=CellRange(layers=[1], rows=[1], columns=[99]),
                )
            ]
        )


def test_water_cannot_be_assigned_to_a_boundary_the_project_does_not_have() -> None:
    with pytest.raises(ValidationError, match="which this project does not have"):
        reactive_project(boundary_solutions={"nosuch": "inflow"})


def test_water_cannot_be_assigned_to_a_drain() -> None:
    """A drain only removes water, so an inflow chemistry for it is a mistake."""
    from mupstudio.schema.common import ConstantSeries
    from mupstudio.schema.flow import CellRange as FlowCells
    from mupstudio.schema.flow import DrainPackage

    project = starter_column("column", cells=10)
    drained = project.flow.model_copy(
        update={
            "packages": [
                *project.flow.packages,
                DrainPackage(
                    id="ditch",
                    cells=FlowCells(layers=[1], rows=[1], columns=[5]),
                    elevation=ConstantSeries(value=0.0),
                    conductance=ConstantSeries(value=1.0),
                ),
            ]
        }
    )
    chemistry = starter_chemistry().model_copy(update={"boundary_solutions": {"ditch": "inflow"}})

    with pytest.raises(ValidationError, match="which only removes water"):
        Project.model_validate(
            {
                **project.model_dump(),
                "flow": drained.model_dump(),
                "chemistry": chemistry.model_dump(),
            }
        )


def test_compositions_need_a_background() -> None:
    with pytest.raises(ValidationError, match="needs a background composition"):
        reactive_project(background=None)


def test_a_project_without_chemistry_still_validates() -> None:
    project = starter_column("plain")
    assert project.chemistry.enabled is False
    assert project.chemistry.solutions == []


def test_equilibrium_phases_keep_their_order() -> None:
    assemblage = EquilibriumPhases(
        id="e",
        phases=[PhaseTarget(phase="Calcite"), PhaseTarget(phase="Dolomite")],
    )
    assert [target.phase for target in assemblage.phases] == ["Calcite", "Dolomite"]
