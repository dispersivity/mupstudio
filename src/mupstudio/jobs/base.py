"""What a runner is, independent of where the work happens.

Only the local subprocess runner exists today, but the interface is shaped for
the cluster case: a job carries what it needs staged in and what it expects
back out, so a Condor runner can implement the same five methods without
anything above this layer changing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from mupstudio.jobs.progress import ProgressEvent
from mupstudio.jobs.registry import RunRecord, RunState


@dataclass
class Stage:
    """One process to run. A PHT3D job is two of these: flow, then transport."""

    argv: list[str]
    name: str = ""
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class JobSpec:
    """Everything needed to run a model, wherever it runs."""

    stages: list[Stage]
    workdir: Path
    engine: str
    label: str | None = None
    # Ignored locally; a cluster runner uses these to ship files to and from
    # a worker node. Declared here so jobs are portable by construction.
    stage_in: list[Path] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    total_kper: int | None = None


class Runner(ABC):
    """Submits jobs and reports on them."""

    @abstractmethod
    async def submit(self, spec: JobSpec) -> RunRecord:
        """Start a job and return its record straight away, without waiting."""

    @abstractmethod
    async def status(self, run_id: str) -> RunRecord | None: ...

    @abstractmethod
    async def cancel(self, run_id: str) -> RunRecord | None:
        """Stop a running job. Already-finished jobs are left alone."""

    @abstractmethod
    def events(self, run_id: str) -> AsyncIterator[ProgressEvent]:
        """Progress for a job, from now until it ends."""

    @abstractmethod
    def log_path(self, run_id: str) -> Path:
        """Where this job's captured output is written."""


def terminal(state: RunState) -> bool:
    return state in {"succeeded", "failed", "cancelled", "unknown"}
