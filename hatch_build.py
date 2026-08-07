"""Build hook that bundles the built frontend into the wheel.

The frontend is built with pnpm into ``frontend/dist`` and copied to
``src/mupstudio/_static``, which ``mupstudio serve`` mounts at ``/``.

Set ``MUPSTUDIO_SKIP_FRONTEND_BUILD=1`` to reuse whatever is already in
``_static`` (editable installs, backend-only iteration, CI jobs that build the
frontend in a separate step).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

ROOT = Path(__file__).parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
STATIC = ROOT / "src" / "mupstudio" / "_static"


class FrontendBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        index = STATIC / "index.html"

        if os.environ.get("MUPSTUDIO_SKIP_FRONTEND_BUILD"):
            # Backend-only path: editable installs and CI jobs that build the
            # frontend separately. A missing bundle is fine here; `serve` will
            # refuse to start without one unless it is run with --dev.
            state = "reusing existing bundle" if index.exists() else "no bundle present"
            self.app.display_info(f"MUPSTUDIO_SKIP_FRONTEND_BUILD set, {state}")
        else:
            if FRONTEND.joinpath("package.json").exists():
                self._build_frontend()
                self._copy_dist()

            if not index.exists():
                raise RuntimeError(
                    f"{index} is missing. Build the frontend (pnpm --dir frontend build) "
                    "or set MUPSTUDIO_SKIP_FRONTEND_BUILD=1 for a backend-only install."
                )

        if index.exists():
            self._force_include(build_data)

    def _force_include(self, build_data: dict[str, Any]) -> None:
        """Add the bundle to the artifact explicitly.

        `_static` is gitignored (it is generated), and hatchling skips
        gitignored paths when collecting files, so the bundle has to be named
        here or it silently misses the wheel.
        """
        build_data.setdefault("force_include", {})[str(STATIC)] = "mupstudio/_static"
        self.app.display_info(f"force-included {STATIC} as mupstudio/_static")

    def _build_frontend(self) -> None:
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            raise RuntimeError("pnpm not found on PATH; needed to build the frontend")
        self.app.display_info("building frontend with pnpm")
        subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=FRONTEND, check=True)
        subprocess.run([pnpm, "run", "build"], cwd=FRONTEND, check=True)

    def _copy_dist(self) -> None:
        if not DIST.exists():
            raise RuntimeError(f"{DIST} not found after the frontend build")
        if STATIC.exists():
            shutil.rmtree(STATIC)
        shutil.copytree(DIST, STATIC)
        self.app.display_info(f"copied {DIST} to {STATIC}")
