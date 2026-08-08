"""Build hook that bundles the built frontend into the sdist and the wheel.

The frontend is built with pnpm into ``frontend/dist`` and copied to
``src/mupstudio/_static``, which ``mupstudio serve`` mounts at ``/``.

Both targets carry the bundle, and that is the point. ``uv build`` and ``pip
install .`` build the wheel *from the sdist*, so a sdist without ``_static`` in
it forces every wheel build to re-run pnpm inside an unpacked tarball — needing
node, a package store and a network connection at install time. Shipping the
built bundle in the sdist is what makes ``pip install`` from PyPI a pure Python
operation.

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
        elif self._can_build():
            self._build_frontend()
            self._copy_dist()
        elif index.exists():
            # Nothing here can build it, but the bundle came with the sdist.
            # This is the path `pip install mupstudio` takes on a machine with
            # only Python on it, and it must not need node.
            self.app.display_info(f"cannot build the frontend here; using the bundle in {STATIC}")
        else:
            raise RuntimeError(
                f"{index} is missing and the frontend cannot be built from here. "
                "Run `pnpm --dir frontend build` and copy frontend/dist to "
                "src/mupstudio/_static, or set MUPSTUDIO_SKIP_FRONTEND_BUILD=1 "
                "for a backend-only install."
            )

        if index.exists():
            self._force_include(build_data)

    def _can_build(self) -> bool:
        """Whether the frontend can be built from what is on disk right now."""
        return FRONTEND.joinpath("package.json").exists() and shutil.which("pnpm") is not None

    def _force_include(self, build_data: dict[str, Any]) -> None:
        """Add the bundle to the artifact explicitly.

        `_static` is gitignored (it is generated), and hatchling skips
        gitignored paths when collecting files, so the bundle has to be named
        here or it silently misses the artifact.

        The target path differs by artifact: a wheel unpacks into site-packages
        so the bundle sits at `mupstudio/_static`, while a sdist keeps the
        repository layout and needs `src/` in front of it — otherwise the file
        lands somewhere the wheel build will not look for it.
        """
        inside = "src/mupstudio/_static" if self.target_name == "sdist" else "mupstudio/_static"
        build_data.setdefault("force_include", {})[str(STATIC)] = inside
        self.app.display_info(f"force-included {STATIC} as {inside}")

    def _build_frontend(self) -> None:
        pnpm = shutil.which("pnpm")
        if pnpm is None:  # pragma: no cover - guarded by _can_build
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
