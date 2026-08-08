"""Health, environment diagnostics and user settings."""

from __future__ import annotations

from fastapi import APIRouter

from mupstudio import __version__
from mupstudio.doctor import DoctorReport, run_doctor
from mupstudio.settings import Settings

router = APIRouter(tags=["system"])


# HEAD as well as GET. Starlette adds HEAD to a plain GET route; FastAPI does
# not, so an endpoint whose entire job is to answer "are you up" refuses the
# method that every uptime checker, load balancer and wait-for-server script
# reaches for first. It cost half an hour of CI a run before anyone noticed.
@router.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/doctor", response_model=DoctorReport)
def doctor() -> DoctorReport:
    return run_doctor()


@router.get("/settings", response_model=Settings)
def get_settings() -> Settings:
    return Settings.load()


@router.put("/settings", response_model=Settings)
def put_settings(settings: Settings) -> Settings:
    settings.save()
    return settings
