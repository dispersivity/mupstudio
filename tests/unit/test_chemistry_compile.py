"""Compiling chemistry to per-cell numbers, and on into mf6rtm's block shapes.

The bridge is tested without mf6rtm installed being relevant: it builds plain
dicts, and those dicts are the contract with the write worker.
"""

from __future__ import annotations

import numpy as np
import pytest

from mupstudio.compile.compiler import CompiledChemistry, compile_project
from mupstudio.engines.mf6rtm import chemistry as bridge
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
    SelectedOutput,
    Solution,
    SurfaceAssemblage,
    SurfaceSite,
)
from mupstudio.schema.project import Project
from mupstudio.schema.templates import starter_chemistry, starter_column


def project_with(chemistry: object, cells: int = 10) -> Project:
    base = starter_column("column", cells=cells)
    return Project.model_validate(
        {**base.model_dump(), "chemistry": chemistry.model_dump()}  # type: ignore[attr-defined]
    )


def test_chemistry_is_not_compiled_when_it_is_off() -> None:
    assert compile_project(starter_column("plain")).chemistry is None


def test_the_background_fills_every_cell() -> None:
    model = compile_project(project_with(starter_chemistry()))
    compiled = model.chemistry
    assert compiled is not None

    assert compiled.assemblages["solution"].shape == (1, 1, 10)
    assert np.all(compiled.assemblages["solution"] == 1)
    assert np.all(compiled.assemblages["equilibrium_phases"] == 1)
    # Nothing defines exchange, so no cell has one.
    assert np.all(compiled.assemblages["exchange"] == 0)


def test_a_zone_overwrites_the_background_where_it_covers() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "compositions": [
                *starter_chemistry().compositions,
                Composition(id="clean", solution="inflow"),
            ],
            "zones": [
                ChemZone(
                    id="patch",
                    composition="clean",
                    cells=CellRange(layers=[1], rows=[1], columns=[8, 9, 10]),
                )
            ],
        }
    )
    compiled = compile_project(project_with(chemistry)).chemistry
    assert compiled is not None

    solution = compiled.assemblages["solution"][0, 0]
    assert list(solution[:7]) == [1] * 7
    assert list(solution[7:]) == [2, 2, 2]
    # The patch has no minerals, so it clears them rather than inheriting them.
    assert list(compiled.assemblages["equilibrium_phases"][0, 0][7:]) == [0, 0, 0]


def test_later_zones_win_where_they_overlap() -> None:
    """Painting order is what a zone list means everywhere else in the app."""
    base = starter_chemistry()
    chemistry = base.model_copy(
        update={
            "compositions": [
                *base.compositions,
                Composition(id="a", solution="inflow"),
                Composition(id="b", solution="background"),
            ],
            "zones": [
                ChemZone(
                    id="first",
                    composition="a",
                    cells=CellRange(layers=[1], rows=[1], columns=[1, 2, 3, 4, 5]),
                ),
                ChemZone(
                    id="second",
                    composition="b",
                    cells=CellRange(layers=[1], rows=[1], columns=[4, 5, 6]),
                ),
            ],
        }
    )
    compiled = compile_project(project_with(chemistry)).chemistry
    assert compiled is not None
    assert list(compiled.assemblages["solution"][0, 0]) == [2, 2, 2, 1, 1, 1, 1, 1, 1, 1]


def test_numbering_follows_the_order_the_assemblages_are_listed_in() -> None:
    compiled = compile_project(project_with(starter_chemistry())).chemistry
    assert compiled is not None
    assert compiled.number_of("solution", "background") == 1
    assert compiled.number_of("solution", "inflow") == 2
    assert compiled.number_of("solution", "nothing") == 0


# --- the mf6rtm block shapes -------------------------------------------------


def test_solutions_are_transposed_into_species_rows() -> None:
    chemistry = starter_chemistry()
    block = bridge.solutions_block(chemistry, ["background", "inflow"])

    assert block["pH"] == [9.91, 7.0]
    assert block["Ca"] == [1.23e-4, 0.0]
    assert block["Mg"] == [0.0, 1e-3]


