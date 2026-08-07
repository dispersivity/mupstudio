"""Chemistry to finished reactive run.

The chemistry here is the calcite and dolomite column: a calcite sand in equilibrium
with its own pore water, flushed with magnesium chloride. It is the benchmark
every reactive transport code is checked against, and the reason it is used here
rather than something simpler is that its answer is known in advance. Calcite
dissolves to exhaustion behind the front, dolomite precipitates ahead of it, and
the pH falls from that of the calcite-equilibrated water to that of the inflow.

A test that only asserted "the run finished" would pass on a model where the
chemistry was silently disconnected — which is exactly the failure this path is
prone to, since a reactive run and a tracer run produce the same file names.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.doctor import find_executable
from mupstudio.engines.mf6rtm.reactive import ReactiveWriteError, write_reactive
from mupstudio.engines.mf6rtm.results import discover_components, read_component, read_sout
from mupstudio.engines.mf6rtm.writer import write_mf6
from mupstudio.schema.chemistry import PhaseTarget, Solution
from mupstudio.schema.project import Project
from mupstudio.schema.templates import starter_chemistry, starter_column

MF6 = find_executable("mf6")
MF6RTM = find_executable("mf6rtm")

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.slow,
    pytest.mark.skipif(
        MF6 is None or MF6RTM is None,
        reason="mf6 and mf6rtm are both needed; run: mupstudio get-engines",
    ),
]


def calcite_column(**chemistry: object) -> Project:
    """The benchmark column, small and short enough to run in a few seconds."""
    base = starter_column("calcite column", cells=50, length=0.5, perlen=0.24, nstp=24)
    edited = starter_chemistry().model_copy(update=chemistry) if chemistry else starter_chemistry()
    return Project.model_validate({**base.model_dump(), "chemistry": edited.model_dump()})


def write_everything(project: Project, workdir: Path):  # type: ignore[no-untyped-def]
    """Both halves of the write: the tracer model, then chemistry on top."""
    model = compile_project(project)
    manifest = write_mf6(model, workdir)
    return write_reactive(
        model,
        workdir,
        flow_name=manifest.flow_name,
        transport_name=manifest.transport_name,
    )


def run(workdir: Path) -> subprocess.CompletedProcess[str]:
    """Run mf6rtm, with the solver library where it expects to find it."""
    assert MF6 is not None and MF6RTM is not None
    for library in MF6.parent.glob("libmf6*"):
        shutil.copyfile(library, workdir / library.name)

    return subprocess.run(
        [str(MF6RTM)],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=900,
    )


@pytest.fixture(scope="module")
def finished(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One run, shared: equilibration and the run itself cost seconds each."""
    workdir = tmp_path_factory.mktemp("reactive")
    written = write_everything(calcite_column(), workdir)
    assert written.components, "equilibration produced no components"

    result = run(workdir)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    return workdir


def test_equilibration_finds_the_components_the_chemistry_implies(tmp_path: Path) -> None:
    """Water, charge, and one per element the solutions contain.

    The component list is not something we choose: PhreeqcRM derives it while
    equilibrating, and it decides how many transport models the run has.
    """
    written = write_everything(calcite_column(), tmp_path)

    assert set(written.components) >= {"H", "O", "Charge", "C", "Ca", "Cl", "Mg"}
    assert written.component_count == len(written.components)
    assert "components" in written.describe()


def test_the_written_model_has_one_transport_model_per_component(tmp_path: Path) -> None:
    written = write_everything(calcite_column(), tmp_path)

    names = "\n".join(written.files)
    for component in written.components:
        assert f"{component.lower()}." in names.lower(), f"no files for component {component}"


def test_the_database_travels_with_the_model(tmp_path: Path) -> None:
    """A run directory that carries its own database still reproduces later."""
    write_everything(calcite_column(), tmp_path)
    assert (tmp_path / "phreeqc.dat").is_file()


def test_a_species_the_database_does_not_have_fails_with_phreeqcs_words(tmp_path: Path) -> None:
    """The PHREEQC message is the useful part, so it must reach the caller."""
    broken = calcite_column(
        solutions=[
            Solution(id="background", concentrations={"Unobtainium": 1e-3}),
            Solution(id="inflow", concentrations={"Cl": 1e-3}),
        ]
    )

    with pytest.raises(ReactiveWriteError) as caught:
        write_everything(broken, tmp_path)

    assert "Unobtainium" in f"{caught.value}{caught.value.output}"


def test_the_run_writes_one_concentration_file_per_component(finished: Path) -> None:
    components = discover_components(finished)
    assert set(components) >= {"C", "Ca", "Cl", "Mg"}


def test_chloride_behaves_conservatively(finished: Path) -> None:
    """Chloride does not react, so it is the check that transport itself is right.

    It should sweep in from the inlet and reach the injected concentration
    behind the front, which is what makes it the reference the reacting species
    are read against.
    """
    times, values = read_component(finished, "Cl")

    # Shaped (ntimes, nlay, cells in a layer), which for a column is one row.
    assert len(times) == 24
    assert values.shape == (24, 1, 50)

    # Straight off the UCN, so still in the mol/m3 MODFLOW transported.
    inlet = values[-1, 0, 0]
    assert inlet == pytest.approx(2.0, rel=0.05)
    # The front has not reached the far end in one pore volume.
    assert values[-1, 0, -1] < inlet


