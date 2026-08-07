"""Command line entry point: mupstudio serve | doctor | get-engines | version."""

from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from mupstudio import __version__
from mupstudio.doctor import run_doctor
from mupstudio.settings import engines_dir, settings_path

app = typer.Typer(
    name="mupstudio",
    help="Build, run and visualise reactive transport models.",
    no_args_is_help=True,
    add_completion=False,
)

STATUS_MARK = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}


def _free_port(preferred: int) -> int:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command()
def doctor() -> None:
    """Check that engines, Python dependencies and the frontend bundle are present."""
    report = run_doctor()
    typer.echo(f"mupstudio {report.version} on {report.platform}, python {report.python}")
    typer.echo(f"settings: {settings_path()}")
    typer.echo(f"engines:  {engines_dir()}")
    typer.echo("")
    for check in report.checks:
        typer.echo(f"  [{STATUS_MARK[check.status]}] {check.name}: {check.detail}")
        if check.fix_hint and check.status != "ok":
            typer.echo(f"         -> {check.fix_hint}")
    if not report.ok:
        typer.echo("\nsome required checks failed", err=True)
        raise typer.Exit(code=1)


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port to bind; a free one is picked if taken")] = 8000,
    host: Annotated[str, typer.Option(help="Interface to bind")] = "127.0.0.1",
    browser: Annotated[bool, typer.Option(help="Open a browser once the server is up")] = True,
    dev: Annotated[
        bool, typer.Option(help="Dev mode: skip static mount, allow Vite origin")
    ] = False,
    check: Annotated[
        bool, typer.Option(help="Start, verify /health and the frontend, then exit")
    ] = False,
) -> None:
    """Run the local server and open the app."""
    import uvicorn

    from mupstudio.server.app import create_app, static_bundle_available

    if not dev and not static_bundle_available():
        typer.echo(
            "no frontend bundle found; build it with 'pnpm --dir frontend build' "
            "or run with --dev alongside the Vite dev server",
            err=True,
        )
        raise typer.Exit(code=1)

    if dev:
        os.environ["MUPSTUDIO_DEV"] = "1"

    if check:
        _serve_check(create_app(dev=dev), host=host, port=_free_port(port))
        return

    chosen = _free_port(port)
    if chosen != port:
        typer.echo(f"port {port} is busy, using {chosen}")
    url = f"http://{host}:{chosen}"
    typer.echo(f"mupstudio serving on {url}")

    if browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(create_app(dev=dev), host=host, port=chosen, log_level="info")


def _serve_check(application: object, *, host: str, port: int) -> None:
    """Start the real server, verify it answers, then shut it down.

    Used by the CI install smoke test, so it leans on the standard library
    only: an HTTP client dependency here would not be exercised by a normal
    `pip install mupstudio`.
    """
    import urllib.error
    import urllib.request

    import uvicorn

    config = uvicorn.Config(application, host=host, port=port, log_level="warning")  # type: ignore[arg-type]
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    def fetch(path: str) -> tuple[int, bytes]:
        with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=5) as response:
            return response.status, response.read()

    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if time.monotonic() > deadline or not thread.is_alive():
                typer.echo("server did not start within 30s", err=True)
                raise typer.Exit(code=1)
            time.sleep(0.05)

        try:
            status, body = fetch("/api/v1/health")
        except urllib.error.URLError as error:
            typer.echo(f"/api/v1/health did not respond: {error}", err=True)
            raise typer.Exit(code=1) from error
        if status != 200:
            typer.echo(f"/api/v1/health returned {status}", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"health: {body.decode()}")

        try:
            status, body = fetch("/")
        except urllib.error.URLError as error:
            typer.echo(f"/ did not respond: {error}", err=True)
            raise typer.Exit(code=1) from error
        if status != 200 or b'<div id="root">' not in body:
            typer.echo(f"/ returned {status} without the app root element", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"frontend: {len(body)} bytes")
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    typer.echo("serve --check passed")


@app.command("new")
def new_project(
    name: Annotated[str, typer.Argument(help="Project name")],
    engine: Annotated[str, typer.Option(help="mf6rtm or pht3d")] = "mf6rtm",
    cells: Annotated[int, typer.Option(help="Cells along the column")] = 50,
    length: Annotated[float, typer.Option(help="Column length")] = 0.5,
    directory: Annotated[Path | None, typer.Option(help="Where to create it")] = None,
) -> None:
    """Create a project as a 1D column, the shape most benchmarks use.

    Writes a directory of TOML you can open in the app or edit by hand.
    """
    from mupstudio.schema.templates import starter_column
    from mupstudio.store import projectstore

    if engine not in {"mf6rtm", "pht3d"}:
        typer.echo(f"unknown engine {engine!r}; choose mf6rtm or pht3d", err=True)
        raise typer.Exit(code=1)

    project = starter_column(
        name,
        engine=engine,  # type: ignore[arg-type]
        cells=cells,
        length=length,
    )

    try:
        created = projectstore.create(directory or Path.cwd(), name, project)
    except projectstore.ProjectError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"created {created}")
    typer.echo(f"  {project.describe()}")
    for file in sorted(path.name for path in created.iterdir() if path.suffix == ".toml"):
        typer.echo(f"  {file}")


