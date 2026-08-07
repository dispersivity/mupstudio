"""Bringing an older project up to the current schema.

Each step takes the raw dictionary read from disk and returns the shape the next
version expects. They run in order on load, so a project written by any earlier
version opens without the user doing anything.

There is nothing to migrate yet — version 1 is the first — but the registry
exists so the first change has an obvious place to go, and so `load` does not
have to grow a special case for it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mupstudio.schema.project import SCHEMA_VERSION

Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Keyed by the version being migrated FROM: MIGRATIONS[1] upgrades 1 to 2.
MIGRATIONS: dict[int, Migration] = {}


def upgrade(document: dict[str, Any], *, from_version: int) -> dict[str, Any]:
    """Apply every migration between the file's version and this build's."""
    version = from_version
    while version < SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"no migration from schema version {version} to {version + 1}; "
                "this build cannot read the project"
            )
        document = migration(document)
        version += 1
        document.setdefault("meta", {})["schema_version"] = version

    return document
