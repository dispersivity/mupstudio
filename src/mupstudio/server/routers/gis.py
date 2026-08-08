"""Importing spatial data and drawing it on a map.

Files arrive one of two ways: uploaded through the browser, or named by path
when the app is being driven from the same machine the data is on, which for a
local tool is most of the time.

Layers go out as GeoJSON in longitude and latitude, because that is what a web
map draws. The projection happens here rather than in the browser: the model's
coordinate system can be anything, pyproj knows them all, and shipping a
projection library to the client to do it a second time would be the same work
in a worse place.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from mupstudio.gisio import ingest, preview
from mupstudio.schema.project import Project
from mupstudio.server.routers.projects import load_project
from mupstudio.store import projectstore

log = logging.getLogger(__name__)
router = APIRouter(tags=["gis"])

# Basemaps offered. Fetched from a third party, so nothing is drawn until one is
# chosen: a local modelling tool should not reach the network because a screen
# happened to open.
#
# Esri's World Imagery and World Terrain are free to use with attribution and
# need no key, which is what makes them usable in an open tool. Google's imagery
# is not: its terms confine it to Google's own APIs and require a billed key per
# user, so it is not offered.
BASEMAPS: list[dict[str, str]] = [
    {
        "id": "esri-imagery",
        "label": "Satellite",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "attribution": "Esri, Maxar, Earthstar Geographics",
        "maxZoom": "19",
    },
    {
        "id": "esri-terrain",
        "label": "Terrain",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Terrain_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "attribution": "Esri, USGS, NOAA",
        "maxZoom": "13",
    },
    {
        "id": "esri-topo",
        "label": "Topographic",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        "attribution": "Esri, HERE, Garmin, USGS",
        "maxZoom": "19",
    },
    {
        "id": "osm",
        "label": "Street map",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "OpenStreetMap contributors",
        "maxZoom": "19",
    },
]


class ImportRequest(BaseModel):
    """Import a file the server can already see, by path."""

    path: str
    label: str = ""
    xColumn: str | None = None
    yColumn: str | None = None


@router.get("/basemaps")
def list_basemaps() -> dict[str, Any]:
    """The basemaps on offer, and what using one means.

    The note travels with the list rather than living in the interface, so
    whatever draws the picker says the same thing about it.
    """
    return {
        "basemaps": BASEMAPS,
        "note": (
            "A basemap is fetched from a third party as you pan, which tells them "
            "roughly where your model is. Nothing is requested until you choose one."
        ),
    }


@router.get("/projects/data")
def list_data(path: str) -> dict[str, Any]:
    """Everything imported into a project."""
    project = load_project(path)
    sources = project.data.sources

    return {
        "sources": [source.model_dump(mode="json") for source in sources],
        "basemap": project.data.basemap,
        "crs": project.meta.crs,
        # Where to point the map when it opens: at the data, if there is any.
        "extent": preview.extent_of(sources, project.meta.crs),
    }


@router.post("/projects/data/import")
def import_by_path(path: str, request: ImportRequest) -> dict[str, Any]:
    """Import a file the server can reach, without uploading it.

    The usual case for a desktop tool: the shapefile is already on this machine,
    and copying it through the browser to a server on the same disk is work for
    nothing.
    """
    return _import(path, Path(request.path).expanduser(), request)


@router.post("/projects/data/upload")
async def import_by_upload(
    path: str,
    # FastAPI reads a multipart form from these declarations, so the calls have
    # to be in the signature; ruff's rule about mutable defaults does not apply
    # to them, since they are markers rather than values.
    file: Annotated[UploadFile, File()],
    label: Annotated[str, Form()] = "",
    xColumn: Annotated[str | None, Form()] = None,
    yColumn: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Import a file sent from the browser."""
    if not file.filename:
        raise HTTPException(status_code=422, detail="the upload has no file name")

    # Written to a scratch directory first: the importer works on paths, and a
    # shapefile in a zip has to exist as a file before it can be unpacked.
    with tempfile.TemporaryDirectory(prefix="mupstudio-upload-") as scratch:
        staged = Path(scratch) / Path(file.filename).name
        with staged.open("wb") as target:
            shutil.copyfileobj(file.file, target)

        return _import(
            path,
            staged,
            ImportRequest(path=str(staged), label=label, xColumn=xColumn, yColumn=yColumn),
        )


