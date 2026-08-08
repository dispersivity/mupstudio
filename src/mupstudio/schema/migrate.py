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


def _v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """Version 1 files are read by the models themselves.

    Boundary packages gained entries, layer elevations became surfaces and
    grids gained active cells — all three accept the version 1 spelling through
    a validator on the model, because a bare number is still what a column
    model wants to write and a one-entry package is still the common case.

    So there is nothing to rewrite here. The step exists because the version
    still has to advance: a version 1 build cannot read what this one writes,
    and the number is how it finds that out rather than failing on a field it
    does not recognise.
    """
    return document


# Keyed by the version being migrated FROM: MIGRATIONS[1] upgrades 1 to 2.
MIGRATIONS: dict[int, Migration] = {1: _v1_to_v2}


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
