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


class TestRun:
    """Building and running a model with nobody at a screen.

    This is what a sensitivity sweep, a CI regression check and an e2e test all
    go through, so its exit code has to mean something without anyone parsing
    the output.
    """

    def test_a_missing_project_is_said_plainly_and_exits_two(self, tmp_path: Path) -> None:
        result = run_cli("run", str(tmp_path / "nowhere.mup"))

        assert result.returncode == 2
        assert "does not exist" in result.stderr

    def test_a_directory_that_is_not_a_project_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "empty.mup").mkdir()

        result = run_cli("run", str(tmp_path / "empty.mup"))

        assert result.returncode == 2
        assert result.stderr.strip()

    @pytest.mark.slow
    def test_a_column_writes_runs_and_collects(self, tmp_path: Path) -> None:
        """The whole path, on the smallest model that exercises it."""
        created = run_cli("new", "headless", "--cells", "10", "--directory", str(tmp_path))
        assert created.returncode == 0, created.stderr

        result = run_cli("run", str(tmp_path / "headless.mup"))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "run succeeded" in result.stdout
        assert "collected" in result.stdout
        # The results store is what the viewport reads; a run that produced
        # nothing readable is not a run that succeeded.
        assert (tmp_path / "headless.mup" / "runs").exists()

    @pytest.mark.slow
    def test_quiet_says_nothing_unless_something_is_wrong(self, tmp_path: Path) -> None:
        run_cli("new", "hush", "--cells", "10", "--directory", str(tmp_path))

        result = run_cli("run", str(tmp_path / "hush.mup"), "--quiet")

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ""