@app.command("show")
def show_project(
    directory: Annotated[Path, typer.Argument(help="A .mup project directory")],
) -> None:
    """Validate a project and print what it contains."""
    from mupstudio.store import projectstore

    try:
        project = projectstore.load(directory)
    except projectstore.ProjectError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(project.describe())
    typer.echo(f"  simulated time: {project.time.total_time} {project.meta.time_unit}")
    if project.flow.packages:
        typer.echo("  boundaries:")
        for package in project.flow.packages:
            typer.echo(f"    {package.id} ({package.kind})")
    else:
        typer.echo("  boundaries: none yet")


@app.command("import-run")
def import_run(
    workdir: Annotated[Path, typer.Argument(help="A finished mf6rtm/MODFLOW 6 run directory")],
    label: Annotated[str | None, typer.Option(help="Name to show in the app")] = None,
) -> None:
    """Register an existing run directory and collect its results.

    Use this to look at a model you ran outside mupstudio: it reads the grid
    and output in place and writes the normalized results the viewport reads.
    """
    import uuid

    from mupstudio.engines.mf6rtm import results as reader
    from mupstudio.jobs.registry import RunRecord, RunRegistry
    from mupstudio.results.store import collect_mf6rtm_run

    workdir = workdir.expanduser().resolve()
    if not reader.looks_like_run_output(workdir):
        typer.echo(
            f"{workdir} does not look like mf6rtm output: expected a .grb grid file "
            "and at least one .ucn concentration file",
            err=True,
        )
        raise typer.Exit(code=1)

    run_id = f"r_{uuid.uuid4().hex[:10]}"
    registry = RunRegistry()
    registry.add(
        RunRecord(
            run_id=run_id,
            engine="mf6rtm",
            label=label or workdir.name,
            workdir=str(workdir),
            state="succeeded",
        )
    )

    typer.echo(f"reading {workdir}")
    catalog = collect_mf6rtm_run(workdir, workdir / "results", run_id=run_id)

    typer.echo(f"run id:     {run_id}")
    typer.echo(f"components: {', '.join(str(entry['name']) for entry in catalog.components)}")
    typer.echo(f"cells:      {catalog.ncells:,} in {catalog.nlay} layers")
    typer.echo(f"timesteps:  {len(catalog.times)}")
    for warning in catalog.warnings:
        typer.echo(f"warning:    {warning}", err=True)
    typer.echo(f"\nopen it with: mupstudio serve   then pick '{label or workdir.name}'")


@app.command()
def runs() -> None:
    """List runs mupstudio knows about."""
    from mupstudio.jobs.registry import RunRegistry

    records = RunRegistry().recent(50)
    if not records:
        typer.echo("no runs yet; add one with: mupstudio import-run <directory>")
        return

    for record in records:
        results = "results" if record.has_results else "no results"
        typer.echo(
            f"{record.run_id}  {record.state:<10} {record.engine:<8} "
            f"{results:<11} {record.label or record.workdir}"
        )


@app.command("get-engines")
def get_engines(
    pht3d: Annotated[bool, typer.Option(help="Also fetch the PHT3D executable")] = False,
) -> None:
    """Download MODFLOW-family executables into the mupstudio engines directory."""
    target = engines_dir()
    target.mkdir(parents=True, exist_ok=True)

    try:
        from flopy.utils import get_modflow
    except ImportError:
        typer.echo("flopy is required to fetch executables: pip install flopy", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"fetching mf6, libmf6, mf2005, gridgen and triangle into {target}")
    try:
        get_modflow(
            bindir=str(target),
            subset="mf6,libmf6,mf2005,gridgen,triangle",
            quiet=False,
        )
    except Exception as error:
        typer.echo(f"could not fetch executables: {error}", err=True)
        raise typer.Exit(code=1) from error

    if pht3d:
        typer.echo(
            "PHT3D binaries are published separately at "
            "https://github.com/dispersivity/pht3d/releases — "
            "download one and set pht3d_exe in settings, or drop it in "
            f"{target}"
        )


if __name__ == "__main__":
    app()
