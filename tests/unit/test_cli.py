from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mupstudio import __version__
from mupstudio.server.app import static_bundle_available


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI the way an installed copy is invoked, in a fresh process.

    `serve --check` starts a real uvicorn server, so it cannot share this
    process with the test runner.
    """
    return subprocess.run(
        [sys.executable, "-m", "mupstudio.cli", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_version_prints_the_installed_version() -> None:
    result = run_cli("version")

    assert result.returncode == 0
    assert result.stdout.strip() == __version__


def test_doctor_reports_every_engine() -> None:
    result = run_cli("doctor")

    assert result.returncode == 0, result.stderr
    for engine in ("mf6", "mf2005", "gridgen", "pht3d"):
        assert engine in result.stdout


def test_serve_check_fails_without_a_frontend_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("mupstudio.server.app.STATIC_DIR", tmp_path / "absent")

    import typer

    from mupstudio.cli import serve

    with pytest.raises(typer.Exit) as exit_info:
        serve(check=True, browser=False)

    assert exit_info.value.exit_code == 1


@pytest.mark.skipif(not static_bundle_available(), reason="frontend bundle not built")
def test_serve_check_passes_with_a_bundle() -> None:
    result = run_cli("serve", "--check", "--no-browser")

    assert result.returncode == 0, result.stderr
    assert "serve --check passed" in result.stdout
