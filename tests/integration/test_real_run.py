"""End to end over a real mf6rtm run: read it, store it, serve it.

The fixture is the finished output of mf6rtm's own test01 (the Engesgaard and
Kipp column), which ships with reference results. Using real output rather than
a fabricated directory is the point: it is the formats and quirks of actual
MODFLOW 6 files that break readers.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mupstudio.engines.mf6rtm import results as reader
from mupstudio.jobs.registry import RunRecord, RunRegistry
from mupstudio.results.store import ResultsStore, collect_mf6rtm_run
from mupstudio.server.app import create_app
from mupstudio.server.ws.frames import decode

# mf6rtm's autotest output, if this machine has the repository checked out.
MF6RTM_TEST01 = Path.home() / "dev/code/mf6rtm/mf6rtm-main/autotest/test01"

pytestmark = pytest.mark.skipif(
    not MF6RTM_TEST01.exists(),
    reason=f"no mf6rtm run output at {MF6RTM_TEST01}",
)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A private copy, so collecting into it cannot touch the original."""
    destination = tmp_path_factory.mktemp("run") / "test01"
    shutil.copytree(MF6RTM_TEST01, destination)
    return destination


@pytest.fixture(scope="module")
def store(run_dir: Path) -> ResultsStore:
    collect_mf6rtm_run(run_dir, run_dir / "results", run_id="test01")
    return ResultsStore(run_dir / "results")


class TestReader:
    def test_finds_every_transported_component(self, run_dir: Path) -> None:
        components = reader.discover_components(run_dir)

        assert components == ["C", "Ca", "Charge", "Cl", "H", "Mg", "O"]

    def test_builds_a_mesh_matching_the_model(self, run_dir: Path) -> None:
        mesh = reader.read_mesh(run_dir)

        # test01 is a 1 x 1 x 50 column.
        assert mesh.ncpl == 50
        assert mesh.nlay == 1
        mesh.validate()

    def test_structured_cells_come_through_as_quads(self, run_dir: Path) -> None:
        mesh = reader.read_mesh(run_dir)
        corners = np.diff(mesh.cell_offsets)

        assert set(corners.tolist()) == {4}

    def test_cells_have_positive_thickness(self, run_dir: Path) -> None:
        mesh = reader.read_mesh(run_dir)

        assert np.all(mesh.top > mesh.botm)

    def test_reads_concentrations_for_every_timestep(self, run_dir: Path) -> None:
        times, values = reader.read_component(run_dir, "Ca")

        assert len(times) == 24
        assert values.shape == (24, 1, 50)
        assert values.dtype == np.float32
        assert np.all(np.isfinite(values))

    def test_reports_a_component_that_is_not_there(self, run_dir: Path) -> None:
        with pytest.raises(reader.RunOutputError, match="Unobtainium"):
            reader.read_component(run_dir, "Unobtainium")

    def test_reads_the_selected_output(self, run_dir: Path) -> None:
        sout = reader.read_sout(run_dir)

        assert sout is not None
        # Chemistry columns come from the model's USER_PUNCH block.
        assert {"time_d", "cell", "pH", "Calcite"} <= set(sout.columns)

    def test_rejects_a_directory_with_no_run_in_it(self, tmp_path: Path) -> None:
        assert not reader.looks_like_run_output(tmp_path)
        with pytest.raises(reader.RunOutputError, match=r"no \.grb"):
            reader.read_mesh(tmp_path)


class TestStore:
    def test_catalog_describes_the_run(self, store: ResultsStore) -> None:
        catalog = store.catalog

        assert catalog.engine == "mf6rtm"
        assert catalog.status == "succeeded"
        assert catalog.ncells == 50
        assert len(catalog.times) == 24
        assert catalog.warnings == []

    def test_records_a_range_per_component(self, store: ResultsStore) -> None:
        for entry in store.catalog.components:
            assert entry["vmin"] <= entry["vmax"]
            assert entry["unit"] == "mol/L"

    def test_scalars_are_memory_mapped(self, store: ResultsStore) -> None:
        values = store.scalars("Ca")

        assert isinstance(values, np.memmap)
        assert values.shape == (24, 1, 50)

    def test_stored_values_match_the_source_output(
        self, store: ResultsStore, run_dir: Path
    ) -> None:
        """The store must not alter the numbers, only rearrange them."""
        _, expected = reader.read_component(run_dir, "Ca")

        np.testing.assert_array_equal(np.asarray(store.scalars("Ca")), expected)

    def test_a_timestep_is_a_slice_of_the_whole(self, store: ResultsStore) -> None:
        whole = store.scalars("Ca")

        np.testing.assert_array_equal(store.timestep("Ca", 7), whole[7])

    def test_rejects_a_timestep_past_the_end(self, store: ResultsStore) -> None:
        with pytest.raises(IndexError, match="99"):
            store.timestep("Ca", 99)

    def test_names_the_components_it_has_when_asked_for_one_it_lacks(
        self, store: ResultsStore
    ) -> None:
        with pytest.raises(KeyError, match="Ca"):
            store.scalars("Plutonium")

    def test_keeps_the_selected_output(self, store: ResultsStore) -> None:
        sout = store.sout()

        assert sout is not None
        assert len(sout) == 1200  # 24 timesteps x 50 cells

    def test_mesh_survives_the_round_trip(self, store: ResultsStore, run_dir: Path) -> None:
        original = reader.read_mesh(run_dir)

        assert store.mesh.grid_hash == original.grid_hash


