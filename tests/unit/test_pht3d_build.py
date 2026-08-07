"""Deriving a PHT3D deck from a project's chemistry.

MF6RTM has to equilibrate before it knows its components. PHT3D is told, so
this path is offline and deterministic — which makes what it decides worth
pinning: which block each name lands in, and what a cell starts with.
"""

from __future__ import annotations

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.engines.pht3d.build import (
    Pht3dBuildError,
    boundary_chemistry,
    chemistry_file,
    component_groups,
    initial_conditions,
)
from mupstudio.engines.pht3d.ordering import Group, order_components
from mupstudio.schema.chemistry import (
    CellRange,
    ChemZone,
    Composition,
    EquilibriumPhases,
    ExchangeAssemblage,
    GasPhaseAssemblage,
    KineticAssemblage,
    KineticReaction,
    PhaseTarget,
    Solution,
    SurfaceAssemblage,
    SurfaceSite,
)
from mupstudio.schema.project import Project
from mupstudio.schema.templates import starter_chemistry, starter_column


def project_with(**chemistry: object) -> Project:
    base = starter_column("column", engine="pht3d", cells=10)
    edited = starter_chemistry().model_copy(update=chemistry)
    return Project.model_validate({**base.model_dump(), "chemistry": edited.model_dump()})


def test_the_starter_chemistry_gives_the_engesgaard_components() -> None:
    groups = component_groups(starter_chemistry())

    assert groups[Group.AQUEOUS] == ["C(+4)", "Ca", "Cl", "Mg"]
    assert groups[Group.MINERAL] == ["Calcite", "Dolomite"]
    assert groups[Group.EXCHANGE] == []


def test_names_are_sorted_so_the_numbering_is_stable() -> None:
    """The numbering names the output files, so it must not drift.

    A component that changed number between runs would silently relabel every
    result: PHT3D007.UCN says nothing about what is in it.
    """
    chemistry = starter_chemistry().model_copy(
        update={
            "solutions": [
                Solution(id="a", concentrations={"Na": 1.0, "Ca": 1.0}),
                Solution(id="b", concentrations={"Cl": 1.0, "Br": 1.0}),
            ]
        }
    )

    assert component_groups(chemistry)[Group.AQUEOUS] == ["Br", "Ca", "Cl", "Na"]


def test_a_rate_on_a_listed_mineral_is_a_kinetic_mineral() -> None:
    """PHT3D reads the two from different blocks and numbers them apart."""
    chemistry = starter_chemistry().model_copy(
        update={
            "kinetics": [
                KineticAssemblage(
                    id="k",
                    reactions=[
                        KineticReaction(rate="Calcite", parms=[1.0]),
                        KineticReaction(rate="Orgc", parms=[1.0], formula="Orgc -1.0 C 1.0"),
                    ],
                )
            ]
        }
    )
    groups = component_groups(chemistry)

    assert groups[Group.KINETIC_MINERAL] == ["Calcite"]
    assert groups[Group.MOBILE_KINETIC] == ["Orgc"]
    # A mineral that reacts kinetically is not also an equilibrium phase.
    assert groups[Group.MINERAL] == ["Dolomite"]


def test_every_kind_of_assemblage_reaches_its_block() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "exchange": [ExchangeAssemblage(id="x", sites={"CaX2": 0.1, "NaX": 0.2})],
            "surface": [SurfaceAssemblage(id="s", sites=[SurfaceSite(site="Hfo_w", moles=1e-3)])],
            "gas_phases": [GasPhaseAssemblage(id="g", partial_pressures={"CO2(g)": 0.01})],
        }
    )
    groups = component_groups(chemistry)

    assert groups[Group.EXCHANGE] == ["CaX2", "NaX"]
    assert groups[Group.SURFACE] == ["Hfo_w"]
    assert groups[Group.GAS] == ["CO2(g)"]


def test_the_background_fills_every_cell() -> None:
    model = compile_project(project_with())
    components = order_components(component_groups(model.project.chemistry))

    initial = initial_conditions(model, components)

    assert np.all(initial["pH"] == 9.91)
    assert np.all(initial["Calcite"] == 1.220625e-4)
    assert np.all(initial["Cl"] == 0.0)


def test_a_zone_overrides_the_background_where_it_covers() -> None:
    base = starter_chemistry()
    model = compile_project(
        project_with(
            compositions=[
                *base.compositions,
                Composition(id="clean", solution="inflow"),
            ],
            zones=[
                ChemZone(
                    id="patch",
                    composition="clean",
                    cells=CellRange(layers=[1], rows=[1], columns=[9, 10]),
                )
            ],
        )
    )
    components = order_components(component_groups(model.project.chemistry))

    initial = initial_conditions(model, components)
    ph = initial["pH"][0, 0]

    assert list(ph[:8]) == [9.91] * 8
    assert list(ph[8:]) == [7.0, 7.0]
    # The patch has no minerals, so it starts with none rather than inheriting.
    assert list(initial["Calcite"][0, 0][8:]) == [0.0, 0.0]


def test_boundary_water_carries_its_ph_and_pe() -> None:
    assigned = boundary_chemistry(starter_chemistry())

    assert assigned["inflow"]["Cl"] == 2e-3
    assert assigned["inflow"]["pH"] == 7.0
    assert assigned["inflow"]["pe"] == 4.0


def test_saturation_indices_reach_the_chemistry_file() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "equilibrium_phases": [
                EquilibriumPhases(
                    id="calcite_sand",
                    phases=[PhaseTarget(phase="Calcite", saturation_index=0.5, moles=1e-3)],
                )
            ]
        }
    )
    components = order_components(component_groups(chemistry))

    written = chemistry_file(chemistry, components)

    assert written.minerals == [("Calcite", 0.5)]


def test_solutions_that_balance_charge_differently_are_refused() -> None:
    """PHT3D declares it once for the whole model, not per solution."""
    chemistry = starter_chemistry().model_copy(
        update={
            "solutions": [
                Solution(id="a", concentrations={"Cl": 1.0}, charge_balance="Cl"),
                Solution(id="b", concentrations={"Na": 1.0}, charge_balance="Na"),
            ]
        }
    )
    components = order_components(component_groups(chemistry))

    with pytest.raises(Pht3dBuildError, match="different components"):
        chemistry_file(chemistry, components)


def test_one_shared_charge_balance_is_written() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "solutions": [
                Solution(id="a", concentrations={"Cl": 1.0}, charge_balance="Cl"),
                Solution(id="b", concentrations={"Cl": 2.0}, charge_balance="Cl"),
            ]
        }
    )
    components = order_components(component_groups(chemistry))

    assert "Cl charge" in chemistry_file(chemistry, components).aqueous


def test_a_project_without_chemistry_cannot_be_a_pht3d_deck(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """PHT3D exists to react; a conservative tracer is the other engine's job."""
    from mupstudio.engines.pht3d.build import build_deck

    model = compile_project(starter_column("plain", engine="pht3d", cells=5))

    with pytest.raises(Pht3dBuildError, match="no chemistry defined"):
        build_deck(model, tmp_path)
