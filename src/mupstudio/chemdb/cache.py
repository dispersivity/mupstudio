"""Finding databases and not reparsing them.

llnl.dat is a megabyte and parses to over a thousand phases. The chemistry
editor asks for that index on every screen, so it is parsed once per file and
kept, keyed by content so an edited database is noticed.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from mupstudio.chemdb.parser import DatabaseIndex, parse_database
from mupstudio.settings import Settings

log = logging.getLogger(__name__)

# Databases shipped with mupstudio, so a fresh install can do chemistry without
# hunting for files. These are USGS public domain.
BUNDLED_DIR = Path(__file__).parent / "assets"


def search_paths(settings: Settings | None = None) -> list[Path]:
    """Where to look for databases, nearest first."""
    settings = settings or Settings.load()
    paths = [Path(directory).expanduser() for directory in settings.database_dirs]
    paths.append(BUNDLED_DIR)

    # mf6rtm and PHT3D both ship databases; if either is installed, its
    # databases are worth offering rather than making the user find them.
    try:
        import mf6rtm

        paths.append(Path(mf6rtm.__file__).parent / "database")
    except ImportError:
        pass

    return [path for path in paths if path.is_dir()]


def available(settings: Settings | None = None) -> list[Path]:
    """Every .dat file on the search path, deduplicated by name."""
    found: dict[str, Path] = {}
    for directory in search_paths(settings):
        for path in sorted(directory.glob("*.dat")):
            found.setdefault(path.name, path)
    return list(found.values())


@lru_cache(maxsize=8)
def _parse_cached(path: str, fingerprint: tuple[int, int]) -> DatabaseIndex:
    """Parse, keyed by path and the file's size and mtime.

    The fingerprint is in the key so editing a database invalidates the entry
    without anyone having to remember to clear it.
    """
    del fingerprint
    return parse_database(Path(path))


def load(path: Path) -> DatabaseIndex:
    """Read a database, from cache when it has not changed."""
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"no database at {path}")
    stat = path.stat()
    return _parse_cached(str(path), (stat.st_size, int(stat.st_mtime)))


def load_by_name(name: str, settings: Settings | None = None) -> DatabaseIndex:
    """Read a database by file name, searching the usual places."""
    if not name.endswith(".dat"):
        name = f"{name}.dat"

    for path in available(settings):
        if path.name == name:
            return load(path)

    known = ", ".join(sorted(path.name for path in available(settings))) or "none"
    raise FileNotFoundError(f"no database named {name} (found: {known})")


def clear() -> None:
    _parse_cached.cache_clear()
