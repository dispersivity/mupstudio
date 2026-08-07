from __future__ import annotations

from pathlib import Path

from mupstudio.settings import Settings


def test_defaults_are_empty() -> None:
    settings = Settings()
    assert settings.mf6_exe is None
    assert settings.database_dirs == []
    assert settings.max_concurrent_runs == 2


def test_missing_file_loads_defaults(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "nope.toml") == Settings()


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    original = Settings(
        pht3d_exe="/opt/bin/pht3d",
        database_dirs=["/data/db", "/more/db"],
        max_concurrent_runs=4,
    )
    original.save(path)

    assert Settings.load(path) == original
