"""The run manager, exercised with real subprocesses.

Short python one-liners stand in for an engine: they are fast, and they print
the same shape of output a real model does, which is all the runner reads.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from mupstudio.jobs.base import JobSpec, Stage
from mupstudio.jobs.local import LocalRunner
from mupstudio.jobs.registry import RunRecord, RunRegistry
from mupstudio.settings import Settings

STEP_LINE = "Transport       | Stress period:  {kper}     | Time step:      1"


def python_stage(code: str, name: str = "fake engine") -> Stage:
    return Stage(argv=[sys.executable, "-c", code], name=name)


def spec(tmp_path: Path, *stages: Stage, total_kper: int | None = None) -> JobSpec:
    return JobSpec(
        stages=list(stages),
        workdir=tmp_path / "work",
        engine="fake",
        label="test",
        total_kper=total_kper,
    )


@pytest.fixture()
def runner(tmp_path: Path) -> LocalRunner:
    return LocalRunner(
        registry=RunRegistry(tmp_path / "runs.db"),
        settings=Settings(max_concurrent_runs=2),
    )


async def wait_for(runner: LocalRunner, run_id: str, timeout: float = 30.0) -> RunRecord:
    """Poll until the run reaches a terminal state."""
    async with asyncio.timeout(timeout):
        while True:
            record = await runner.status(run_id)
            assert record is not None
            if record.state in {"succeeded", "failed", "cancelled", "unknown"}:
                return record
            await asyncio.sleep(0.02)


class TestSuccess:
    async def test_a_clean_run_succeeds(self, runner: LocalRunner, tmp_path: Path) -> None:
        record = await runner.submit(spec(tmp_path, python_stage("print('done')")))

        finished = await wait_for(runner, record.run_id)

        assert finished.state == "succeeded"
        assert finished.exit_code == 0
        assert finished.ended_at

    async def test_output_is_captured_to_a_log(self, runner: LocalRunner, tmp_path: Path) -> None:
        record = await runner.submit(spec(tmp_path, python_stage("print('hello from the engine')")))
        await wait_for(runner, record.run_id)

        log = runner.log_path(record.run_id).read_text()

        assert "hello from the engine" in log

    async def test_stages_run_in_order(self, runner: LocalRunner, tmp_path: Path) -> None:
        record = await runner.submit(
            spec(
                tmp_path,
                python_stage("print('first')", name="flow"),
                python_stage("print('second')", name="transport"),
            )
        )
        await wait_for(runner, record.run_id)

        log = runner.log_path(record.run_id).read_text()

        assert log.index("first") < log.index("second")

    async def test_runs_in_its_own_working_directory(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        job = spec(tmp_path, python_stage("import os; print(os.getcwd())"))
        record = await runner.submit(job)
        await wait_for(runner, record.run_id)

        log = runner.log_path(record.run_id).read_text()

        assert str(job.workdir.resolve()) in log


class TestFailure:
    async def test_a_nonzero_exit_fails_the_run(self, runner: LocalRunner, tmp_path: Path) -> None:
        record = await runner.submit(spec(tmp_path, python_stage("raise SystemExit(3)")))

        finished = await wait_for(runner, record.run_id)

        assert finished.state == "failed"
        assert finished.exit_code == 3

    async def test_a_later_stage_does_not_run_after_a_failure(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        record = await runner.submit(
            spec(
                tmp_path,
                python_stage("raise SystemExit(1)", name="flow"),
                python_stage("print('should not appear')", name="transport"),
            )
        )
        await wait_for(runner, record.run_id)

        assert "should not appear" not in runner.log_path(record.run_id).read_text()

    async def test_a_missing_executable_is_reported_not_raised(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        record = await runner.submit(
            spec(tmp_path, Stage(argv=["definitely-not-an-engine"], name="ghost"))
        )

        finished = await wait_for(runner, record.run_id)

        assert finished.state == "failed"
        assert "not found" in (finished.message or "")

    async def test_an_engine_that_reports_failure_in_its_output_fails(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        """Exit code 0 is not proof of success: mf6rtm says so in its output."""
        record = await runner.submit(
            spec(tmp_path, python_stage("print('SOMETHING WENT WRONG. BUMMER')"))
        )

        finished = await wait_for(runner, record.run_id)

        assert finished.state == "failed"


class TestProgress:
    async def test_progress_follows_the_engine_output(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        code = ";".join(f"print({STEP_LINE.format(kper=kper)!r}, flush=True)" for kper in (1, 2, 3))
        record = await runner.submit(spec(tmp_path, python_stage(code), total_kper=3))
        await wait_for(runner, record.run_id)

        progress = runner.progress(record.run_id)

        assert progress is not None
        assert progress["kper"] == 3
        assert progress["fraction"] == pytest.approx(1.0)

    async def test_subscribers_receive_step_events(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        code = ";".join(f"print({STEP_LINE.format(kper=kper)!r}, flush=True)" for kper in (1, 2))
        record = await runner.submit(spec(tmp_path, python_stage(code)))

        seen = [event async for event in runner.events(record.run_id)]

        assert any(event.kper == 2 for event in seen)


class TestCancellation:
    async def test_cancelling_stops_a_running_job(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        record = await runner.submit(
            spec(tmp_path, python_stage("import time; time.sleep(60)", name="slow"))
        )

        # Let it actually start before cancelling.
        async with asyncio.timeout(15):
            while (await runner.status(record.run_id)).state != "running":  # type: ignore[union-attr]
                await asyncio.sleep(0.02)

        cancelled = await runner.cancel(record.run_id)

        assert cancelled is not None
        assert cancelled.state == "cancelled"

    async def test_cancelling_a_finished_run_leaves_it_alone(
        self, runner: LocalRunner, tmp_path: Path
    ) -> None:
        record = await runner.submit(spec(tmp_path, python_stage("pass")))
        await wait_for(runner, record.run_id)

        after = await runner.cancel(record.run_id)

        assert after is not None
        assert after.state == "succeeded"

    async def test_cancelling_an_unknown_run_returns_nothing(self, runner: LocalRunner) -> None:
        assert await runner.cancel("r_nope") is None


class TestRegistry:
    def test_records_survive_reopening(self, tmp_path: Path) -> None:
        path = tmp_path / "runs.db"
        RunRegistry(path).add(
            RunRecord(
                run_id="r_1", engine="mf6rtm", label="a", workdir=str(tmp_path), state="running"
            )
        )

        reopened = RunRegistry(path).get("r_1")

        assert reopened is not None
        assert reopened.label == "a"

    def test_lists_newest_first(self, tmp_path: Path) -> None:
        registry = RunRegistry(tmp_path / "runs.db")
        for index, started in enumerate(["2026-01-01T00:00:00", "2026-06-01T00:00:00"]):
            registry.add(
                RunRecord(
                    run_id=f"r_{index}",
                    engine="mf6rtm",
                    label=None,
                    workdir=str(tmp_path),
                    state="succeeded",
                    started_at=started,
                )
            )

        assert [record.run_id for record in registry.recent()] == ["r_1", "r_0"]

    def test_reconcile_clears_runs_whose_process_is_gone(self, tmp_path: Path) -> None:
        registry = RunRegistry(tmp_path / "runs.db")
        registry.add(
            RunRecord(
                run_id="r_orphan",
                engine="mf6rtm",
                label=None,
                workdir=str(tmp_path),
                state="running",
                # A pid that cannot be running: 0 is never a user process.
                pid=0,
            )
        )

        stale = registry.reconcile()

        assert stale == ["r_orphan"]
        record = registry.get("r_orphan")
        assert record is not None
        assert record.state == "unknown"
        assert "restarted" in (record.message or "")

    def test_reconcile_leaves_finished_runs_alone(self, tmp_path: Path) -> None:
        registry = RunRegistry(tmp_path / "runs.db")
        registry.add(
            RunRecord(
                run_id="r_done",
                engine="mf6rtm",
                label=None,
                workdir=str(tmp_path),
                state="succeeded",
            )
        )

        assert registry.reconcile() == []
