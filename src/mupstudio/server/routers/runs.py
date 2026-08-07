"""Runs: status, log, cancel, and live progress.

Progress comes over a websocket because a reactive run reports per timestep and
polling would either lag or hammer the server. The endpoint also sends the
current state on connect, so a client that joins mid-run is not left blank until
the next timestep.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from mupstudio.results.store import collect_mf6rtm_run
from mupstudio.server.deps import run_registry, runner_instance

log = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

# Tail length for the log endpoint. Enough to show what went wrong without
# shipping a listing file that can reach megabytes.
LOG_TAIL_LINES = 400


def _record(run_id: str):  # type: ignore[no-untyped-def]
    record = run_registry().get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return record


def _state(run_id: str) -> dict[str, Any]:
    record = _record(run_id)
    return {
        "runId": record.run_id,
        "engine": record.engine,
        "label": record.label,
        "state": record.state,
        "exitCode": record.exit_code,
        "startedAt": record.started_at,
        "endedAt": record.ended_at,
        "message": record.message,
        "hasResults": record.has_results,
        "workdir": record.workdir,
        "progress": runner_instance().progress(run_id),
    }


@router.get("/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    return {"runs": [_state(record.run_id) for record in run_registry().recent(limit)]}


@router.get("/runs/{run_id}")
def run_status(run_id: str) -> dict[str, Any]:
    return _state(run_id)


@router.get("/runs/{run_id}/log")
def run_log(
    run_id: str, tail: int = Query(default=LOG_TAIL_LINES, ge=1, le=10_000)
) -> dict[str, Any]:
    """The end of the captured engine output."""
    record = _record(run_id)
    path = Path(record.workdir) / "mupstudio-run.log"
    if not path.exists():
        return {"runId": run_id, "lines": [], "detail": "no output captured yet"}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"runId": run_id, "lines": lines[-tail:], "truncated": len(lines) > tail}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    _record(run_id)
    await runner_instance().cancel(run_id)
    return _state(run_id)


@router.post("/runs/{run_id}/collect")
def collect_run(run_id: str) -> dict[str, Any]:
    """Read a finished run's output into the results store.

    Separate from the run itself, and safe to repeat: a run that failed partway
    still has output worth looking at, and a collection that was interrupted
    should be retryable.
    """
    record = _record(run_id)
    workdir = Path(record.workdir)

    try:
        catalog = collect_mf6rtm_run(
            workdir,
            workdir / "results",
            run_id=record.run_id,
            status=record.state,
        )
    except Exception as error:
        raise HTTPException(
            status_code=400, detail=f"could not collect results: {error}"
        ) from error

    return {
        "runId": run_id,
        "components": [entry["name"] for entry in catalog.components],
        "times": len(catalog.times),
        "cells": catalog.ncells,
        "warnings": catalog.warnings,
    }


@router.websocket("/ws/runs/{run_id}")
async def run_events(socket: WebSocket, run_id: str) -> None:
    """Stream a run's progress until it ends."""
    await socket.accept()

    record = run_registry().get(run_id)
    if record is None:
        await socket.send_json({"op": "error", "message": f"no run {run_id}"})
        await socket.close()
        return

    runner = runner_instance()

    # Send the current state first: a client joining mid-run should not sit
    # blank until the next timestep is reported.
    await socket.send_json({"op": "state", **_state(run_id)})

    try:
        async for event in runner.events(run_id):
            await socket.send_json({"op": "progress", **event.as_dict()})
        await socket.send_json({"op": "state", **_state(run_id)})
    except WebSocketDisconnect:
        log.debug("run socket for %s closed by the client", run_id)
    finally:
        # The client may already have gone, which closes the socket for us.
        with contextlib.suppress(RuntimeError):
            await socket.close()
