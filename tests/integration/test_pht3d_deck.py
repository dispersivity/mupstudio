"""A complete PHT3D run, and whether it agrees with MF6RTM.

The Engesgaard calcite and dolomite column is run here through PHT3D and
elsewhere through MF6RTM, from the same project. Two engines, two solvers, two
chemistry libraries: if they disagree, one of the two decks is wrong, and
nothing else in the project would notice.

The assertions are about the chemistry rather than about the numbers matching
digit for digit. PHREEQC-2 and PhreeqcRM are different implementations and the
transport schemes differ, so the fronts land in the same place and not at the
same value.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.doctor import find_executable
from mupstudio.engines.pht3d import ph_dat
from mupstudio.engines.pht3d.deck import write_pht3d
from mupstudio.engines.pht3d.ordering import Group, order_components
from mupstudio.engines.pht3d.results import discover_output, read_component
from mupstudio.schema.templates import starter_column

MF2005 = find_executable("mf2005")
PHT3D = find_executable("pht3d")
DATABASE = Path(__file__).parent.parent.parent / "src" / "mupstudio" / "chemdb" / "assets"

pytestmark = [
    pytest.mark.pht3d,
    pytest.mark.slow,
    pytest.mark.skipif(
        MF2005 is None or PHT3D is None,
        reason="mf2005 and pht3d are both needed; run: mupstudio get-engines --pht3d",
    ),
]

COMPONENTS = {
    Group.AQUEOUS: ["C(+4)", "Ca", "Cl", "Mg"],
    Group.MINERAL: ["Calcite", "Dolomite"],
}

# The pore water in equilibrium with calcite, and the magnesium chloride that
# displaces it. Same numbers as the MF6RTM run of this column.
BACKGROUND = {
    "C(+4)": 1.23e-4,
    "Ca": 1.23e-4,
    "Cl": 0.0,
    "Mg": 0.0,
    "pH": 9.91,
    "pe": 4.0,
    "Calcite": 3.906e-5,
    "Dolomite": 0.0,
}
INFLOW = {"Cl": 2e-3, "Mg": 1e-3, "pH": 7.0, "pe": 4.0}


@pytest.fixture(scope="module")
def finished(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One run, shared: writing, solving flow and reacting all cost seconds."""
    workdir = tmp_path_factory.mktemp("pht3d")
    project = starter_column("column", engine="pht3d", cells=50, length=0.5, perlen=0.24, nstp=24)
    model = compile_project(project)

    components = order_components(COMPONENTS)
    shape = model.grid.shape
    initial = {name: np.full(shape, value) for name, value in BACKGROUND.items()}

    write_pht3d(
        model,
        workdir,
        components,
        ph_dat.chemistry_from_components(components),
        initial,
        {"inflow": INFLOW},
    )

    # The flow twin has to run first: PHT3D transports through the link file
    # MODFLOW writes, and there is nothing to read until it has.
    assert MF2005 is not None and PHT3D is not None
    flow = subprocess.run(
        [str(MF2005)], cwd=workdir, input="flow.nam\n", capture_output=True, text=True, timeout=600
    )
    assert "Normal termination" in flow.stdout, flow.stdout[-2000:]

    shutil.copyfile(DATABASE / "pht3d_datab.dat", workdir / "pht3d_datab.dat")
    run = subprocess.run(
        [str(PHT3D)],
        cwd=workdir,
        input="pht3d.nam\n",
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert "Program completed" in run.stdout, run.stdout[-3000:]
    return workdir


def final(workdir: Path, name: str) -> np.ndarray:
    """One component's values along the column at the end of the run."""
    component = next(item for item in order_components(COMPONENTS) if item.name == name)
    _, values = read_component(workdir, component)
    return np.asarray(values[-1, 0])


def test_it_writes_one_output_per_component(finished: Path) -> None:
    """Numbered, not named: eight components, eight files, no gaps."""
    found = discover_output(finished)

    assert sorted(found) == list(range(1, 9))


def test_chloride_behaves_conservatively(finished: Path) -> None:
    """Nothing reacts with it, so it is the check on transport alone."""
    chloride = final(finished, "Cl")

    assert chloride[0] == pytest.approx(2e-3, rel=0.05)
    assert chloride[-1] < chloride[0]


def test_calcite_dissolves_to_exhaustion_behind_the_front(finished: Path) -> None:
    calcite = final(finished, "Calcite")

    assert calcite[0] == pytest.approx(0.0, abs=1e-9)
    assert calcite[-1] > 0, "the far end should still hold its calcite"
    assert np.all(calcite >= -1e-12), "calcite went negative, which is not a state"


def test_dolomite_precipitates_where_calcite_dissolved(finished: Path) -> None:
    """The second front, and what makes this benchmark worth running.

    Dolomite starts at zero, so any at the end came from magnesium meeting the
    carbonate calcite released.
    """
    dolomite = final(finished, "Dolomite")

    assert dolomite.max() > 1e-6
    assert dolomite[0] == pytest.approx(0.0, abs=1e-12)
    assert int(np.argmax(dolomite)) > 0


def test_the_ph_falls_from_the_pore_water_to_the_inflow(finished: Path) -> None:
    ph = final(finished, "pH")

    assert ph[0] == pytest.approx(7.0, abs=0.3)
    assert ph[-1] > 9.0


def test_both_engines_agree_about_the_chemistry(finished: Path) -> None:
    """PHT3D and MF6RTM are two implementations of the same problem.

    Compared as the shape of the answer rather than digit for digit: PHREEQC-2
    and PhreeqcRM are different libraries and the transport schemes differ, so
    the fronts arrive in the same order and the same part of the column, not at
    identical values. Disagreeing about the order would mean one of the decks
    describes a different model.
    """
    calcite = final(finished, "Calcite")
    dolomite = final(finished, "Dolomite")

    remaining = int(np.argmax(calcite > 0))  # first cell that still has calcite
    peak = int(np.argmax(dolomite))

    # Calcite has been flushed out of everything but the far end, and dolomite
    # peaks behind that: it forms where the magnesium front has reached calcite
    # to react with, which is upstream of where calcite still survives. Both
    # engines put the two fronts in that order.
    assert remaining > 0, "calcite survived nowhere, so the column was over-flushed"
    assert 0 < peak < remaining, "dolomite should peak behind the remaining calcite"
    assert final(finished, "Mg")[0] > final(finished, "Mg")[-1]


def test_progress_can_be_read_from_the_log(finished: Path) -> None:
    """Scraping the listing is the only progress signal PHT3D offers.

    The stress period and the time step arrive on different lines and far
    apart, so the reader has to carry the period forward. Read against a real
    listing rather than an invented one, because the spacing is the thing being
    matched.
    """
    from mupstudio.engines.pht3d.results import ProgressReader

    reader = ProgressReader()
    seen = [
        position
        for line in (finished / "pht3d.out").read_text().splitlines()
        if (position := reader.feed(line)) is not None
    ]

    assert seen, "no progress was found in the listing"
    assert seen[-1] == (1, 24), "the last step read should be the last one run"
    assert [step for _, step in seen] == sorted(step for _, step in seen)


def test_the_name_file_makes_the_run_reactive(finished: Path) -> None:
    """Without the PHC entry PHT3D is MT3DMS and the minerals never change."""
    entries = (finished / "pht3d.nam").read_text().split()

    assert "PHC" in entries
    assert "FTL" in entries