def test_a_species_missing_from_one_solution_becomes_zero_there() -> None:
    """The columns have to line up, so absence is a value and not a gap."""
    chemistry = starter_chemistry().model_copy(
        update={
            "solutions": [
                Solution(id="a", concentrations={"Ca": 1e-3, "Na": 5e-3}),
                Solution(id="b", concentrations={"Ca": 2e-3}),
            ]
        }
    )
    block = bridge.solutions_block(chemistry, ["a", "b"])
    assert block["Na"] == [5e-3, 0.0]


def test_solutions_without_any_solution_is_an_error() -> None:
    with pytest.raises(bridge.ChemistryError, match="at least one solution"):
        bridge.solutions_block(starter_chemistry(), [])


def test_equilibrium_phases_carry_their_index_and_moles() -> None:
    block = bridge.equilibrium_block(starter_chemistry(), ["calcite_sand"])
    assert block[1]["Calcite"] == {"si": 0.0, "m0": 1.220625e-4}
    assert block[1]["Dolomite"]["m0"] == 0.0


def test_exchange_sites_become_m0_entries() -> None:
    chemistry = starter_chemistry().model_copy(
        update={"exchange": [ExchangeAssemblage(id="x", sites={"X": 0.087})]}
    )
    assert bridge.exchange_block(chemistry, ["x"]) == {1: {"X": {"m0": 0.087}}}


def test_an_exchanger_points_at_the_solution_it_equilibrates_with() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "exchange": [
                ExchangeAssemblage(id="x", sites={"X": 0.1}, equilibrate_with="inflow"),
                ExchangeAssemblage(id="y", sites={"X": 0.1}),
            ]
        }
    )
    assert bridge.exchange_equilibrations(chemistry, ["x", "y"], ["background", "inflow"]) == [2, 0]


def test_surfaces_that_disagree_about_the_double_layer_are_refused() -> None:
    """mf6rtm applies one option to every surface, so a mix cannot be written."""
    chemistry = starter_chemistry().model_copy(
        update={
            "surface": [
                SurfaceAssemblage(
                    id="a",
                    edl_model="no_edl",
                    sites=[SurfaceSite(site="Hfo_w", moles=1e-3)],
                ),
                SurfaceAssemblage(
                    id="b",
                    edl_model="donnan",
                    sites=[SurfaceSite(site="Hfo_w", moles=1e-3)],
                ),
            ]
        }
    )
    with pytest.raises(bridge.ChemistryError, match="different double layer models"):
        bridge.surface_options(chemistry, ["a", "b"])


def test_the_diffuse_layer_is_phreeqcs_default_and_needs_no_keyword() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "surface": [
                SurfaceAssemblage(
                    id="a",
                    edl_model="diffuse_layer",
                    sites=[SurfaceSite(site="Hfo_w", moles=1e-3, specific_area=600, mass=1)],
                )
            ]
        }
    )
    assert bridge.surface_options(chemistry, ["a"]) == []
    assert bridge.surface_options(chemistry, []) == ["no_edl"]


def test_kinetics_keep_their_parameters_positional() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "kinetics": [
                KineticAssemblage(
                    id="k",
                    reactions=[
                        KineticReaction(rate="Calcite", m0=4.0, parms=[1e2, 0.6]),
                        KineticReaction(rate="Organic", parms=[9.5e-10], formula="Orgc -1.0 C 1.0"),
                    ],
                )
            ]
        }
    )
    block = bridge.kinetics_block(chemistry, ["k"])
    assert block[1]["Calcite"] == {"m0": 4.0, "parms": [1e2, 0.6]}
    assert block[1]["Organic"]["formula"] == "Orgc -1.0 C 1.0"
    # No formula given means take the stoichiometry from the phase of that name.
    assert "formula" not in block[1]["Calcite"]


