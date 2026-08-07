# MUP Studio

A GUI for building, running and visualising reactive transport models with
[PHT3D](https://www.pht3d.org) and [MF6RTM](https://github.com/p-ortega/mf6rtm).

MUP Studio runs as a local web app: a Python backend that owns FloPy, mf6rtm and the
simulation engines, and a browser frontend that renders model grids directly on the GPU
with WebGPU. Install it with pip, run one command, and it opens in your browser.

> **Status: early development.** The scaffold is in place; the viewport, model builder
> and chemistry editor are being built. Not yet usable for real work.

## Install

```bash
pip install mupstudio
mupstudio get-engines   # downloads mf6, mf2005, gridgen, triangle
mupstudio doctor        # checks everything is where it should be
mupstudio serve         # opens the app in your browser
```

PHT3D is distributed separately (it is GPL-3, unlike this BSD-3 package). Fetch a build
from [dispersivity/pht3d](https://github.com/dispersivity/pht3d/releases) and point
`pht3d_exe` at it in settings, or drop it in the engines directory `mupstudio doctor`
prints.

Requires Python 3.11+ and a browser with WebGPU: Chrome or Edge 113+, Safari 26+, or
Firefox 141+. There is no WebGL fallback — the viewport is built for WebGPU only.

## Development

```bash
just install   # uv sync + pnpm install
just dev       # uvicorn on :8000 and Vite on :5173
just test      # pytest and vitest
just lint      # ruff, mypy, eslint, prettier, tsc
just wheel     # build the wheel, frontend included
```

Without `just`: `uv sync`, `pnpm --dir frontend install`, then
`uv run uvicorn mupstudio.server.app:create_app --factory --reload` alongside
`pnpm --dir frontend dev`.

For backend-only work, `MUPSTUDIO_SKIP_FRONTEND_BUILD=1` lets you install without
building the frontend; run the server with `mupstudio serve --dev` and let Vite serve
the UI.

## License

BSD 3-Clause. PHT3D and MODFLOW binaries are separate programs with their own licenses;
MUP Studio runs them as subprocesses and does not link against them.
