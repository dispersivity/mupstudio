"""Projects: list, create, open, validate, write and run.

Long work returns a run id straight away and reports progress over the
websocket. Writing is fast enough to do inline, and the file manifest it returns
is what the Simulate step shows: the point of the preview is that a modeller can
read the input MODFLOW will read before believing any of this.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from mupstudio.compile.compiler import CompileError, compile_project
from mupstudio.engines.mf6rtm.writer import write_mf6
from mupstudio.jobs.base import JobSpec, Stage
from mupstudio.schema.project import Project
from mupstudio.schema.templates import starter_column
from mupstudio.server.deps import runner_instance
from mupstudio.store import projectstore, registry

log = logging.getLogger(__name__)
router = APIRouter(tags=["projects"])

# How much of a written input file to send for preview. Enough for any hand-read
# package; an array-heavy file is truncated with a note rather than streamed.
PREVIEW_LIMIT = 200_000


class NewProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    engine: str = "mf6rtm"
    parent: str | None = Field(default=None, description="Where to create it; cwd if omitted")
    cells: int = Field(default=50, ge=1, le=100_000)
    length: float = Field(default=0.5, gt=0)
    perlen: float = Field(default=1.0, gt=0)
    nstp: int = Field(default=10, ge=1)
    withBoundaries: bool = Field(
        default=True,
        description="Add inflow and outflow, so the project runs and shows something",
    )


class OpenProjectRequest(BaseModel):
    path: str


class ProjectSummary(BaseModel):
    path: str
    name: str
    engine: str
    description: str = ""
    exists: bool = True
    lastOpened: str | None = None


def _summary(entry: registry.ProjectEntry) -> ProjectSummary:
    return ProjectSummary(
        path=str(entry.path),
        name=entry.name,
        engine=entry.engine,
        exists=entry.exists,
        lastOpened=entry.last_opened,
    )


def _load(path: str) -> Project:
    try:
        return projectstore.load(Path(path))
    except projectstore.ProjectError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/projects")
def list_projects() -> dict[str, Any]:
    """Projects this machine has opened before."""
    return {"projects": [_summary(entry).model_dump() for entry in registry.entries()]}


@router.post("/projects", status_code=201)
def create_project(request: NewProjectRequest) -> dict[str, Any]:
    """Create a project as a 1D column, the shape most benchmarks use."""
    if request.engine not in {"mf6rtm", "pht3d"}:
        raise HTTPException(status_code=422, detail=f"unknown engine {request.engine!r}")

    project = starter_column(
        request.name,
        engine=request.engine,  # type: ignore[arg-type]
        cells=request.cells,
        length=request.length,
        perlen=request.perlen,
        nstp=request.nstp,
        with_boundaries=request.withBoundaries,
    )

    parent = Path(request.parent).expanduser() if request.parent else Path.cwd()
    try:
        directory = projectstore.create(parent, request.name, project)
    except projectstore.ProjectError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    entry = registry.remember(directory, name=project.meta.name, engine=project.meta.engine)
    return {"project": _summary(entry).model_dump(), "detail": describe(project)}


@router.post("/projects/open")
def open_project(request: OpenProjectRequest) -> dict[str, Any]:
    """Remember an existing project directory and return what it contains."""
    directory = Path(request.path).expanduser()
    project = _load(str(directory))
    entry = registry.remember(directory, name=project.meta.name, engine=project.meta.engine)
    return {"project": _summary(entry).model_dump(), "detail": describe(project)}


@router.delete("/projects")
def forget_project(path: str) -> dict[str, str]:
    """Drop a project from the list. Nothing on disk is touched."""
    registry.forget(Path(path))
    return {"status": "forgotten"}


@router.get("/projects/detail")
def project_detail(path: str) -> dict[str, Any]:
    """Everything the Project step displays."""
    return describe(_load(path))


def describe(project: Project) -> dict[str, Any]:
    """A project reduced to what the UI shows."""
    grid = project.grid
    return {
        "name": project.meta.name,
        "engine": project.meta.engine,
        "description": project.meta.description,
        "summary": project.describe(),
        "lengthUnit": project.meta.length_unit,
        "timeUnit": project.meta.time_unit,
        "grid": {
            "kind": grid.kind,
            "nlay": grid.nlay,
            "nrow": getattr(grid, "nrow", None),
            "ncol": getattr(grid, "ncol", None),
            "ncells": grid.ncells,
        },
        "time": {
            "nper": project.time.nper,
            "total": project.time.total_time,
            "periods": [period.model_dump() for period in project.time.periods],
        },
        "boundaries": [
            {"id": package.id, "kind": package.kind} for package in project.flow.packages
        ],
        "transport": {
            "advection": project.transport.advection_scheme,
            "dispersion": project.transport.dispersion.enabled,
            "dualPorosity": project.transport.dual_porosity is not None,
        },
    }


@router.get("/projects/document")
def read_document(path: str) -> dict[str, Any]:
    """The whole project, as the editors read and write it.

    One document rather than per-section endpoints because validation is
    holistic: a boundary's cell indices are only checkable against the grid, and
    a per-period series only against the stress periods.
    """
    return {"document": _load(path).model_dump(mode="json")}


@router.put("/projects/document")
def write_document(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Validate an edited project and save it if it holds up.

    An invalid edit is reported field by field and never reaches disk, so a
    project on disk is always one that loads.
    """
    directory = Path(path)
    if not projectstore.is_project(directory):
        raise HTTPException(status_code=404, detail=f"{path} is not a project")

    try:
        project = Project.model_validate(body.get("document", body))
    except ValidationError as error:
        return {
            "ok": False,
            "problems": [
                {
                    "field": ".".join(str(part) for part in item["loc"]),
                    "message": item["msg"],
                }
                for item in error.errors()
            ],
        }

    projectstore.save(directory, project)
    return {
        "ok": True,
        "problems": [],
        "document": project.model_dump(mode="json"),
        "detail": describe(project),
    }


