"""FastAPI application factory.

The API lives under ``/api/v1``; everything else is served from the bundled
frontend in ``mupstudio/_static``. In dev mode the static mount is skipped and
Vite serves the frontend, proxying ``/api`` and ``/ws`` back here.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mupstudio import __version__
from mupstudio.server.routers import chemistry, gis, projects, runs, system, viewport

STATIC_DIR = Path(__file__).resolve().parent.parent / "_static"
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def static_bundle_available() -> bool:
    return (STATIC_DIR / "index.html").exists()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Settle runs left in progress by a previous server, then serve.

    A run recorded as running is not running: this process did not start it and
    nothing is watching it.
    """
    from mupstudio.server.deps import reconcile_runs

    reconcile_runs()
    yield


def create_app(*, dev: bool | None = None) -> FastAPI:
    if dev is None:
        dev = os.environ.get("MUPSTUDIO_DEV") == "1"

    app = FastAPI(
        title="MUP Studio",
        version=__version__,
        summary="Build, run and visualise reactive transport models",
        lifespan=lifespan,
    )
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(chemistry.router, prefix="/api/v1")
    app.include_router(gis.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")
    app.include_router(viewport.router, prefix="/api/v1")

    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEV_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif static_bundle_available():
        # html=True makes unknown paths fall back to index.html for client routing.
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app
