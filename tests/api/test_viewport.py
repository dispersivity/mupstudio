from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mupstudio.results.demo import demo_dataset, time_stride
from mupstudio.server.app import create_app
from mupstudio.server.ws.frames import decode

SMALL = "?ncpl=200&nlay=3&ntimes=5"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(dev=True))


class TestCatalog:
    def test_describes_the_grid(self, client: TestClient) -> None:
        body = client.get(f"/api/v1/datasets/demo{SMALL}").json()

        assert body["nlay"] == 3
        assert body["ncpl"] > 0
        assert body["ncells"] == body["nlay"] * body["ncpl"]
        assert len(body["times"]) == 5
        assert len(body["gridHash"]) == 16

    def test_lists_components_with_their_ranges(self, client: TestClient) -> None:
        body = client.get(f"/api/v1/datasets/demo{SMALL}").json()

        component = body["components"][0]
        assert component["name"] == "concentration"
        assert component["vmin"] < component["vmax"]

    def test_bounds_are_ordered(self, client: TestClient) -> None:
        bounds = client.get(f"/api/v1/datasets/demo{SMALL}").json()["bounds"]

        for low, high in zip(bounds["min"], bounds["max"], strict=True):
            assert low < high

    def test_rejects_an_absurd_grid_size(self, client: TestClient) -> None:
        assert client.get("/api/v1/datasets/demo?ncpl=99999999").status_code == 422


class TestMeshFrames:
    def test_sends_every_geometry_frame_then_done(self, client: TestClient) -> None:
        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(json.dumps({"op": "get_mesh", "reqId": 1}))

            frames = [decode(socket.receive_bytes()) for _ in range(5)]
            done = json.loads(socket.receive_text())

        assert [frame.kind for frame in frames] == [
            "mesh_vertices",
            "mesh_cell_offsets",
            "mesh_cell_indices",
            "mesh_cell_centers",
            "cell_elevations",
        ]
        assert done == {"op": "done", "reqId": 1, "frames": 5}

    def test_every_frame_carries_the_request_id_and_grid_hash(self, client: TestClient) -> None:
        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(json.dumps({"op": "get_mesh", "reqId": 42}))
            frames = [decode(socket.receive_bytes()) for _ in range(5)]
            socket.receive_text()

        assert all(frame.header["reqId"] == 42 for frame in frames)
        assert len({frame.header["gridHash"] for frame in frames}) == 1

    def test_geometry_matches_the_dataset(self, client: TestClient) -> None:
        expected = demo_dataset(200, 3, 5).mesh

        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(json.dumps({"op": "get_mesh", "reqId": 1}))
            frames = {}
            for _ in range(5):
                frame = decode(socket.receive_bytes())
                frames[frame.kind] = frame
            socket.receive_text()

        np.testing.assert_array_equal(frames["mesh_vertices"].array, expected.vertices)
        np.testing.assert_array_equal(frames["mesh_cell_indices"].array, expected.cell_indices)

    def test_elevations_stack_top_then_bottom(self, client: TestClient) -> None:
        expected = demo_dataset(200, 3, 5).mesh

        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(json.dumps({"op": "get_mesh", "reqId": 1}))
            elevations = [decode(socket.receive_bytes()) for _ in range(5)][-1]
            socket.receive_text()

        assert elevations.array.shape == (2, expected.nlay, expected.ncpl)
        np.testing.assert_array_equal(elevations.array[0], expected.top)
        np.testing.assert_array_equal(elevations.array[1], expected.botm)


class TestScalarFrames:
    def test_block_carries_every_timestep(self, client: TestClient) -> None:
        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(
                json.dumps({"op": "get_scalar_block", "reqId": 2, "component": "concentration"})
            )
            frame = decode(socket.receive_bytes())
            socket.receive_text()

        assert frame.kind == "scalar_block"
        assert frame.array.shape[0] == 5
        assert frame.header["timeStride"] == 1
        assert frame.header["vmin"] < frame.header["vmax"]

    def test_block_is_decimated_rather_than_truncated_when_over_budget(
        self, client: TestClient
    ) -> None:
        full = demo_dataset(200, 3, 5).scalars["concentration"]
        budget = full.nbytes // 2

        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(
                json.dumps(
                    {
                        "op": "get_scalar_block",
                        "reqId": 3,
                        "component": "concentration",
                        "maxBytes": budget,
                    }
                )
            )
            frame = decode(socket.receive_bytes())
            socket.receive_text()

        stride = frame.header["timeStride"]
        assert stride > 1
        assert frame.array.shape[0] == len(range(0, 5, stride))
        # Decimation keeps the span of the run: first and last-kept steps, not
        # the first N steps.
        np.testing.assert_array_equal(frame.array[0], full[0])
        assert len(frame.header["times"]) == frame.array.shape[0]

    def test_single_timestep_matches_the_block(self, client: TestClient) -> None:
        expected = demo_dataset(200, 3, 5).scalars["concentration"][2]

        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(
                json.dumps(
                    {
                        "op": "get_scalar",
                        "reqId": 4,
                        "component": "concentration",
                        "timeIdx": 2,
                    }
                )
            )
            frame = decode(socket.receive_bytes())
            socket.receive_text()

        assert frame.header["timeIdx"] == 2
        np.testing.assert_array_equal(frame.array, expected)


class TestErrors:
    def test_unknown_component_reports_what_exists(self, client: TestClient) -> None:
        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(
                json.dumps({"op": "get_scalar_block", "reqId": 5, "component": "nope"})
            )
            error = json.loads(socket.receive_text())

        assert error["op"] == "error"
        assert error["reqId"] == 5
        assert "concentration" in error["message"]

    def test_out_of_range_timestep_is_reported(self, client: TestClient) -> None:
        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(
                json.dumps(
                    {
                        "op": "get_scalar",
                        "reqId": 6,
                        "component": "concentration",
                        "timeIdx": 999,
                    }
                )
            )
            error = json.loads(socket.receive_text())

        assert error["op"] == "error"
        assert "999" in error["message"]

    def test_malformed_request_does_not_close_the_socket(self, client: TestClient) -> None:
        with client.websocket_connect(f"/api/v1/ws/viewport{SMALL}") as socket:
            socket.send_text(json.dumps({"op": "nonsense"}))
            error = json.loads(socket.receive_text())

            assert error["op"] == "error"

            # Still usable afterwards.
            socket.send_text(json.dumps({"op": "get_mesh", "reqId": 7}))
            assert decode(socket.receive_bytes()).header["reqId"] == 7


class TestTimeStride:
    def test_is_one_when_everything_fits(self) -> None:
        values = np.zeros((10, 2, 3), dtype=np.float32)

        assert time_stride(values, values.nbytes) == 1

    def test_grows_as_the_budget_shrinks(self) -> None:
        values = np.zeros((100, 10, 10), dtype=np.float32)

        assert time_stride(values, values.nbytes // 2) == 2
        assert time_stride(values, values.nbytes // 10) == 10

    def test_never_drops_the_only_timestep(self) -> None:
        values = np.zeros((1, 100, 100), dtype=np.float32)

        assert time_stride(values, 1) == 1

    def test_rejects_a_nonsense_budget(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            time_stride(np.zeros((4, 2), dtype=np.float32), 0)
