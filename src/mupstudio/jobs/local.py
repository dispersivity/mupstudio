"""Running models as local subprocesses.

Subprocess rather than a thread, always. mf6rtm changes the process working
directory when it solves, and PhreeqcRM keeps state in a shared library that is
global to the process. Two runs in one interpreter would corrupt each other,
and either would corrupt the server.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from mupstudio.jobs.base import JobSpec, Runner
from mupstudio.jobs.progress import ProgressEvent, ProgressTracker, parse_line
from mupstudio.jobs.registry import RunRecord, RunRegistry
from mupstudio.settings import Settings

log = logging.getLogger(__name__)

LOG_NAME = "mupstudio-run.log"
# How long a cancelled process is given to exit before it is killed outright.
TERMINATE_GRACE_SECONDS = 10.0


class LocalRunner(Runner):
    """Runs each job's stages in order, on this machine."""

    def __init__(self, registry: RunRegistry | None = None, settings: Settings | None = None):
        self.registry = registry or RunRegistry()
        self.settings = settings or Settings.load()
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_runs)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._subscribers: dict[str, set[asyncio.Queue[ProgressEvent | None]]] = {}
        self._trackers: dict[str, ProgressTracker] = {}

    # -- submission ----------------------------------------------------------

    async def submit(self, spec: JobSpec) -> RunRecord:
        run_id = f"r_{uuid.uuid4().hex[:10]}"
        spec.workdir.mkdir(parents=True, exist_ok=True)

        record = self.registry.add(
            RunRecord(
                run_id=run_id,
                engine=spec.engine,
                label=spec.label,
                workdir=str(spec.workdir),
                state="queued",
            )
        )
        self._trackers[run_id] = ProgressTracker(spec.total_kper)
        self._tasks[run_id] = asyncio.create_task(self._run(run_id, spec))
        return record

    async def _run(self, run_id: str, spec: JobSpec) -> None:
        async with self._semaphore:
            log_file = self.log_path(run_id, spec.workdir)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            try:
                with log_file.open("w", encoding="utf-8") as sink:
                    for index, stage in enumerate(spec.stages):
                        sink.write(
                            f"--- stage {index + 1}/{len(spec.stages)}: {stage.name or stage.argv[0]}\n"
                        )
                        sink.flush()
                        code = await self._run_stage(run_id, spec, stage, sink)
                        if code != 0:
                            self._finish(
                                run_id, "failed", code, f"{stage.name or 'stage'} exited {code}"
                            )
                            return
            except asyncio.CancelledError:
                self._finish(run_id, "cancelled", None, "cancelled")
                raise
            except FileNotFoundError as error:
                self._finish(run_id, "failed", None, f"executable not found: {error}")
                return
            except Exception as error:  # the run must not take the server down
                log.exception("run %s failed to start", run_id)
                self._finish(run_id, "failed", None, str(error))
                return

            tracker = self._trackers.get(run_id)
            if tracker and tracker.failed:
                self._finish(run_id, "failed", 0, "the engine reported a failure")
            else:
                self._finish(run_id, "succeeded", 0, None)

    async def _run_stage(self, run_id: str, spec: JobSpec, stage, sink) -> int:  # type: ignore[no-untyped-def]
        environment = {**os.environ, **stage.env}
        # Its own session on POSIX, so cancelling reaches child processes too.
        # Windows has no equivalent here and terminates the process directly.
        new_session = sys.platform != "win32"
        process = await asyncio.create_subprocess_exec(
            *stage.argv,
            cwd=str(spec.workdir),
            env=environment,
            # Always a pipe, even with nothing to send: a program that prompts
            # would otherwise read the terminal the server was started from,
            # and wait there forever.
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=new_session,
        )
        if process.stdin is not None:
            if stage.stdin:
                process.stdin.write(stage.stdin.encode())
            # Closed either way, so a program expecting more input sees the end
            # of it rather than blocking.
            process.stdin.close()
        self._processes[run_id] = process
        self.registry.update(run_id, state="running", pid=process.pid)
        self._publish(run_id, ProgressEvent(kind="log", message=f"--- {stage.name} started"))

        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            sink.write(line + "\n")
            sink.flush()

            # Every line goes out as-is so the UI can show live output, and
            # the ones that mean something also go out parsed.
            self._publish(run_id, ProgressEvent(kind="log", message=line))

            event = parse_line(line)
            if event is not None:
                self._trackers.setdefault(run_id, ProgressTracker()).apply(event)
                self._publish(run_id, event)

        return await process.wait()

    # -- control -------------------------------------------------------------

    async def status(self, run_id: str) -> RunRecord | None:
        return self.registry.get(run_id)

    async def cancel(self, run_id: str) -> RunRecord | None:
        record = self.registry.get(run_id)
        if record is None or record.state in {"succeeded", "failed", "cancelled"}:
            return record

        process = self._processes.get(run_id)
        if process is not None and process.returncode is None:
            _terminate(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=TERMINATE_GRACE_SECONDS)
            except TimeoutError:
                log.warning("run %s ignored SIGTERM, killing", run_id)
                _kill(process)
                await process.wait()

        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._finish(run_id, "cancelled", None, "cancelled by the user")
        return self.registry.get(run_id)

    def progress(self, run_id: str) -> dict[str, object] | None:
        tracker = self._trackers.get(run_id)
        return tracker.snapshot() if tracker else None

    async def events(self, run_id: str) -> AsyncIterator[ProgressEvent]:
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        self._subscribers.setdefault(run_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            self._subscribers.get(run_id, set()).discard(queue)

    def log_path(self, run_id: str, workdir: Path | None = None) -> Path:
        if workdir is None:
            record = self.registry.get(run_id)
            if record is None:
                raise KeyError(f"no run {run_id}")
            workdir = Path(record.workdir)
        return workdir / LOG_NAME

    # -- internals -----------------------------------------------------------

    def _publish(self, run_id: str, event: ProgressEvent | None) -> None:
        for queue in self._subscribers.get(run_id, set()):
            queue.put_nowait(event)

    def _finish(self, run_id: str, state, exit_code: int | None, message: str | None) -> None:  # type: ignore[no-untyped-def]
        self.registry.finish(run_id, state, exit_code, message)
        self._publish(run_id, None)
        self._processes.pop(run_id, None)
        self._tasks.pop(run_id, None)


def _terminate(process: asyncio.subprocess.Process) -> None:
    """Ask the process group to stop."""
    if sys.platform == "win32":
        process.terminate()
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()


def _kill(process: asyncio.subprocess.Process) -> None:
    if sys.platform == "win32":
        process.kill()
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()