def test_collected_concentrations_are_in_moles_per_litre(finished: Path, tmp_path: Path) -> None:
    """The 1000x that separates what MODFLOW moved from what PHREEQC computed.

    mf6rtm transports mol/m3 because that is what a mass balance in metres
    wants, while the chemistry either side of it is in mol/L. Collecting without
    converting would show chloride at 2 mol/L instead of 2 mmol/L, which reads
    as seawater rather than as the dilute solution it is.
    """
    from mupstudio.results.store import collect_mf6rtm_run

    catalog = collect_mf6rtm_run(finished, tmp_path, run_id="units")

    chloride = next(entry for entry in catalog.components if entry["name"] == "Cl")
    assert chloride["unit"] == "mol/L"
    assert float(chloride["vmax"]) == pytest.approx(2e-3, rel=0.05)

    # And it agrees with what PHREEQC itself reported for the same cells.
    table = read_sout(finished)
    assert table is not None
    last = table[table["time_d"] == table["time_d"].max()]
    assert last["Cl(mol/kgw)"].max() == pytest.approx(float(chloride["vmax"]), rel=0.05)


def test_calcite_dissolves_to_exhaustion_behind_the_front(finished: Path) -> None:
    table = read_sout(finished)
    assert table is not None

    last = table[table["time_d"] == table["time_d"].max()]
    calcite = last["Calcite"].to_numpy()

    # Flushed by magnesium chloride, the first cells lose all their calcite.
    assert calcite[0] == pytest.approx(0.0, abs=1e-9)
    assert np.all(calcite >= -1e-12), "calcite went negative, which is not a state"


def test_dolomite_precipitates_where_calcite_dissolved(finished: Path) -> None:
    """The second front, and the reason this benchmark is worth running.

    Dolomite starts at zero moles, so any amount at the end can only have come
    from magnesium meeting the carbonate that calcite released.
    """
    table = read_sout(finished)
    assert table is not None

    last = table[table["time_d"] == table["time_d"].max()]
    dolomite = last["Dolomite"].to_numpy()

    assert dolomite.max() > 1e-6, "no dolomite formed, so the reaction did not happen"
    # It forms downstream of the flushed cells, not at the inlet.
    assert dolomite[0] == pytest.approx(0.0, abs=1e-12)
    assert int(np.argmax(dolomite)) > 0


def test_the_ph_falls_from_the_pore_water_to_the_inflow(finished: Path) -> None:
    table = read_sout(finished)
    assert table is not None

    last = table[table["time_d"] == table["time_d"].max()]
    ph = last["pH"].to_numpy()

    assert ph[0] == pytest.approx(7.0, abs=0.3), "the inlet did not take the inflow's pH"
    assert ph[-1] > 9.0, "the far end should still hold the calcite-equilibrated water"


def test_magnesium_is_taken_up_as_dolomite_forms(finished: Path) -> None:
    """Mass has to go somewhere: dissolved Mg falls where dolomite appears."""
    table = read_sout(finished)
    assert table is not None

    last = table[table["time_d"] == table["time_d"].max()]
    magnesium = last["Mg(mol/kgw)"].to_numpy()
    dolomite = last["Dolomite"].to_numpy()

    where_dolomite = dolomite > dolomite.max() * 0.5
    assert magnesium[where_dolomite].mean() < magnesium[0]


def test_only_the_selected_output_is_reported(finished: Path) -> None:
    """What is not selected is not written, and the run has to be repeated."""
    table = read_sout(finished)
    assert table is not None

    assert {"Calcite", "Dolomite", "pH"} <= set(table.columns)
    assert not any(column.startswith("Gypsum") for column in table.columns)


def test_rewriting_over_a_finished_run_works(finished: Path, tmp_path: Path) -> None:
    """The database is already in the directory the second time round.

    mf6rtm refuses to copy a file over itself, so a rewrite has to hand it a
    different source. Re-running the write is what editing chemistry and
    pressing Run again does.
    """
    for path in finished.iterdir():
        if path.is_file():
            shutil.copyfile(path, tmp_path / path.name)

    written = write_everything(calcite_column(), tmp_path)
    assert written.components


def test_a_zoned_column_equilibrates_each_zone_separately(tmp_path: Path) -> None:
    """Two compositions in one column, which is what zoning is for."""
    from mupstudio.schema.chemistry import CellRange, ChemZone, Composition, EquilibriumPhases

    base = starter_chemistry()
    zoned = calcite_column(
        equilibrium_phases=[
            *base.equilibrium_phases,
            EquilibriumPhases(id="gypsum_lens", phases=[PhaseTarget(phase="Gypsum", moles=1e-3)]),
        ],
        compositions=[
            *base.compositions,
            Composition(id="lens", solution="background", equilibrium_phases="gypsum_lens"),
        ],
        zones=[
            ChemZone(
                id="lens",
                composition="lens",
                cells=CellRange(layers=[1], rows=[1], columns=list(range(20, 31))),
            )
        ],
    )

    written = write_everything(zoned, tmp_path)
    # Gypsum brings sulphur into the model, so the component list grows.
    assert "S" in written.components
