"""Turning a selection into the cells it means.

The browser needs this before anything is saved. Someone drawing a river
boundary wants to see which cells it lands on while they are still choosing the
buffer, and someone typing a range wants to know it covers eleven cells and not
a hundred and eleven. Resolving it here rather than in the browser keeps one
implementation of the rules: the same code that answers this question answers
it again when the model is written, so the preview cannot disagree with what
runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mupstudio.grids.select import SelectionError, cells_under_shape
from mupstudio.schema.grid import StructuredGrid
from mupstudio.schema.project import Project
from mupstudio.schema.selection import CellSelection, describe
from mupstudio.server.routers.projects import load_project

router = APIRouter(tags=["selection"])

# Sent back as an explicit list so the viewport can highlight them. Above this
# the list is summarised instead: a hundred thousand triples is megabytes of
# JSON to draw a shape the user can already see, and the count is the part that
# actually informs the decision.
MAX_LISTED = 20_000


class SelectionRequest(BaseModel):
    selection: CellSelection


class SelectionResult(BaseModel):
    """What a selection resolves to, in the terms the screen uses."""

    count: int
    summary: str
    # One-based (layer, row, column), matching what the rest of the UI shows.
    cells: list[tuple[int, int, int]] = Field(default_factory=list)
    truncated: bool = False
    problem: str | None = None


@router.post("/projects/selection/resolve")
def resolve(path: str, request: SelectionRequest) -> SelectionResult:
    """Which cells a selection covers, right now, on this project's grid."""
    project = load_project(path)

    if not isinstance(project.grid, StructuredGrid):
        raise HTTPException(422, f"cannot resolve a selection on a {project.grid.kind} grid")

    try:
        cells = resolve_selection(Path(path), request.selection, project)
    except SelectionError as error:
        # A shape that does not reach the grid is a normal thing to be told
        # while adjusting one, not a server error.
        return SelectionResult(count=0, summary="no cells", problem=str(error))

    truncated = len(cells) > MAX_LISTED
    return SelectionResult(
        count=len(cells),
        summary=describe(request.selection),
        cells=cells[:MAX_LISTED],
        truncated=truncated,
    )


def resolve_selection(path: Path, selection: Any, project: Project) -> list[tuple[int, int, int]]:
    """One-based cells for any selection kind.

    Delegates to the compiler for index-based kinds so there is no second
    implementation of what a range means, and to the grid intersector for a
    shape.
    """
    if selection.kind == "cells":
        return [
            (layer, row, column)
            for layer in selection.layers
            for row in selection.rows
            for column in selection.columns
        ]

    if selection.kind == "list":
        return list(selection.indices)

    source = next((item for item in project.data.sources if item.id == selection.source), None)
    if source is None:
        raise SelectionError(f"no data source {selection.source!r} to select cells with")

    assert isinstance(project.grid, StructuredGrid)
    mask = cells_under_shape(path, selection, source, project.grid, project_crs=project.meta.crs)

    import numpy as np

    rows, columns = np.nonzero(mask)
    return [
        (layer, int(row) + 1, int(column) + 1)
        for layer in selection.layers
        for row, column in zip(rows, columns, strict=True)
    ]
