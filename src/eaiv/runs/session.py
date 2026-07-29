"""The recording surface a running pipeline talks to.

:class:`RunSession` is the single object that ties together the three
things a run needs to stay observable: the manifest (what happened), the
event stream (when it happened), and the store (where it survives a
process restart). Execution code calls small, intention-revealing methods
— ``stage()``, ``log()``, ``artifact()``, ``suite_result()`` — and never
touches JSON or Streamlit.

A session with no store is fully functional and writes nothing, which is
what keeps the plain ``Orchestrator``/``ValidationPipeline`` API working
for callers that never asked for run persistence.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from eaiv.runs.cancel import CancellationToken, RunCancelled
from eaiv.runs.events import (
    CompositeEventSink,
    EventEmitter,
    EventKind,
    EventLevel,
    EventSink,
    JsonlEventSink,
    NullEventSink,
    utcnow,
)
from eaiv.runs.models import (
    ArtifactKind,
    RunArtifact,
    RunFailure,
    RunManifest,
    RunStatus,
    StageRecord,
    StageStatus,
)
from eaiv.runs.store import RunStore

log = logging.getLogger("eaiv.runs.session")

#: Minimum seconds between manifest rewrites triggered by events. Stage
#: transitions always write immediately; this only throttles the
#: heartbeat that proves a long-running stage is still alive.
HEARTBEAT_INTERVAL_S = 5.0

#: Per-run log file cap; older content is rotated to ``run.log.1``.
MAX_LOG_BYTES = 4 * 1024 * 1024


class RunSession:
    """Records one validation run to a manifest, event log, and store."""

    def __init__(
        self,
        manifest: RunManifest,
        store: RunStore | None = None,
        sink: EventSink | None = None,
        cancel: CancellationToken | None = None,
    ) -> None:
        self.manifest = manifest
        self.store = store
        sinks: list[EventSink] = []
        if sink is not None:
            sinks.append(sink)
        if store is not None:
            store.create(manifest)
            sinks.append(JsonlEventSink(store.events_path(manifest.run_id)))
        combined: EventSink
        if not sinks:
            combined = NullEventSink()
        elif len(sinks) == 1:
            combined = sinks[0]
        else:
            combined = CompositeEventSink(sinks)
        self.emitter = EventEmitter(combined, run_id=manifest.run_id)
        self.cancel = cancel if cancel is not None else self._default_token()
        self._last_heartbeat = 0.0
        self._t0 = time.perf_counter()

    # -- construction ------------------------------------------------------

    def _default_token(self) -> CancellationToken:
        if self.store is None:
            return CancellationToken()
        return CancellationToken(watch_file=self.store.run_dir(self.manifest.run_id) / "cancel.request")

    @property
    def run_dir(self) -> Path | None:
        if self.store is None:
            return None
        return self.store.run_dir(self.manifest.run_id)

    @property
    def run_id(self) -> str:
        return self.manifest.run_id

    # -- persistence -------------------------------------------------------

    def flush(self) -> None:
        """Persist the manifest now (no-op without a store)."""
        if self.store is None:
            return
        try:
            self.store.save(self.manifest)
        except OSError:
            log.exception("could not persist manifest for run %s", self.manifest.run_id)
        self._last_heartbeat = time.monotonic()

    def _heartbeat(self) -> None:
        if self.store is None:
            return
        if time.monotonic() - self._last_heartbeat >= HEARTBEAT_INTERVAL_S:
            self.flush()

    # -- events ------------------------------------------------------------

    def emit(
        self,
        kind: EventKind,
        message: str = "",
        *,
        stage: str = "",
        level: EventLevel = EventLevel.INFO,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.emitter.emit(kind, message, stage=stage, level=level, data=data)
        self._heartbeat()

    def log(self, message: str, *, stage: str = "", level: EventLevel = EventLevel.INFO) -> None:
        """Record a human-readable log line (event stream + run.log)."""
        self.emit(EventKind.LOG, message, stage=stage, level=level)
        self._append_log_file(f"{utcnow()} [{level}] {stage or '-'}: {message}")

    def _append_log_file(self, line: str) -> None:
        directory = self.run_dir
        if directory is None:
            return
        path = directory / "logs" / "run.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
                rotated = path.with_suffix(".log.1")
                rotated.unlink(missing_ok=True)
                path.rename(rotated)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line[:8000] + "\n")
        except OSError:
            log.exception("could not append to run log %s", path)

    def progress(self, stage: str, message: str, **data: Any) -> None:
        self.emit(EventKind.STAGE_PROGRESS, message, stage=stage, data=data)

    def target_connected(self, info: dict[str, Any]) -> None:
        self.manifest.target.update({k: v for k, v in info.items() if v not in (None, "")})
        self.emit(
            EventKind.TARGET_CONNECTED,
            f"connected to {info.get('name') or info.get('kind', 'target')}",
            data=dict(info),
        )

    def metric(self, suite: str, name: str, value: Any, unit: str = "") -> None:
        self.emit(
            EventKind.METRIC,
            f"{suite}.{name}={value}",
            data={"suite": suite, "metric": name, "value": value, "unit": unit},
        )

    def suite_result(self, name: str, passed: bool, metrics: dict[str, Any], notes: str) -> None:
        kind = EventKind.SUITE_PASSED if passed else EventKind.SUITE_FAILED
        self.emit(
            kind,
            f"suite {name}: {'PASS' if passed else 'FAIL'}",
            stage="validate",
            level=EventLevel.INFO if passed else EventLevel.ERROR,
            data={
                "suite": name,
                "metrics": {
                    k: v for k, v in metrics.items() if isinstance(v, (int, float, str, bool))
                },
                "notes": notes[:1000],
            },
        )
        if name not in self.manifest.suites:
            self.manifest.suites.append(name)

    def artifact(
        self,
        name: str,
        path: str | Path,
        kind: ArtifactKind = ArtifactKind.OTHER,
        description: str = "",
    ) -> None:
        """Register a produced file against the run."""
        file = Path(path)
        directory = self.run_dir
        try:
            relative = str(file.relative_to(directory)) if directory else str(file)
        except ValueError:
            relative = str(file)
        size = file.stat().st_size if file.exists() else 0
        artifact = RunArtifact(
            name=name, path=relative, kind=kind, size_bytes=size, description=description
        )
        self.manifest.add_artifact(artifact)
        self.emit(
            EventKind.ARTIFACT,
            f"artifact {name}",
            data={"path": relative, "artifact_kind": str(kind), "size_bytes": size},
        )

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.manifest.status = RunStatus.RUNNING
        self.manifest.started_at = utcnow()
        self.flush()
        self.emit(
            EventKind.RUN_CREATED,
            f"run {self.manifest.display_name} started",
            data={
                "suite_selection": self.manifest.suite_selection,
                "target": dict(self.manifest.target),
            },
        )

    @contextmanager
    def stage(self, name: str) -> Iterator[StageRecord]:
        """Time a stage, record its outcome, and emit start/finish events.

        The context manager records failures but re-raises nothing: the
        pipeline decides whether a failed stage aborts the run, exactly as
        it did before events existed.
        """
        record = StageRecord(name=name, status=StageStatus.RUNNING, started_at=utcnow())
        self.manifest.upsert_stage(record)
        self.emit(EventKind.STAGE_STARTED, f"stage {name} started", stage=name)
        self.flush()
        t0 = time.perf_counter()
        try:
            yield record
        finally:
            record.duration_s = round(time.perf_counter() - t0, 3)
            record.completed_at = utcnow()
            if record.status is StageStatus.RUNNING:
                record.status = StageStatus.OK
            self.manifest.upsert_stage(record)
            self.emit(
                EventKind.STAGE_COMPLETED,
                f"stage {name}: {record.status} ({record.duration_s:.3f}s) {record.detail}".strip(),
                stage=name,
                level=(
                    EventLevel.ERROR if record.status is StageStatus.FAILED else EventLevel.INFO
                ),
                data={
                    "status": str(record.status),
                    "duration_s": record.duration_s,
                    "detail": record.detail,
                },
            )
            self.flush()

    def finish(self, status: RunStatus, failure: RunFailure | None = None) -> None:
        self.manifest.status = status
        self.manifest.completed_at = utcnow()
        self.manifest.duration_s = round(time.perf_counter() - self._t0, 3)
        if failure is not None:
            self.manifest.failure = failure
        if status is RunStatus.CANCELLED:
            self.manifest.cancel_reason = self.manifest.cancel_reason or self.cancel.reason
            self.emit(EventKind.RUN_CANCELLED, self.manifest.cancel_reason, level=EventLevel.WARNING)
        elif status in (RunStatus.FAILED, RunStatus.ERROR, RunStatus.INTERRUPTED):
            message = failure.message if failure else "validation failed"
            self.emit(EventKind.RUN_FAILED, message, level=EventLevel.ERROR)
        else:
            self.emit(EventKind.RUN_COMPLETED, f"run {status}", data={"status": str(status)})
        self.flush()

    def check_cancelled(self) -> None:
        """Raise :class:`RunCancelled` if a cancellation has been requested."""
        self.cancel.check()


def null_session(run_id: str = "adhoc") -> RunSession:
    """A session that persists nothing — used when no store is supplied."""
    return RunSession(RunManifest(run_id=run_id))


__all__ = ["HEARTBEAT_INTERVAL_S", "RunCancelled", "RunSession", "null_session"]
