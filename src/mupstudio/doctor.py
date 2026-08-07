"""Environment diagnostics shared by the CLI and the /doctor endpoint.

Every check reports a status, what was found, and how to fix it when it wasn't.
Executables are located in this order: the user's explicit setting, the
mupstudio engines directory, then PATH.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mupstudio import __version__
from mupstudio.settings import Settings, engines_dir

Status = Literal["ok", "warn", "fail"]


class Check(BaseModel):
    name: str
    status: Status
    detail: str
    fix_hint: str | None = None


class DoctorReport(BaseModel):
    version: str
    platform: str
    python: str
    checks: list[Check]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


def find_executable(name: str, configured: str | None = None) -> Path | None:
    """Resolve an engine executable: explicit setting, engines dir, then PATH."""
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate

    suffix = ".exe" if platform.system() == "Windows" else ""
    candidate = engines_dir() / f"{name}{suffix}"
    if candidate.is_file():
        return candidate

    found = shutil.which(name)
    return Path(found) if found else None


def _check_executable(name: str, configured: str | None, *, required: bool, fix_hint: str) -> Check:
    path = find_executable(name, configured)
    if path is not None:
        return Check(name=name, status="ok", detail=str(path))
    return Check(
        name=name,
        status="fail" if required else "warn",
        detail="not found",
        fix_hint=fix_hint,
    )


def _check_import(module: str, *, fix_hint: str) -> Check:
    if importlib.util.find_spec(module) is None:
        return Check(name=module, status="fail", detail="not importable", fix_hint=fix_hint)
    return Check(name=module, status="ok", detail="importable")


def run_doctor(settings: Settings | None = None) -> DoctorReport:
    settings = settings or Settings.load()
    get_modflow_hint = "run: mupstudio get-engines"

    checks = [
        _check_import("flopy", fix_hint="pip install flopy"),
        _check_import("mf6rtm", fix_hint="pip install mf6rtm"),
        _check_import("phreeqcrm", fix_hint="pip install phreeqcrm"),
        _check_executable("mf6", settings.mf6_exe, required=False, fix_hint=get_modflow_hint),
        _check_executable("mf2005", settings.mf2005_exe, required=False, fix_hint=get_modflow_hint),
        _check_executable(
            "gridgen", settings.gridgen_exe, required=False, fix_hint=get_modflow_hint
        ),
        _check_executable(
            "pht3d",
            settings.pht3d_exe,
            required=False,
            fix_hint="run: mupstudio get-engines --pht3d, or set pht3d_exe in settings",
        ),
        _check_static_bundle(),
    ]

    return DoctorReport(
        version=__version__,
        platform=f"{platform.system()} {platform.machine()}",
        python=sys.version.split()[0],
        checks=checks,
    )


def _check_static_bundle() -> Check:
    from mupstudio.server.app import STATIC_DIR, static_bundle_available

    if static_bundle_available():
        return Check(name="frontend bundle", status="ok", detail=str(STATIC_DIR))
    return Check(
        name="frontend bundle",
        status="warn",
        detail=f"no index.html in {STATIC_DIR}",
        fix_hint="build it with: pnpm --dir frontend build (not needed in dev mode)",
    )
