"""Schema to running model: write MODFLOW 6 input and run it.

These use the real mf6 executable, because the point is that the files we write
are files MODFLOW accepts. Every failure found while building this writer was a
rejection by mf6, not a wrong-looking array — a missing transverse dispersivity,
an undeclared auxiliary variable — so a test that stops at "the file was
written" would have caught none of them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from mupstudio.compile.compiler import compile_project
from mupstudio.doctor import find_executable
from mupstudio.engines.mf6rtm.writer import write_mf6
from mupstudio.results.store import ResultsStore, collect_mf6rtm_run
from mupstudio.schema.common import (
    ConstantSeries,
    StressPeriod,
    TimeDiscretisation,
    constant,
)
from mupstudio.schema.flow import (
    CellRange,
    ConstantHeadPackage,
    FlowModel,
    FlowProperties,
    WellPackage,
)
from mupstudio.schema.grid import column_grid
from mupstudio.schema.project import Project, ProjectMeta
from mupstudio.schema.transport import Dispersion, TransportModel

MF6 = find_executable("mf6")

pytestmark = pytest.mark.skipif(
    MF6 is None,
    reason="mf6 not installed; run: mupstudio get-engines",
)


# One pore volume through the column over the simulated time, so the tracer
# actually sweeps it: 0.5 m x 1 m x 1 m at porosity 0.32 is 0.16 m3, and the run
# is 0.24 d.
PORE_VOLUME = 0.5 * 1.0 * 1.0 * 0.32
SIMULATED_DAYS = 0.24
INFLOW_RATE = PORE_VOLUME / SIMULATED_DAYS


def tracer_column(ncells: int = 50, *, concentration: float = 1.0) -> Project:
    """A column with water and solute entering one end, leaving the other."""
    return Project(
        meta=ProjectMeta(name="tracer column", engine="mf6rtm"),
        grid=column_grid(ncells=ncells, length=0.5),
        time=TimeDiscretisation(periods=[StressPeriod(perlen=SIMULATED_DAYS, nstp=24)]),
        flow=FlowModel(
            properties=FlowProperties(k=constant(1.0), porosity=constant(0.32)),
            packages=[
                WellPackage(
                    id="inflow",
                    cells=CellRange(layers=[1], rows=[1], columns=[1]),
                    rate=ConstantSeries(value=INFLOW_RATE),
                    concentration=ConstantSeries(value=concentration),
                ),
                ConstantHeadPackage(
                    id="outflow",
                    cells=CellRange(layers=[1], rows=[1], columns=[ncells]),
                    head=ConstantSeries(value=0.0),
                ),
            ],
        ),
        transport=TransportModel(dispersion=Dispersion(longitudinal=constant(0.0067))),
    )


def run_mf6(workdir: Path) -> subprocess.CompletedProcess[str]:
    assert MF6 is not None
    return subprocess.run([str(MF6)], cwd=workdir, capture_output=True, text=True, timeout=600)


@pytest.fixture(scope="module")
def finished_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A written, run and collected model, shared across the assertions."""
    workdir = tmp_path_factory.mktemp("mf6") / "run"
    write_mf6(compile_project(tracer_column()), workdir)
    result = run_mf6(workdir)
    assert result.returncode == 0, result.stdout[-2000:]
    collect_mf6rtm_run(workdir, workdir / "results", run_id="tracer")
    return workdir


class TestWriting:
    def test_writes_the_files_modflow_needs(self, tmp_path: Path) -> None:
        manifest = write_mf6(compile_project(tracer_column(ncells=5)), tmp_path / "w")

        assert "mfsim.nam" in manifest.files
        assert "gwf.dis" in manifest.files
        assert "gwf.npf" in manifest.files
        assert "trans.dis" in manifest.files
        assert manifest.warnings == []

    def test_names_a_boundary_package_after_its_id(self, tmp_path: Path) -> None:
        manifest = write_mf6(compile_project(tracer_column(ncells=5)), tmp_path / "w")

        assert any("inflow" in name for name in manifest.files)
        assert any("outflow" in name for name in manifest.files)

    def test_supplies_a_transverse_dispersivity_with_a_longitudinal_one(
        self, tmp_path: Path
    ) -> None:
        """MODFLOW rejects ALH without ATH1, so the compiler fills it in."""
        model = compile_project(tracer_column(ncells=5))

        np.testing.assert_allclose(
            model.properties["ath1"], model.properties["alh"] * 0.1, rtol=1e-12
        )
        np.testing.assert_allclose(
            model.properties["atv"], model.properties["alh"] * 0.01, rtol=1e-12
        )

    def test_declares_the_auxiliary_variable_the_ssm_package_reads(self, tmp_path: Path) -> None:
        """Without the declaration MODFLOW cannot resolve the aux name."""
        write_mf6(compile_project(tracer_column(ncells=5)), tmp_path / "w")

        well = (tmp_path / "w" / "gwf.inflow.well").read_text().lower()

        assert "auxiliary" in well
        assert "tracer" in well


