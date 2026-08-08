"""The list of projects this machine knows about.

Projects live wherever the user put them, so the app keeps a small index of
paths rather than owning a projects folder. A path that has since been moved or
deleted is reported as missing instead of silently disappearing, because a
project vanishing from the list looks like data loss.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from mupstudio.settings import config_dir
from mupstudio.store import projectstore, toml_io


@dataclass
class ProjectEntry:
    """One remembered project."""

    path: Path
    name: str
    engine: str
    last_opened: str | None = None

    @property
    def exists(self) -> bool:
        return projectstore.is_project(self.path)


def default_parent() -> Path:
    """Where a new project goes when nobody says otherwise.

    Not the working directory. A server started from a source checkout would
    scatter project directories through it, and a server started by a desktop
    launcher has a working directory nobody chose. A named folder under the
    user's documents is somewhere a person can find again.
    """
    import platformdirs

    documents = Path(platformdirs.user_documents_dir())
    root = documents if documents.is_dir() else Path.home()
    return root / "MUP Studio"


def registry_path() -> Path:
    return config_dir() / "projects.toml"


def _read() -> list[dict[str, str]]:
    path = registry_path()
    if not path.exists():
        return []
    with path.open("rb") as handle:
        content = tomllib.load(handle)
    entries = content.get("projects", [])
    return entries if isinstance(entries, list) else []


def _write(entries: list[dict[str, str]]) -> None:
    toml_io.write(registry_path(), {"projects": entries})


def entries() -> list[ProjectEntry]:
    """Remembered projects, most recently opened first."""
    found = [
        ProjectEntry(
            path=Path(entry["path"]),
            name=entry.get("name", Path(entry["path"]).stem),
            engine=entry.get("engine", "mf6rtm"),
            last_opened=entry.get("last_opened"),
        )
        for entry in _read()
        if "path" in entry
    ]
    return sorted(found, key=lambda entry: entry.last_opened or "", reverse=True)


def remember(directory: Path, *, name: str, engine: str) -> ProjectEntry:
    """Add or refresh a project in the index."""
    directory = Path(directory).resolve()
    now = projectstore._now()

    kept = [entry for entry in _read() if Path(entry.get("path", "")) != directory]
    kept.insert(0, {"path": str(directory), "name": name, "engine": engine, "last_opened": now})
    _write(kept[:100])

    return ProjectEntry(path=directory, name=name, engine=engine, last_opened=now)


def forget(directory: Path) -> None:
    """Remove a project from the index. The files on disk are left alone."""
    directory = Path(directory).resolve()
    _write([entry for entry in _read() if Path(entry.get("path", "")) != directory])
