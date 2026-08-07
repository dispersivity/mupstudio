"""Shared instances the routers reach for.

One runner and one registry per process. The runner holds live subprocess
handles and progress subscribers, so a fresh instance per request would lose
track of everything already running.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from mupstudio.jobs.local import LocalRunner
from mupstudio.jobs.registry import RunRegistry

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def run_registry() -> RunRegistry:
    return RunRegistry()


@lru_cache(maxsize=1)
def runner_instance() -> LocalRunner:
    return LocalRunner(registry=run_registry())


def reconcile_runs() -> list[str]:
    """Settle runs left in progress by a previous server.

    Called at startup: a run recorded as running is not running, because this
    process did not start it and nothing is watching it.
    """
    stale = run_registry().reconcile()
    if stale:
        log.info("marked %d interrupted run(s) as unknown: %s", len(stale), ", ".join(stale))
    return stale
