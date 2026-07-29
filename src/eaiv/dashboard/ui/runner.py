"""Launching validation runs from the browser.

A run started in the dashboard executes on a worker thread, but every
piece of its state — manifest, events, artifacts, cancellation request —
lives on disk in the run directory. That is deliberate: a browser refresh,
a new tab, or a restarted Streamlit server must never lose a run or
orphan a running one. The thread registry below is a convenience for the
tab that started the run, not the source of truth.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eaiv.config import Config
from eaiv.core.baseline import BaselineStore
from eaiv.core.pipeline import ValidationPipeline
from eaiv.runs.models import RunFailure, RunStatus
from eaiv.runs.store import RunStore

log = logging.getLogger("eaiv.dashboard.runner")


@dataclass(frozen=True)
class LaunchSpec:
    """Everything needed to start a mission."""

    config: dict[str, Any]
    suite: str = "all"
    baseline: str = ""
    save_baseline: str = ""
    telemetry_s: float = 0.0
    max_regression_pct: float = 10.0
    build_env: str = ""
    run_name: str = ""
    config_path: str = ""


class RunLauncher:
    """Starts pipeline runs on worker threads and tracks the live ones."""

    def __init__(self, report_dir: str | Path, baseline_dir: str | Path) -> None:
        self.report_dir = Path(report_dir)
        self.baseline_dir = Path(baseline_dir)
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    @property
    def store(self) -> RunStore:
        return RunStore(self.report_dir)

    def start(self, spec: LaunchSpec) -> str:
        """Begin a run and return its id as soon as the manifest exists.

        The manifest is created synchronously so the caller can navigate
        straight to the live view; the stages then run on the worker.
        """
        store = self.store
        pipeline = ValidationPipeline(
            Config(dict(spec.config)),
            report_dir=str(self.report_dir),
            baseline_store=BaselineStore(self.baseline_dir),
            run_store=store,
            config_path=spec.config_path,
        )
        session = pipeline.create_session(
            suite=spec.suite,
            baseline=spec.baseline or None,
            save_baseline=spec.save_baseline or None,
            max_regression_pct=spec.max_regression_pct,
            run_name=spec.run_name,
            trigger="dashboard",
        )
        pipeline.session = session
        run_id = session.manifest.run_id

        def _execute() -> None:
            try:
                pipeline.run(
                    suite=spec.suite,
                    build_env=spec.build_env or None,
                    baseline=spec.baseline or None,
                    save_baseline=spec.save_baseline or None,
                    telemetry_s=spec.telemetry_s,
                    max_regression_pct=spec.max_regression_pct,
                    run_name=spec.run_name,
                    trigger="dashboard",
                )
            except BaseException as exc:  # noqa: BLE001 - the worker owns the run's outcome
                log.exception("run %s crashed", run_id)
                session.finish(
                    RunStatus.ERROR,
                    RunFailure.from_exception(
                        exc,
                        hint="This is an unexpected failure; the traceback is in the run manifest.",
                    ),
                )
            finally:
                with self._lock:
                    self._threads.pop(run_id, None)

        thread = threading.Thread(target=_execute, name=f"eaiv-run-{run_id}", daemon=True)
        with self._lock:
            self._threads[run_id] = thread
        thread.start()
        return run_id

    def is_live_here(self, run_id: str) -> bool:
        """True when this process is the one executing the run."""
        with self._lock:
            thread = self._threads.get(run_id)
        return thread is not None and thread.is_alive()

    def cancel(self, run_id: str, reason: str = "cancelled from the dashboard") -> None:
        """Request cancellation through the run directory, not through memory.

        Writing the request to disk means it works even when the run was
        started by a different browser session or a different process.
        """
        self.store.request_cancel(run_id, reason)


_launchers: dict[tuple[str, str], RunLauncher] = {}
_launcher_lock = threading.Lock()


def get_launcher(report_dir: str | Path, baseline_dir: str | Path) -> RunLauncher:
    """One launcher per (report dir, baseline dir), shared across reruns.

    Streamlit re-executes the script constantly but keeps module state, so
    a module-level registry is what lets a run survive interactions in the
    tab that started it.
    """
    key = (str(report_dir), str(baseline_dir))
    with _launcher_lock:
        launcher = _launchers.get(key)
        if launcher is None:
            launcher = RunLauncher(report_dir, baseline_dir)
            _launchers[key] = launcher
        return launcher


__all__ = ["LaunchSpec", "RunLauncher", "get_launcher"]
