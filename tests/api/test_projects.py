"""Project endpoints.

Editing goes through the same schema validation as loading, so an edit that
would break the model is refused and the copy on disk is left alone. That is the
property these tests are mostly about: a project on disk always loads.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mupstudio.server.app import create_app
from mupstudio.store import projectstore


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A server whose project index is private to this test."""
    monkeypatch.setattr(
        "mupstudio.store.registry.registry_path", lambda: tmp_path / "projects.toml"
    )
    return TestClient(create_app(dev=True))


@pytest.fixture()
def project(client: TestClient, tmp_path: Path) -> str:
    response = client.post(
        "/api/v1/projects", json={"name": "api test", "parent": str(tmp_path / "models")}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["project"]["path"])


def document(client: TestClient, path: str) -> dict:
    return client.get(f"/api/v1/projects/document?path={path}").json()["document"]


def save(client: TestClient, path: str, body: dict) -> dict:
    return client.put(f"/api/v1/projects/document?path={path}", json={"document": body}).json()


class TestCreate:
    def test_a_new_project_runs_without_further_editing(
        self, client: TestClient, project: str
    ) -> None:
        """A column with no boundaries produces a field of zeros, which is useless."""
        detail = client.get(f"/api/v1/projects/detail?path={project}").json()

        assert [item["id"] for item in detail["boundaries"]] == ["inflow", "outflow"]

    def test_the_inflow_carries_solute(self, client: TestClient, project: str) -> None:
        inflow = next(
            item for item in document(client, project)["flow"]["packages"] if item["id"] == "inflow"
        )

        assert inflow["concentration"]["value"] > 0

    def test_rejects_an_unknown_engine(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post(
            "/api/v1/projects", json={"name": "x", "engine": "feflow", "parent": str(tmp_path)}
        )

        assert response.status_code == 422
        assert "feflow" in response.text

    def test_refuses_to_overwrite(self, client: TestClient, tmp_path: Path) -> None:
        body = {"name": "twice", "parent": str(tmp_path)}
        assert client.post("/api/v1/projects", json=body).status_code == 201

        assert client.post("/api/v1/projects", json=body).status_code == 409

    def test_a_created_project_is_remembered(self, client: TestClient, project: str) -> None:
        listed = client.get("/api/v1/projects").json()["projects"]

        assert [entry["path"] for entry in listed] == [project]


class TestEditing:
    def test_an_edit_is_saved_and_read_back(self, client: TestClient, project: str) -> None:
        body = document(client, project)
        body["flow"]["properties"]["k"]["value"] = 12.5

        result = save(client, project, body)

        assert result["ok"]
        assert document(client, project)["flow"]["properties"]["k"]["value"] == 12.5

    def test_the_summary_reflects_the_edit(self, client: TestClient, project: str) -> None:
        body = document(client, project)
        body["grid"]["columns"]["ncells"] = 12
        body["flow"]["packages"][1]["cells"]["columns"] = [12]

        result = save(client, project, body)

        assert "1x1x12" in result["detail"]["summary"]

    def test_a_broken_cross_reference_is_refused(self, client: TestClient, project: str) -> None:
        body = document(client, project)
        body["flow"]["packages"][1]["cells"]["columns"] = [9999]

        result = save(client, project, body)

        assert not result["ok"]
        assert any("9999" in problem["message"] for problem in result["problems"])

    def test_a_refused_edit_does_not_reach_disk(self, client: TestClient, project: str) -> None:
        before = document(client, project)
        broken = document(client, project)
        broken["grid"]["columns"]["ncells"] = -5

        save(client, project, broken)

        assert document(client, project) == before

    def test_problems_name_the_field(self, client: TestClient, project: str) -> None:
        body = document(client, project)
        body["grid"]["top"] = -999.0  # now below every layer bottom

        result = save(client, project, body)

        assert not result["ok"]
        assert any("grid" in problem["field"] for problem in result["problems"])

    def test_a_series_that_does_not_cover_the_periods_is_refused(
        self, client: TestClient, project: str
    ) -> None:
        body = document(client, project)
        body["time"]["periods"].append(dict(body["time"]["periods"][0]))
        body["flow"]["packages"][0]["rate"] = {"kind": "per_period", "values": [1.0]}

        result = save(client, project, body)

        assert not result["ok"]
        assert any("stress" in problem["message"] for problem in result["problems"])

    def test_editing_an_unknown_project_is_reported(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        response = client.put(
            f"/api/v1/projects/document?path={tmp_path / 'nope'}", json={"document": {}}
        )

        assert response.status_code == 404


class TestWriting:
    def test_validate_reports_the_cells_and_boundaries(
        self, client: TestClient, project: str
    ) -> None:
        result = client.post(f"/api/v1/projects/validate?path={project}").json()

        assert result["ok"]
        assert result["cells"] == 50
        assert {item["id"] for item in result["boundaries"]} == {"inflow", "outflow"}

    def test_write_produces_the_files_modflow_needs(self, client: TestClient, project: str) -> None:
        result = client.post(f"/api/v1/projects/write?path={project}").json()

        assert "mfsim.nam" in result["files"]
        assert "gwf.dis" in result["files"]

    def test_a_written_file_can_be_previewed(self, client: TestClient, project: str) -> None:
        client.post(f"/api/v1/projects/write?path={project}")

        body = client.get(f"/api/v1/projects/file?path={project}&name=gwf.dis").json()

        assert "NCOL" in body["content"].upper()
        assert body["bytes"] > 0

    def test_the_preview_cannot_read_outside_the_run_directory(
        self, client: TestClient, project: str
    ) -> None:
        """The preview shows what was generated; it is not a file browser."""
        client.post(f"/api/v1/projects/write?path={project}")

        response = client.get(f"/api/v1/projects/file?path={project}&name=../../../../etc/passwd")

        assert response.status_code == 400

    def test_a_pht3d_project_with_no_chemistry_says_why_it_cannot_be_written(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """PHT3D exists to react. A new project has no chemistry yet, and the
        message should point at that rather than at a missing feature."""
        created = client.post(
            "/api/v1/projects",
            json={"name": "pht", "engine": "pht3d", "parent": str(tmp_path / "pht")},
        ).json()

        response = client.post(f"/api/v1/projects/write?path={created['project']['path']}")

        assert response.status_code == 422
        assert "no chemistry" in response.json()["detail"]

    def test_writing_a_pht3d_project_produces_a_runnable_deck(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """Flow, transport and chemistry, plus the name file tying them together."""
        from mupstudio.schema.project import Project
        from mupstudio.schema.templates import starter_chemistry
        from mupstudio.store import projectstore

        created = client.post(
            "/api/v1/projects",
            json={"name": "pht", "engine": "pht3d", "parent": str(tmp_path / "pht")},
        ).json()
        path = created["project"]["path"]

        base = projectstore.load(Path(path))
        projectstore.save(
            Path(path),
            Project.model_validate(
                {
                    **base.model_dump(),
                    "chemistry": starter_chemistry(database="pht3d_datab.dat").model_dump(),
                }
            ),
        )

        body = client.post(f"/api/v1/projects/write?path={path}").json()

        assert body["reactive"] is True
        assert body["components"][:2] == ["C(+4)", "Ca"]
        assert {"pht3d.nam", "pht3d_ph.dat", "trans.btn", "trans.ssm", "flow.dis"} <= set(
            body["files"]
        )


def test_a_hand_edited_project_opens_through_the_api(client: TestClient, project: str) -> None:
    """The TOML is a supported authoring surface, including for the app."""
    grid = Path(project) / "grid.toml"
    grid.write_text(grid.read_text().replace("ncells = 50", "ncells = 7"))
    # The outflow boundary has to move too, since it referred to column 50.
    flow = Path(project) / "flow.toml"
    flow.write_text(flow.read_text().replace("columns = [50]", "columns = [7]"))

    detail = client.post("/api/v1/projects/open", json={"path": project}).json()["detail"]

    assert detail["grid"]["ncol"] == 7
    assert projectstore.load(Path(project)).grid.ncol == 7
