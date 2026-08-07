"""Where runs are recorded and where their files live.

State is kept in SQLite rather than in memory so a server restart does not
lose track of what was running. Anything found still marked as running after a
restart is reconciled: the process that owned it is gone.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from mupstudio.settings import data_dir

RunState = Literal["queued", "running", "succeeded", "failed", "cancelled", "unknown"]
TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "unknown"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    engine     TEXT NOT NULL,
    label      TEXT,
    workdir    TEXT NOT NULL,
    state      TEXT NOT NULL,
    pid        INTEGER,
    exit_code  INTEGER,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    message    TEXT
);
"""


@dataclass
class RunRecord:
    run_id: str
    engine: str
    label: str | None
    workdir: str
    state: RunState
    pid: int | None = None
    exit_code: int | None = None
    started_at: str = ""
    ended_at: str | None = None
    message: str | None = None

    @property
    def results_dir(self) -> Path:
        return Path(self.workdir) / "results"

    @property
    def has_results(self) -> bool:
        return (self.results_dir / "catalog.json").exists()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunRegistry:
    """The list of runs, past and present."""

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "runs.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def add(self, record: RunRecord) -> RunRecord:
        record.started_at = record.started_at or now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, engine, label, workdir, state, pid, exit_code,"
                " started_at, ended_at, message)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.run_id,
                    record.engine,
                    record.label,
                    record.workdir,
                    record.state,
                    record.pid,
                    record.exit_code,
                    record.started_at,
                    record.ended_at,
                    record.message,
                ),
            )
        return record

    def update(self, run_id: str, **fields: object) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",
                (*fields.values(), run_id),
            )

    def finish(
        self, run_id: str, state: RunState, exit_code: int | None, message: str | None = None
    ) -> None:
        self.update(run_id, state=state, exit_code=exit_code, ended_at=now(), message=message)

    def get(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunRecord(**dict(row)) if row else None

    def recent(self, limit: int = 50) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [RunRecord(**dict(row)) for row in rows]

    def delete(self, run_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    def reconcile(self) -> list[str]:
        """Mark runs whose process is gone as no longer running.

        Called at startup. A run recorded as running after a restart is not
        running: this server did not start it, and nothing is watching it.
        """
        stale: list[str] = []
        for record in self.recent(1000):
            if record.state in TERMINAL:
                continue
            if record.pid is not None and _process_alive(record.pid):
                continue
            self.finish(
                record.run_id,
                "unknown",
                None,
                "the server restarted while this run was in progress",
            )
            stale.append(record.run_id)
        return stale


def _process_alive(pid: int) -> bool:
    import os

    # os.kill treats 0 and negative values as process groups, not processes:
    # os.kill(0, 0) signals our own group and always succeeds, which would make
    # a bad record look permanently alive. Only real pids are positive.
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        # Exists but belongs to another user, which still means alive.
        return True
    return True
