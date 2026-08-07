"""Viewport data: a REST catalog plus the websocket that streams arrays."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from mupstudio.results.demo import Dataset, demo_dataset
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


@router.get("/datasets/demo")
def demo_catalog(
    ncpl: int = Query(default=20_000, ge=1, le=2_000_000),
    nlay: int = Query(default=6, ge=1, le=200),
    ntimes: int = Query(default=40, ge=1, le=1000),
) -> dict[str, object]:
    """Describe the demo dataset: grid size, time steps, components and ranges.

    The size parameters exist so the perf harness can ask for a grid far larger
    than the default without a separate endpoint.
    """
    return demo_dataset(ncpl, nlay, ntimes).catalog()


@router.websocket("/ws/viewport")
async def viewport_socket(
    socket: WebSocket,
    ncpl: int = Query(default=20_000, ge=1, le=2_000_000),
    nlay: int = Query(default=6, ge=1, le=200),
    ntimes: int = Query(default=40, ge=1, le=1000),
) -> None:
    """Stream mesh and scalar frames on request.

    One socket serves many requests. Each reply is a run of binary frames
    tagged with the request's ``reqId``, terminated by a ``done`` message, so
    the client knows when a multi-frame answer is complete.
    """
    await socket.accept()
    dataset = demo_dataset(ncpl, nlay, ntimes)

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
                frames = _frames_for(dataset, message)
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


def _frames_for(dataset: Dataset, message: ClientMessage) -> list[bytes]:
    if isinstance(message, GetMesh):
        return dataset.mesh_frames(message.reqId)
    if isinstance(message, GetScalarBlock):
        return [
            dataset.scalar_block_frame(message.reqId, message.component, max_bytes=message.maxBytes)
        ]
    if isinstance(message, GetScalar):
        return [dataset.scalar_frame(message.reqId, message.component, message.timeIdx)]
    raise HTTPException(status_code=400, detail=f"unhandled op {message!r}")
