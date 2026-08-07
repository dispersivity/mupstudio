"""Running the chemistry write worker and reading its answer.

The worker is a subprocess (see ``write_worker`` for why). This is the parent
half: it writes the spec, starts the process, streams its output to whoever is
watching, and turns the result line back into something typed.

PHREEQC failures arrive as text, and that text is the most useful thing anyone
gets when a solution will not equilibrate. It is passed through unchanged.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mupstudio.compile.compiler import CompiledModel
from mupstudio.engines.mf6rtm.chemistry import build_spec
from mupstudio.engines.mf6rtm.write_worker import RESULT_MARKER

log = logging.getLogger(__name__)

# Equilibrating a large grid against a big database is slow, but not this slow;
# past here something is wrong and waiting will not fix it.
DEFAULT_TIMEOUT = 900.0


class ReactiveWriteError(Exception):
    """The reactive model could not be built.

    ``output`` holds everything the worker printed, which for a chemistry
    failure is where the PHREEQC message is.
    """

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


@dataclass
class ReactiveWrite:
    """What attaching chemistry produced."""

    workdir: Path
    components: list[str]
    files: list[str]
    output: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def component_count(self) -> int:
        return len(self.components)

    def describe(self) -> str:
        names = ", ".join(self.components[:8])
        if len(self.components) > 8:
            names += f" and {len(self.components) - 8} more"
        return f"{self.component_count} components: {names}"


def write_reactive(
    model: CompiledModel,
    workdir: Path,
    *,
    flow_name: str,
    transport_name: str,
    on_output: Callable[[str], None] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ReactiveWrite:
    """Attach chemistry to an already-written simulation.

    The MODFLOW 6 files must be in ``workdir`` already: this equilibrates the
    chemistry, clones the tracer transport model once per component, and writes
    the result over the top.
    """
    spec = {
        "workdir": str(Path(workdir).resolve()),
        "flowName": flow_name,
        "transportName": transport_name,
        "shape": list(model.grid.shape),
        "chemistry": build_spec(model),
    }

    with tempfile.TemporaryDirectory(prefix="mupstudio-chem-") as scratch:
        spec_path = Path(scratch) / "spec.json"
        spec_path.write_text(json.dumps(spec))
        result, output = _run_worker(spec_path, on_output=on_output, timeout=timeout)

    return ReactiveWrite(
        workdir=Path(result["workdir"]),
        components=result["components"],
        files=result["files"],
        output=output,
    )


def _run_worker(
    spec_path: Path,
    *,
    on_output: Callable[[str], None] | None,
    timeout: float,
) -> tuple[dict[str, Any], str]:
    """Start the worker, collect its output, and find the result line."""
    command = [sys.executable, "-m", "mupstudio.engines.mf6rtm.write_worker", str(spec_path)]
    log.debug("chemistry worker: %s", " ".join(command))

    lines: list[str] = []
    result: dict[str, Any] | None = None

    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # Unbuffered on the child's side too, so progress appears while it works
        # rather than all at once when it exits.
        env=_worker_env(),
    ) as process:
        assert process.stdout is not None
        try:
            for raw in process.stdout:
                line = raw.rstrip("\n")
                if line.startswith(RESULT_MARKER):
                    result = json.loads(line[len(RESULT_MARKER) :])
                    continue
                lines.append(line)
                if on_output is not None:
                    on_output(line)
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raise ReactiveWriteError(
                f"the chemistry worker did not finish within {timeout:.0f} seconds",
                "\n".join(lines),
            ) from None

    output = "\n".join(lines)

    if result is None:
        raise ReactiveWriteError(
            f"the chemistry worker exited with code {process.returncode} without a result",
            output,
        )
    if not result.get("ok"):
        # The worker's traceback is more informative than anything reconstructed
        # here, so it goes into the output the caller shows.
        detail = result.get("traceback", "")
        raise ReactiveWriteError(
            result.get("error", "the chemistry worker failed"),
            f"{output}\n{detail}".strip(),
        )

    return result, output


def _worker_env() -> dict[str, str]:
    import os

    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    return environment