def test_gas_phases_carry_their_partial_pressures() -> None:
    chemistry = starter_chemistry().model_copy(
        update={"gas_phases": [GasPhaseAssemblage(id="g", partial_pressures={"CO2(g)": 0.03})]}
    )
    assert bridge.gas_block(chemistry, ["g"]) == {1: {"CO2(g)": 0.03}}


def test_a_boundary_gets_one_solution_number_per_cell() -> None:
    model = compile_project(project_with(starter_chemistry()))
    assert model.chemistry is not None
    assert bridge.boundary_solutions(model, model.chemistry) == {"inflow": [2]}


def test_selected_output_is_written_as_phreeqc_text() -> None:
    lines = bridge.selected_output_lines(starter_chemistry())
    assert lines[0] == "SELECTED_OUTPUT"
    assert any(line.strip() == "-totals Ca Cl Mg C" for line in lines)
    assert any(line.strip() == "-equilibrium_phases Calcite Dolomite" for line in lines)


def test_uniform_conditions_collapse_to_one_number() -> None:
    """Smaller to send, and it is what mf6rtm's own examples pass."""
    compiled = compile_project(project_with(starter_chemistry())).chemistry
    assert compiled is not None
    assert bridge.initial_conditions(compiled, "solution") == 1


def test_varying_conditions_stay_an_array() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "compositions": [
                *starter_chemistry().compositions,
                Composition(id="other", solution="inflow"),
            ],
            "zones": [
                ChemZone(
                    id="z",
                    composition="other",
                    cells=CellRange(layers=[1], rows=[1], columns=[5]),
                )
            ],
        }
    )
    compiled = compile_project(project_with(chemistry)).chemistry
    assert compiled is not None
    values = bridge.initial_conditions(compiled, "solution")
    assert isinstance(values, np.ndarray)
    assert values.shape == (1, 1, 10)


def test_the_whole_spec_round_trips_as_json() -> None:
    """The spec crosses a process boundary, so it has to survive being JSON."""
    import json

    model = compile_project(project_with(starter_chemistry()))
    spec = bridge.build_spec(model)
    restored = json.loads(json.dumps(spec))

    assert restored["solutions"]["ic"] == 1
    assert restored["boundaries"] == {"inflow": [2]}
    assert restored["temperature"] == [25.0, 25.0]
    assert "equilibriumPhases" in restored
    # Nothing defines these, so they are absent rather than empty.
    assert "exchange" not in restored
    assert "gasPhase" not in restored


def test_building_a_spec_without_chemistry_is_an_error() -> None:
    model = compile_project(starter_column("plain"))
    with pytest.raises(bridge.ChemistryError, match="no chemistry to write"):
        bridge.build_spec(model)


def test_the_block_list_matches_what_a_composition_can_name() -> None:
    """One list drives compiling, numbering and writing; drift would be silent."""
    fields = set(Composition.model_fields) - {"id", "label", "colour"}
    assert set(CompiledChemistry.BLOCKS) == fields


def test_an_empty_selected_output_still_writes_a_block() -> None:
    """Validation rejects it; the writer should not also crash on it."""
    chemistry = starter_chemistry().model_copy(update={"selected_output": SelectedOutput()})
    assert bridge.selected_output_lines(chemistry)[0] == "SELECTED_OUTPUT"


def test_equilibrium_phases_with_no_minerals_is_allowed() -> None:
    chemistry = starter_chemistry().model_copy(
        update={"equilibrium_phases": [EquilibriumPhases(id="calcite_sand")]}
    )
    assert bridge.equilibrium_block(chemistry, ["calcite_sand"]) == {1: {}}


def test_phases_keep_the_order_they_were_listed_in() -> None:
    chemistry = starter_chemistry().model_copy(
        update={
            "equilibrium_phases": [
                EquilibriumPhases(
                    id="calcite_sand",
                    phases=[
                        PhaseTarget(phase="Gypsum"),
                        PhaseTarget(phase="Calcite"),
                    ],
                )
            ]
        }
    )
    block = bridge.equilibrium_block(chemistry, ["calcite_sand"])
    assert list(block[1]) == ["Gypsum", "Calcite"]