def _import(project_path: str, file: Path, request: ImportRequest) -> dict[str, Any]:
    project = load_project(project_path)
    directory = Path(project_path)

    try:
        imported = ingest.import_file(
            file,
            directory,
            source_id=_unique_id(project, file.stem),
            label=request.label,
            colour=project.data.next_colour(),
            x_column=request.xColumn,
            y_column=request.yColumn,
            crs=project.meta.crs,
        )
    except ingest.ImportError_ as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    updated = project.model_copy(
        update={
            "data": project.data.model_copy(
                update={"sources": [*project.data.sources, imported.source]}
            )
        }
    )
    projectstore.save(directory, updated)

    return {
        "source": imported.source.model_dump(mode="json"),
        "warnings": imported.warnings,
    }


@router.get("/projects/data/geojson")
def layer_geojson(path: str, source: str, simplify: bool = True) -> dict[str, Any]:
    """One layer, projected to longitude and latitude for the map."""
    project = load_project(path)

    try:
        found = project.data.source(source)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    try:
        return preview.geojson_for(
            Path(path), found, project_crs=project.meta.crs, simplify=simplify
        )
    except preview.PreviewError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/projects/data/source")
def update_source(path: str, source: str, body: dict[str, Any]) -> dict[str, Any]:
    """Change a layer's appearance: its name, colour or whether it is drawn."""
    project = load_project(path)
    directory = Path(path)

    allowed = {"label", "colour", "visible"}
    unknown = set(body) - allowed
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"cannot change {', '.join(sorted(unknown))}; only {', '.join(sorted(allowed))}",
        )

    sources = []
    found = False
    for item in project.data.sources:
        if item.id == source:
            sources.append(item.model_copy(update=body))
            found = True
        else:
            sources.append(item)

    if not found:
        raise HTTPException(status_code=404, detail=f"no data layer {source!r}")

    updated = project.model_copy(
        update={"data": project.data.model_copy(update={"sources": sources})}
    )
    projectstore.save(directory, updated)
    return {"source": updated.data.source(source).model_dump(mode="json")}


@router.put("/projects/data/basemap")
def set_basemap(path: str, basemap: str | None = None) -> dict[str, Any]:
    """Choose the basemap, or turn it off."""
    known = {item["id"] for item in BASEMAPS}
    if basemap is not None and basemap not in known:
        raise HTTPException(
            status_code=422, detail=f"no basemap {basemap!r}; there is {', '.join(sorted(known))}"
        )

    project = load_project(path)
    if basemap is not None and project.meta.crs is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "this model has no coordinate system, so there is nowhere on Earth to "
                "draw it. Set one on the Grid step, under Domain."
            ),
        )

    updated = project.model_copy(
        update={"data": project.data.model_copy(update={"basemap": basemap})}
    )
    projectstore.save(Path(path), updated)
    return {"basemap": basemap}


@router.delete("/projects/data/source")
def remove_source(path: str, source: str, delete_file: bool = False) -> dict[str, str]:
    """Forget a layer.

    The copied file is left alone unless asked for: removing a layer from the
    map is a common thing to undo, and re-importing is more annoying than a file
    nobody is looking at.
    """
    project = load_project(path)
    directory = Path(path)

    try:
        found = project.data.source(source)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    if delete_file:
        target = ingest.source_path(directory, found)
        if target.exists():
            target.unlink()

    updated = project.model_copy(
        update={
            "data": project.data.model_copy(
                update={"sources": [item for item in project.data.sources if item.id != source]}
            )
        }
    )
    projectstore.save(directory, updated)
    return {"status": "removed"}


def _unique_id(project: Project, stem: str) -> str:
    """A layer id from the file's name, not already taken."""
    cleaned = "".join(item if item.isalnum() or item in "-_" else "_" for item in stem.lower())
    base = cleaned.strip("_") or "layer"

    taken = {item.id for item in project.data.sources}
    if base not in taken:
        return base

    counter = 2
    while f"{base}_{counter}" in taken:
        counter += 1
    return f"{base}_{counter}"
