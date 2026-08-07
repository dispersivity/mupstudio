"""Viewport data: a REST catalog plus the websocket that streams arrays.

Datasets are addressed by id. ``demo`` is the synthetic grid; anything else is
a run id, served from its collected results. Both go through the same frame
encoder, so the client cannot tell them apart beyond what the catalog says.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from mupstudio.results import datasets as ds
from mupstudio.server.ws.protocol import (
    ClientMessage,
    DoneMessage,
    ErrorMessage,
    GetMesh,
    GetScalar,
    GetScalarBlock,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["viewport"])

_messages = TypeAdapter[ClientMessage](ClientMessage)

DEMO = "demo"


def resolve(dataset_id: str, ncpl: int, nlay: int, ntimes: int) -> ds.Dataset:
    """Find a dataset by id, or say clearly why it cannot be served."""
    if dataset_id == DEMO:
        return ds.demo_dataset(ncpl, nlay, ntimes)

    from mupstudio.jobs.registry import RunRegistry

    record = RunRegistry().get(dataset_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no dataset or run {dataset_id!r}")
    if not record.has_results:
        raise HTTPException(
            status_code=409,
            detail=f"run {dataset_id} has no collected results (state: {record.state})",
        )
    return ds.open_run(record.results_dir)


@router.get("/datasets")
def list_datasets() -> dict[str, Any]:
    """Everything the viewport could be pointed at."""
    from mupstudio.jobs.registry import RunRegistry

    runs = [
        {
            "id": record.run_id,
            "label": record.label,
            "engine": record.engine,
            "state": record.state,
            "startedAt": record.started_at,
            "hasResults": record.has_results,
        }
        for record in RunRegistry().recent(50)
    ]
    return {"demo": {"id": DEMO, "kind": "synthetic"}, "runs": runs}


@router.get("/datasets/{dataset_id}")
def dataset_catalog(
    dataset_id: str,
    ncpl: int = Query(default=20_000, ge=1, le=2_000_000),
    nlay: int = Query(default=6, ge=1, le=200),
    ntimes: int = Query(default=40, ge=1, le=1000),
) -> dict[str, Any]:
    """Grid size, time steps, components and their ranges.

    The size parameters apply only to the demo dataset; they let the perf
    harness ask for a grid far larger than the default without a separate
    endpoint.
    """
    return ds.catalog_of(resolve(dataset_id, ncpl, nlay, ntimes))


@router.websocket("/ws/viewport")
async def viewport_socket(
    socket: WebSocket,
    dataset: str = Query(default=DEMO),
    ncpl: int = Query(default=20_000, ge=1, le=2_000_000),
    nlay: int = Query(default=6, ge=1, le=200),
    ntimes: int = Query(default=40, ge=1, le=1000),
) -> None:
    """Stream mesh and scalar frames on request.

    One socket serves many requests. Each reply is a run of binary frames
    tagged with the request's ``reqId``, ended by a ``done`` message, so the
    client knows when a multi-frame answer is complete.
    """
    await socket.accept()

    try:
        source = resolve(dataset, ncpl, nlay, ntimes)
    except HTTPException as error:
        await socket.send_text(ErrorMessage(message=str(error.detail)).model_dump_json())
        await socket.close()
        return

    try:
        while True:
            raw = await socket.receive_text()
            try:
                message = _messages.validate_json(raw)
            except ValidationError as error:
                await socket.send_text(
                    ErrorMessage(
                        message=f"could not parse request: {error.error_count()} problems"
                    ).model_dump_json()
                )
                continue

            try:
                frames = _frames_for(source, message)
            except (KeyError, IndexError) as error:
                await socket.send_text(
                    ErrorMessage(reqId=message.reqId, message=str(error)).model_dump_json()
                )
                continue

            for frame in frames:
                await socket.send_bytes(frame)
            await socket.send_text(
                DoneMessage(reqId=message.reqId, frames=len(frames)).model_dump_json()
            )
    except WebSocketDisconnect:
        log.debug("viewport socket closed by the client")


def _frames_for(source: ds.Dataset, message: ClientMessage) -> list[bytes]:
    if isinstance(message, GetMesh):
        return ds.mesh_frames(source, message.reqId)
    if isinstance(message, GetScalarBlock):
        return [
            ds.scalar_block_frame(
                source, message.reqId, message.component, max_bytes=message.maxBytes
            )
        ]
    if isinstance(message, GetScalar):
        return [ds.scalar_frame(source, message.reqId, message.component, message.timeIdx)]
    raise KeyError(f"unhandled op {message!r}")