@router.post("/projects/validate")
def validate_project(path: str) -> dict[str, Any]:
    """Compile the project without writing anything.

    Loading already enforces the schema, so this reports what compiling would
    warn about: a zone field with no geometry yet, a boundary kind not written.
    """
    project = _load(path)
    try:
        model = compile_project(project, root=Path(path))
    except CompileError as error:
        return {"ok": False, "errors": [str(error)], "warnings": []}

    return {
        "ok": True,
        "errors": [],
        "warnings": model.warnings,
        "cells": model.grid.ncells,
        "boundaries": [
            {"id": boundary.id, "kind": boundary.kind, "cells": boundary.cell_count}
            for boundary in model.boundaries
        ],
    }


@router.post("/projects/write")
def write_project(path: str) -> dict[str, Any]:
    """Write engine input into the project's runs directory."""
    project = _load(path)
    directory = Path(path)

    if project.meta.engine != "mf6rtm":
        raise HTTPException(
            status_code=501,
            detail=f"writing input for {project.meta.engine} is not implemented yet",
        )

    try:
        model = compile_project(project, root=directory)
    except CompileError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    workdir = directory / "runs" / "latest"
    manifest = write_mf6(model, workdir)

    return {
        "workdir": str(manifest.workdir),
        "files": manifest.files,
        "warnings": manifest.warnings,
        "flowName": manifest.flow_name,
        "transportName": manifest.transport_name,
    }


@router.get("/projects/file")
def read_written_file(path: str, name: str) -> dict[str, Any]:
    """One written input file, for the preview.

    Reading is confined to the project's runs directory: the preview exists to
    show what was generated, not to browse the filesystem.
    """
    workdir = (Path(path) / "runs" / "latest").resolve()
    target = (workdir / name).resolve()

    if not target.is_relative_to(workdir):
        raise HTTPException(status_code=400, detail="that file is outside the run directory")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no written file named {name}")

    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > PREVIEW_LIMIT
    return {
        "name": name,
        "bytes": target.stat().st_size,
        "truncated": truncated,
        "content": content[:PREVIEW_LIMIT],
    }


@router.post("/projects/run")
async def run_project(path: str) -> dict[str, Any]:
    """Write the input, then start the engine on it.

    Returns as soon as the process is launched. Progress arrives over the
    websocket; the run id is how the results are found afterwards.
    """
    from mupstudio.doctor import find_executable
    from mupstudio.settings import Settings

    project = _load(path)
    written = write_project(path)
    workdir = Path(written["workdir"])

    executable = project.run.executable or str(
        find_executable("mf6", Settings.load().mf6_exe) or ""
    )
    if not executable:
        raise HTTPException(
            status_code=409,
            detail="mf6 was not found; run 'mupstudio get-engines' or set mf6_exe in settings",
        )

    runner = runner_instance()
    record = await runner.submit(
        JobSpec(
            stages=[Stage(argv=[executable], name="mf6")],
            workdir=workdir,
            engine=project.meta.engine,
            label=project.meta.name,
            total_kper=project.time.nper,
            expected_outputs=["*.hds", "*.ucn", "*.grb"],
        )
    )

    return {
        "runId": record.run_id,
        "workdir": str(workdir),
        "files": written["files"],
        "warnings": written["warnings"],
    }