class TestRunning:
    def test_modflow_accepts_what_we_wrote(self, finished_run: Path) -> None:
        assert (finished_run / "mfsim.lst").read_text().count("Normal termination") == 1

    def test_produces_the_outputs_the_reader_expects(self, finished_run: Path) -> None:
        produced = {path.suffix for path in finished_run.iterdir()}

        # .grb is what the mesh is built from; .ucn is what gets rendered.
        assert {".grb", ".hds", ".ucn"} <= produced

    def test_a_model_with_no_boundaries_still_runs(self, tmp_path: Path) -> None:
        bare = Project(
            meta=ProjectMeta(name="bare", engine="mf6rtm"),
            grid=column_grid(ncells=5, length=1.0),
            time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0, steady=True)]),
        )
        write_mf6(compile_project(bare), tmp_path / "w")

        assert run_mf6(tmp_path / "w").returncode == 0

    def test_a_multi_layer_model_runs(self, tmp_path: Path) -> None:
        from mupstudio.schema.grid import AxisSpacing, LayerSpec, StructuredGrid

        layered = Project(
            meta=ProjectMeta(name="layered", engine="mf6rtm"),
            grid=StructuredGrid(
                columns=AxisSpacing(ncells=4, total_length=40.0),
                rows=AxisSpacing(ncells=3, total_length=30.0),
                top=10.0,
                layers=[LayerSpec(bottom=0.0, sublayers=3), LayerSpec(bottom=-10.0)],
            ),
            time=TimeDiscretisation(periods=[StressPeriod(perlen=1.0, steady=True)]),
        )
        model = compile_project(layered)
        write_mf6(model, tmp_path / "w")

        assert model.grid.nlay == 4
        assert run_mf6(tmp_path / "w").returncode == 0


class TestResults:
    def test_collects_into_the_normalized_store(self, finished_run: Path) -> None:
        store = ResultsStore(finished_run / "results")

        assert store.catalog.ncells == 50
        assert len(store.catalog.times) == 24
        assert store.catalog.warnings == []

    def test_the_mesh_matches_the_grid_we_asked_for(self, finished_run: Path) -> None:
        mesh = ResultsStore(finished_run / "results").mesh

        assert (mesh.nlay, mesh.ncpl) == (1, 50)
        # A single row: the axis the viewport offers to squash.
        assert mesh.thin_axis == "y"

    def test_one_pore_volume_sweeps_most_of_the_column(self, finished_run: Path) -> None:
        """With a pore volume injected, the tracer should reach the far end."""
        values = np.asarray(ResultsStore(finished_run / "results").scalars("trans"))[:, 0, :]
        reached = np.nonzero(values[-1] > 1e-6)[0]

        assert reached.size > 0
        assert int(reached.max()) > values.shape[1] // 2

    def test_the_tracer_enters_and_accumulates(self, finished_run: Path) -> None:
        values = np.asarray(ResultsStore(finished_run / "results").scalars("trans"))
        totals = values.sum(axis=(1, 2))

        assert values[0].max() > 0, "solute should be present from the first output"
        assert np.all(np.diff(totals) > -1e-9), "mass should not decrease while injecting"
        assert totals[-1] > totals[0]

    def test_the_front_advances_down_the_column(self, finished_run: Path) -> None:
        """The half-concentration point moves downstream, step by step.

        Tracked at C/C0 = 0.5, the usual definition of a breakthrough front.
        Any small threshold instead reports the leading edge, which dispersion
        carries to the end of the column almost at once and which therefore
        shows no advance to measure.
        """
        values = np.asarray(ResultsStore(finished_run / "results").scalars("trans"))[:, 0, :]

        def front(step: int) -> int:
            above = np.nonzero(values[step] >= 0.5)[0]
            return int(above.max()) if above.size else -1

        assert front(0) < front(len(values) // 2) < front(-1)

    def test_concentration_stays_within_the_source_strength(self, finished_run: Path) -> None:
        """Injected water is diluted by what is already there, never concentrated."""
        values = np.asarray(ResultsStore(finished_run / "results").scalars("trans"))

        assert values.max() <= 1.0 + 1e-9
        assert values.min() >= -1e-9