class TestServing:
    @pytest.fixture()
    def client(self, store: ResultsStore, tmp_path: Path, monkeypatch) -> TestClient:
        """A server whose registry knows about this one run."""
        registry = RunRegistry(tmp_path / "runs.db")
        registry.add(
            RunRecord(
                run_id="test01",
                engine="mf6rtm",
                label="Engesgaard column",
                workdir=str(store.directory.parent),
                state="succeeded",
            )
        )
        monkeypatch.setattr(
            "mupstudio.jobs.registry.RunRegistry",
            lambda *args, **kwargs: registry,
        )
        return TestClient(create_app(dev=True))

    def test_lists_the_run_alongside_the_demo(self, client: TestClient) -> None:
        body = client.get("/api/v1/datasets").json()

        assert body["demo"]["id"] == "demo"
        assert [run["id"] for run in body["runs"]] == ["test01"]
        assert body["runs"][0]["hasResults"] is True

    def test_serves_the_run_catalog(self, client: TestClient) -> None:
        body = client.get("/api/v1/datasets/test01").json()

        assert body["kind"] == "run"
        assert body["engine"] == "mf6rtm"
        assert body["ncells"] == 50
        assert [entry["name"] for entry in body["components"]][:2] == ["C", "Ca"]

    def test_reports_an_unknown_run(self, client: TestClient) -> None:
        response = client.get("/api/v1/datasets/r_nope")

        assert response.status_code == 404
        assert "r_nope" in response.json()["detail"]

    def test_streams_the_real_mesh(self, client: TestClient, store: ResultsStore) -> None:
        with client.websocket_connect("/api/v1/ws/viewport?dataset=test01") as socket:
            socket.send_text(json.dumps({"op": "get_mesh", "reqId": 1}))
            frames = {}
            for _ in range(5):
                frame = decode(socket.receive_bytes())
                frames[frame.kind] = frame
            socket.receive_text()

        np.testing.assert_array_equal(frames["mesh_vertices"].array, store.mesh.vertices)
        assert frames["cell_elevations"].array.shape == (2, 1, 50)

    def test_streams_concentrations_matching_the_store(
        self, client: TestClient, store: ResultsStore
    ) -> None:
        with client.websocket_connect("/api/v1/ws/viewport?dataset=test01") as socket:
            socket.send_text(json.dumps({"op": "get_scalar_block", "reqId": 2, "component": "Ca"}))
            frame = decode(socket.receive_bytes())
            socket.receive_text()

        assert frame.header["component"] == "Ca"
        assert frame.header["timeStride"] == 1
        np.testing.assert_array_equal(frame.array, np.asarray(store.scalars("Ca")))

    def test_reports_a_component_the_run_does_not_have(self, client: TestClient) -> None:
        with client.websocket_connect("/api/v1/ws/viewport?dataset=test01") as socket:
            socket.send_text(
                json.dumps({"op": "get_scalar_block", "reqId": 3, "component": "Plutonium"})
            )
            error = json.loads(socket.receive_text())

        assert error["op"] == "error"
        assert "Ca" in error["message"]


class TestPartialRun:
    """A run that died partway must still be readable."""

    def test_collects_what_was_written_and_says_so(self, tmp_path: Path) -> None:
        workdir = tmp_path / "partial"
        shutil.copytree(MF6RTM_TEST01, workdir)

        # Simulate a run killed mid-write: one component's output is truncated
        # to a whole number of records, the rest are complete.
        victim = workdir / "Ca.ucn"
        data = victim.read_bytes()
        victim.write_bytes(data[: len(data) // 2])

        catalog = collect_mf6rtm_run(
            workdir, workdir / "results", run_id="partial", status="failed"
        )

        assert catalog.status == "failed"
        assert catalog.components, "a partial run should still yield components"
        # Every component now spans the same, shorter, time axis.
        store = ResultsStore(workdir / "results")
        lengths = {store.scalars(name).shape[0] for name in store.component_names}
        assert lengths == {len(catalog.times)}
