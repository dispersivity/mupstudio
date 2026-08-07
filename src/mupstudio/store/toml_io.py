"""Writing TOML that diffs cleanly.

A project is meant to live in version control and to be edited by hand, which
puts two demands on the writer that a general-purpose serializer does not meet:
the same data must always produce byte-identical output, and floats must not
drift when a file is read and written again.

Python has no TOML writer in the standard library, so this is a small one
covering exactly the shapes the schema produces.
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any


class TomlWriteError(ValueError):
    """A value that cannot be represented in TOML."""


def dumps(data: dict[str, Any]) -> str:
    """Serialize a mapping to TOML.

    Key order is preserved rather than sorted: the schema's field order is
    meaningful to a reader (name before description, top before layers), and
    pydantic already gives it deterministically.
    """
    lines: list[str] = []
    _write_table(data, path=(), lines=lines)
    return "\n".join(lines).rstrip("\n") + "\n"


def loads(text: str) -> dict[str, Any]:
    return tomllib.loads(text)


def read(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(data), encoding="utf-8")


def _write_table(table: dict[str, Any], *, path: tuple[str, ...], lines: list[str]) -> None:
    # None is dropped rather than written: TOML has no null, and omitting the
    # key means the schema default applies on read, which is the same thing.
    # It must not count towards whether a table has content, or a table holding
    # only unset fields would emit an empty header.
    scalars = {
        key: value
        for key, value in table.items()
        if not _is_table_like(value) and value is not None
    }
    tables = {key: value for key, value in table.items() if _is_table_like(value)}

    if path and (scalars or not tables):
        lines.append(f"[{'.'.join(path)}]")

    for key, value in scalars.items():
        lines.append(f"{_key(key)} = {_value(value)}")

    if scalars:
        lines.append("")

    for key, value in tables.items():
        if isinstance(value, dict):
            _write_table(value, path=(*path, key), lines=lines)
        else:
            for item in value:
                lines.append(f"[[{'.'.join((*path, key))}]]")
                _write_table_body(item, path=(*path, key), lines=lines)


def _write_table_body(table: dict[str, Any], *, path: tuple[str, ...], lines: list[str]) -> None:
    """An array-of-tables entry: its header is already written."""
    nested = {key: value for key, value in table.items() if _is_table_like(value)}

    for key, value in table.items():
        if _is_table_like(value) or value is None:
            continue
        lines.append(f"{_key(key)} = {_value(value)}")

    for key, value in nested.items():
        if isinstance(value, dict):
            _write_table(value, path=(*path, key), lines=lines)
        else:
            for item in value:
                lines.append(f"[[{'.'.join((*path, key))}]]")
                _write_table_body(item, path=(*path, key), lines=lines)

    lines.append("")


def _is_table_like(value: Any) -> bool:
    if isinstance(value, dict):
        return True
    return (
        isinstance(value, list) and len(value) > 0 and all(isinstance(item, dict) for item in value)
    )


def _key(key: str) -> str:
    if key.replace("_", "").replace("-", "").isalnum():
        return key
    return _string(key)


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    if isinstance(value, dict):
        # Inline table, for the small mappings a zone map produces.
        body = ", ".join(f"{_key(key)} = {_value(item)}" for key, item in value.items())
        return "{" + body + "}"
    raise TomlWriteError(f"cannot write {type(value).__name__} to TOML: {value!r}")


def _float(value: float) -> str:
    """Format a float so reading it back gives the same number.

    ``repr`` is the shortest representation that round-trips exactly, which is
    what keeps load-save byte-identical. A trailing ``.0`` is added where repr
    omits it, so the value stays a float in TOML rather than becoming an int.
    """
    if math.isnan(value) or math.isinf(value):
        raise TomlWriteError(f"TOML has no representation for {value}")

    text = repr(value)
    if "." not in text and "e" not in text and "E" not in text:
        text += ".0"
    return text


def _string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'
