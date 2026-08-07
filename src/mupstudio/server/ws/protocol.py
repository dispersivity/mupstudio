"""Control messages exchanged over the viewport websocket.

Text frames carry these JSON messages; binary frames carry arrays (see
``frames.py``). Requests carry a ``reqId`` which is echoed in every frame sent
in reply, so a client can match a stream of frames to the request that asked
for them without relying on ordering.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class GetMesh(BaseModel):
    """Ask for the grid geometry. Answered with several binary frames."""

    op: Literal["get_mesh"]
    reqId: int
    dataset: str = "demo"


class GetScalarBlock(BaseModel):
    """Ask for every timestep of one component, for GPU preload."""

    op: Literal["get_scalar_block"]
    reqId: int
    dataset: str = "demo"
    component: str
    maxBytes: int | None = Field(
        default=None,
        ge=1,
        description="Budget for the reply. Timesteps are decimated to fit rather than truncated.",
    )


class GetScalar(BaseModel):
    """Ask for a single timestep, e.g. to refine one the block decimated away."""

    op: Literal["get_scalar"]
    reqId: int
    dataset: str = "demo"
    component: str
    timeIdx: int = Field(ge=0)


ClientMessage = Annotated[
    GetMesh | GetScalarBlock | GetScalar,
    Field(discriminator="op"),
]


class ErrorMessage(BaseModel):
    """Sent instead of frames when a request cannot be served."""

    op: Literal["error"] = "error"
    reqId: int | None = None
    message: str


class DoneMessage(BaseModel):
    """Marks the end of the frames answering one request."""

    op: Literal["done"] = "done"
    reqId: int
    frames: int
