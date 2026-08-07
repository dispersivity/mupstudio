"""Turning engine chatter into progress.

mf6rtm has no callback API and no structured log: the only signal a running
model gives is what it prints. It prints a fixed-width line per phase per
timestep, so those lines are the progress bar.

Sample of what is being matched::

    Transport       | Stress period:  1     | Time step:      3          | Completed in : 0.01 mins
    Reactions       | Stress period:  1     | Time step:      3          | Completed in : 0.12 mins
    Solution finished at 2026-08-07 10:12:03. Running time: 2.4 mins
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Phase = Literal["flow", "transport", "chemistry", "other"]

_STEP = re.compile(
    r"^(?P<phase>Transport|Reactions|Flow)\s*\|\s*"
    r"Stress period:\s*(?P<kper>\d+)\s*\|\s*"
    r"Time step:\s*(?P<kstp>\d+)",
    re.IGNORECASE,
)
_FINISHED = re.compile(r"MODEL RUN FINISHED", re.IGNORECASE)
_FAILED = re.compile(r"SOMETHING WENT WRONG|BUMMER", re.IGNORECASE)
_CONVERGENCE = re.compile(r"failed to converge (?P<count>\d+) times", re.IGNORECASE)

_PHASES: dict[str, Phase] = {
    "transport": "transport",
    "reactions": "chemistry",
    "flow": "flow",
}


@dataclass(frozen=True)
class ProgressEvent:
    """One thing worth telling the user about a running model."""

    kind: Literal["step", "finished", "failed", "warning"]
    kper: int | None = None
    kstp: int | None = None
    phase: Phase = "other"
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "kper": self.kper,
            "kstp": self.kstp,
            "phase": self.phase,
            "message": self.message,
        }


def parse_line(line: str) -> ProgressEvent | None:
    """Read one line of engine output. Returns None for lines that say nothing."""
    text = line.strip()
    if not text:
        return None

    step = _STEP.match(text)
    if step:
        return ProgressEvent(
            kind="step",
            kper=int(step.group("kper")),
            kstp=int(step.group("kstp")),
            phase=_PHASES.get(step.group("phase").lower(), "other"),
        )

    convergence = _CONVERGENCE.search(text)
    if convergence:
        return ProgressEvent(
            kind="warning",
            message=f"MODFLOW failed to converge {convergence.group('count')} times",
        )

    if _FAILED.search(text):
        return ProgressEvent(kind="failed", message=text)

    if _FINISHED.search(text):
        return ProgressEvent(kind="finished", message=text)

    return None


class ProgressTracker:
    """Keeps the latest position, and estimates how far along the run is.

    Total stress periods are not known from stdout, so the fraction is only
    offered once a caller supplies the count from the model definition.
    """

    def __init__(self, total_kper: int | None = None):
        self.total_kper = total_kper
        self.kper: int | None = None
        self.kstp: int | None = None
        self.phase: Phase = "other"
        self.warnings: list[str] = []
        self.finished = False
        self.failed = False

    def apply(self, event: ProgressEvent) -> None:
        if event.kind == "step":
            self.kper = event.kper
            self.kstp = event.kstp
            self.phase = event.phase
        elif event.kind == "warning":
            self.warnings.append(event.message)
        elif event.kind == "finished":
            self.finished = True
        elif event.kind == "failed":
            self.failed = True

    @property
    def fraction(self) -> float | None:
        """Rough completion, or None when the total is unknown."""
        if not self.total_kper or self.kper is None:
            return None
        return min(1.0, self.kper / self.total_kper)

    def snapshot(self) -> dict[str, object]:
        return {
            "kper": self.kper,
            "kstp": self.kstp,
            "phase": self.phase,
            "fraction": self.fraction,
            "warnings": list(self.warnings),
            "finished": self.finished,
            "failed": self.failed,
        }
