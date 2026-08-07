from __future__ import annotations

from fastapi.testclient import TestClient

from mupstudio import __version__
from mupstudio.server.app import create_app


def client() -> TestClient:
    return TestClient(create_app(dev=True))


def test_health_reports_version() -> None:
    response = client().get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_doctor_lists_checks() -> None:
    response = client().get("/api/v1/doctor")

    assert response.status_code == 200
    body = response.json()
    names = {check["name"] for check in body["checks"]}
    assert {"flopy", "mf6rtm", "phreeqcrm", "mf6", "pht3d"} <= names
    for check in body["checks"]:
        assert check["status"] in {"ok", "warn", "fail"}


def test_settings_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("mupstudio.settings.settings_path", lambda: tmp_path / "settings.toml")

    api = client()
    assert api.get("/api/v1/settings").json()["max_concurrent_runs"] == 2

    updated = api.put("/api/v1/settings", json={"max_concurrent_runs": 6, "pht3d_exe": "/bin/p"})
    assert updated.status_code == 200

    assert api.get("/api/v1/settings").json()["max_concurrent_runs"] == 6
