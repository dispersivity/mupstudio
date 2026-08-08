"""Projects: list, create, open, validate, write and run.

Long work returns a run id straight away and reports progress over the
websocket. Writing is fast enough to do inline, and the file manifest it returns
is what the Simulate step shows: the point of the preview is that a modeller can
read the input MODFLOW will read before believing any of this.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from mupstudio.compile.compiler import CompiledModel, CompileError, compile_project
from mupstudio.engines.mf6rtm.chemistry import ChemistryError
from mupstudio.engines.mf6rtm.reactive import ReactiveWriteError, write_reactive
from mupstudio.engines.mf6rtm.writer import write_mf6
from mupstudio.jobs.base import JobSpec, Stage
from mupstudio.schema.project import Project
from mupstudio.schema.templates import starter_column
from mupstudio.server.deps import runner_instance
from mupstudio.store import projectstore, registry

if TYPE_CHECKING:
    from mupstudio.settings import Settings

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


def load_project(path: str) -> Project:
    """Read a project, turning a bad path into a 400 rather than a traceback."""
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
    project = load_project(str(directory))
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
    return describe(load_project(path))


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
        "chemistry": {
            "enabled": project.chemistry.enabled,
            "database": project.chemistry.database.name,
            "solutions": len(project.chemistry.solutions),
            "compositions": len(project.chemistry.compositions),
        },
        "data": {"sources": len(project.data.sources), "crs": project.meta.crs},
    }


@router.get("/projects/document")
def read_document(path: str) -> dict[str, Any]:
    """The whole project, as the editors read and write it.

    One document rather than per-section endpoints because validation is
    holistic: a boundary's cell indices are only checkable against the grid, and
    a per-period series only against the stress periods.
    """
    return {"document": load_project(path).model_dump(mode="json")}


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
    project = load_project(path)
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
    project = load_project(path)
    directory = Path(path)

    try:
        model = compile_project(project, root=directory)
    except CompileError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    workdir = directory / "runs" / "latest"

    if project.meta.engine == "pht3d":
        return _write_pht3d(model, workdir)
    manifest = write_mf6(model, workdir)

    written = {
        "workdir": str(manifest.workdir),
        "files": manifest.files,
        "warnings": manifest.warnings,
        "flowName": manifest.flow_name,
        "transportName": manifest.transport_name,
        "reactive": False,
        "components": [],
    }

    if not _is_reactive(project):
        return written

    # Chemistry is attached on top of the tracer model rather than instead of
    # it: mf6rtm reads the simulation back, clones the transport model once per
    # component, and overwrites. Equilibration happens here, so this is also
    # where an impossible solution is first reported.
    try:
        reactive = write_reactive(
            model,
            manifest.workdir,
            flow_name=manifest.flow_name,
            transport_name=manifest.transport_name,
        )
    except (ChemistryError, ReactiveWriteError) as error:
        detail = str(error)
        output = getattr(error, "output", "")
        raise HTTPException(
            status_code=422,
            detail=f"{detail}\n\n{output}".strip() if output else detail,
        ) from error

    written.update(
        {
            "files": reactive.files,
            "reactive": True,
            "components": reactive.components,
            "chemistryLog": reactive.output,
        }
    )
    return written


def _write_pht3d(model: CompiledModel, workdir: Path) -> dict[str, Any]:
    """Write a PHT3D deck.

    No equilibration step, unlike MF6RTM: PHT3D is told its component list
    rather than deriving one, so the whole deck is written here and now.
    """
    from mupstudio.engines.pht3d.build import Pht3dBuildError, build_deck
    from mupstudio.engines.pht3d.ordering import OrderingError
    from mupstudio.engines.pht3d.ph_dat import PhDatError

    try:
        deck = build_deck(model, workdir)
    except (Pht3dBuildError, PhDatError, OrderingError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return {
        "workdir": str(deck.workdir),
        "files": deck.files,
        "warnings": deck.warnings,
        "flowName": "flow",
        "transportName": "trans",
        "reactive": True,
        "components": [item.name for item in deck.components],
    }


def _is_reactive(project: Project) -> bool:
    """Whether this project's chemistry should be written.

    Both switches have to be on: a project can keep its chemistry while a run is
    deliberately made conservative, which is how a tracer test of the same model
    is set up.
    """
    return project.run.reactive and project.chemistry.enabled and bool(project.chemistry.solutions)


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

    project = load_project(path)

    # Off the event loop: writing a reactive model runs PHREEQC through a
    # subprocess and waits for it, which for a large grid is minutes. Doing that
    # inline would freeze every other request, including the websocket carrying
    # progress for runs already going.
    written = await asyncio.to_thread(write_project, path)
    workdir = Path(written["workdir"])

    settings = Settings.load()
    reactive = bool(written["reactive"])

    if project.meta.engine == "pht3d":
        return await _run_pht3d(project, workdir, written, settings)

    if reactive:
        # A reactive run is driven by mf6rtm, which steps MODFLOW through the
        # shared library and calls PHREEQC between steps. It looks for that
        # library in the model directory, so it is put there.
        executable = project.run.executable or str(find_executable("mf6rtm") or "")
        missing = (
            "mf6rtm was not found; it installs with mupstudio, so check the environment "
            "is the one mupstudio was installed into"
        )
        name = "mf6rtm"
    else:
        executable = project.run.executable or str(find_executable("mf6", settings.mf6_exe) or "")
        missing = "mf6 was not found; run 'mupstudio get-engines' or set mf6_exe in settings"
        name = "mf6"

    if not executable:
        raise HTTPException(status_code=409, detail=missing)

    warnings = list(written["warnings"])
    if reactive:
        warnings.extend(_stage_solver_library(workdir, settings))

    runner = runner_instance()
    record = await runner.submit(
        JobSpec(
            stages=[Stage(argv=[executable], name=name)],
            workdir=workdir,
            engine=project.meta.engine,
            label=project.meta.name,
            total_kper=project.time.nper,
            expected_outputs=["*.hds", "*.ucn", "*.grb", "sout.csv"],
        )
    )

    return {
        "runId": record.run_id,
        "workdir": str(workdir),
        "files": written["files"],
        "warnings": warnings,
        "reactive": reactive,
        "components": written["components"],
    }


async def _run_pht3d(
    project: Project, workdir: Path, written: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    """Run a PHT3D model, which takes two programs rather than one.

    MODFLOW-2005 solves the flow and writes the link file; PHT3D then reads that
    and transports through it. They are separate executables, so the run is two
    stages and the second is worth nothing without the first.
    """
    from mupstudio.doctor import find_executable

    stages = []
    for name, configured in (("mf2005", settings.mf2005_exe), ("pht3d", settings.pht3d_exe)):
        found = find_executable(name, configured)
        if found is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{name} was not found; run 'mupstudio get-engines --pht3d' or set "
                    f"{name}_exe in settings"
                ),
            )
        stages.append((name, str(found)))

    warnings = list(written["warnings"])
    warnings.extend(_stage_database(project, workdir))

    runner = runner_instance()
    record = await runner.submit(
        JobSpec(
            stages=[
                # Both read their name file from standard input rather than
                # from an argument, which is how these two programs have always
                # been driven.
                Stage(argv=[executable], name=name, stdin=f"{_name_file(name)}\n")
                for name, executable in stages
            ],
            workdir=workdir,
            engine="pht3d",
            label=project.meta.name,
            total_kper=project.time.nper,
            expected_outputs=["*.hds", "PHT3D*.UCN", "*.ftl"],
        )
    )

    return {
        "runId": record.run_id,
        "workdir": str(workdir),
        "files": written["files"],
        "warnings": warnings,
        "reactive": True,
        "components": written["components"],
    }


def _name_file(program: str) -> str:
    return "flow.nam" if program == "mf2005" else "pht3d.nam"


def _stage_database(project: Project, workdir: Path) -> list[str]:
    """Copy the PHREEQC database next to the model, where PHT3D looks for it."""
    import shutil

    from mupstudio.chemdb import cache

    name = project.chemistry.database.name
    try:
        index = cache.load_by_name(name)
    except FileNotFoundError as error:
        return [str(error)]

    destination = workdir / Path(index.path).name
    if not destination.exists():
        shutil.copyfile(index.path, destination)
    return []


def _stage_solver_library(workdir: Path, settings: Settings) -> list[str]:
    """Put libmf6 next to the model, which is where mf6rtm looks for it.

    Copied rather than pointed at, because the run directory is what gets
    shipped to a cluster and a run that carries its own solver is one that
    still works when it lands there.
    """
    import shutil

    from mupstudio.doctor import find_executable as find

    if any(workdir.glob("libmf6*")):
        return []

    mf6 = find("mf6", settings.mf6_exe)
    candidates = sorted(mf6.parent.glob("libmf6*")) if mf6 else []
    if not candidates:
        return [
            "libmf6 was not found next to mf6, so mf6rtm will look for it on the "
            "library path; run 'mupstudio get-engines' if the run cannot start"
        ]

    shutil.copyfile(candidates[0], workdir / candidates[0].name)
    return []
