"""Typed pipeline events and the sinks that consume them.

Execution emits :class:`PipelineEvent` values through an
:class:`EventSink`. The core package never imports a UI toolkit: a sink is
any object with an ``emit(event)`` method, so the CLI, the dashboard, a
test, or a log file all observe the same stream.

    sink = CompositeEventSink([JsonlEventSink(path), MemoryEventSink()])
    pipeline = ValidationPipeline(cfg, events=sink)

Existing synchronous callers pass nothing and get the previous behaviour
(events are dropped by :class:`NullEventSink`).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("eaiv.events")

#: A single JSONL event line is truncated past this size so a runaway
#: device can never fill the disk with one record.
MAX_EVENT_MESSAGE_CHARS = 4000


class EventKind(StrEnum):
    """Every observable moment in a validation run."""

    RUN_CREATED = "run_created"
    STAGE_STARTED = "stage_started"
    STAGE_PROGRESS = "stage_progress"
    LOG = "log"
    TARGET_CONNECTED = "target_connected"
    ARTIFACT = "artifact"
    METRIC = "metric"
    SUITE_PASSED = "suite_passed"
    SUITE_FAILED = "suite_failed"
    STAGE_COMPLETED = "stage_completed"
    RUN_CANCELLED = "run_cancelled"
    RUN_FAILED = "run_failed"
    RUN_COMPLETED = "run_completed"


class EventLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def utcnow() -> str:
    """Timestamp string used across manifests, events, and reports."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class PipelineEvent:
    """One immutable observation from a run.

    ``seq`` is assigned by :class:`EventEmitter` and is monotonic per run,
    which is what makes ordering assertions (and incremental UI reads)
    possible even when timestamps collide at millisecond resolution.
    """

    kind: EventKind
    run_id: str = ""
    seq: int = 0
    timestamp: str = field(default_factory=utcnow)
    stage: str = ""
    message: str = ""
    level: EventLevel = EventLevel.INFO
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "run_id": self.run_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "message": self.message[:MAX_EVENT_MESSAGE_CHARS],
            "level": str(self.level),
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PipelineEvent:
        """Parse a persisted event, tolerating unknown kinds and levels."""
        raw_kind = str(payload.get("kind", EventKind.LOG))
        try:
            kind = EventKind(raw_kind)
        except ValueError:
            kind = EventKind.LOG
        try:
            level = EventLevel(str(payload.get("level", EventLevel.INFO)))
        except ValueError:
            level = EventLevel.INFO
        data = payload.get("data")
        return cls(
            kind=kind,
            run_id=str(payload.get("run_id", "")),
            seq=int(payload.get("seq", 0) or 0),
            timestamp=str(payload.get("timestamp", "")),
            stage=str(payload.get("stage", "")),
            message=str(payload.get("message", "")),
            level=level,
            data=data if isinstance(data, dict) else {},
        )


@runtime_checkable
class EventSink(Protocol):
    """Anything that can receive pipeline events."""

    def emit(self, event: PipelineEvent) -> None: ...


class NullEventSink:
    """Drops everything — the default for callers that don't observe."""

    def emit(self, event: PipelineEvent) -> None:  # noqa: D102
        return None


class MemoryEventSink:
    """Keeps events in memory (bounded); used by tests and short-lived UIs."""

    def __init__(self, max_events: int = 10_000) -> None:
        self.max_events = max_events
        self.events: list[PipelineEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: PipelineEvent) -> None:
        with self._lock:
            self.events.append(event)
            if len(self.events) > self.max_events:
                del self.events[: len(self.events) - self.max_events]

    def kinds(self) -> list[str]:
        return [str(e.kind) for e in self.events]


class CallbackEventSink:
    """Adapts a plain callable into a sink.

    A misbehaving observer must never take down a validation run, so
    callback errors are logged (never silently discarded) and execution
    continues.
    """

    def __init__(self, callback: Callable[[PipelineEvent], None]) -> None:
        self.callback = callback

    def emit(self, event: PipelineEvent) -> None:
        try:
            self.callback(event)
        except Exception:  # noqa: BLE001 - observer errors must not abort a run
            log.exception("event callback failed for %s", event.kind)


class JsonlEventSink:
    """Appends events to ``events.jsonl``, one JSON object per line.

    The file is the durable record a dashboard replays after a refresh or
    a process restart. Writes are line-buffered and flushed so a partially
    completed run is still readable; the file is rotated once it exceeds
    ``max_bytes`` so a chatty device cannot exhaust the disk.
    """

    def __init__(self, path: str | Path, max_bytes: int = 8 * 1024 * 1024) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: PipelineEvent) -> None:
        line = json.dumps(event.to_dict(), default=str)
        with self._lock:
            try:
                self._rotate_if_needed()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                log.exception("could not append event to %s", self.path)

    def _rotate_if_needed(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return
        rotated = self.path.with_suffix(self.path.suffix + ".1")
        rotated.unlink(missing_ok=True)
        self.path.rename(rotated)


class CompositeEventSink:
    """Fans one event out to several sinks."""

    def __init__(self, sinks: Iterable[EventSink]) -> None:
        self.sinks = list(sinks)

    def emit(self, event: PipelineEvent) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:  # noqa: BLE001 - one bad sink must not block others
                log.exception("event sink %r failed", sink)


class EventEmitter:
    """Stamps sequence numbers/timestamps and forwards to a sink.

    Thread-safe: the dashboard runs pipelines on a worker thread while the
    UI thread tails the same run.
    """

    def __init__(self, sink: EventSink | None = None, run_id: str = "") -> None:
        self.sink: EventSink = sink if sink is not None else NullEventSink()
        self.run_id = run_id
        self._seq = 0
        self._lock = threading.Lock()

    def emit(
        self,
        kind: EventKind,
        message: str = "",
        *,
        stage: str = "",
        level: EventLevel = EventLevel.INFO,
        data: dict[str, Any] | None = None,
    ) -> PipelineEvent:
        """Emit one event.

        Payload fields go in ``data`` rather than as keyword arguments so
        an event can carry a key named ``kind``, ``stage``, or ``level``
        without colliding with this method's own parameters.
        """
        with self._lock:
            self._seq += 1
            seq = self._seq
        event = PipelineEvent(
            kind=kind,
            run_id=self.run_id,
            seq=seq,
            stage=stage,
            message=message,
            level=level,
            data=dict(data or {}),
        )
        self.sink.emit(event)
        return event


def read_events(path: str | Path, after_seq: int = 0) -> list[PipelineEvent]:
    """Read persisted events with ``seq > after_seq``, skipping bad lines.

    A truncated final line is normal while a run is in flight; it is
    skipped rather than raising, and picked up on the next read.
    """
    file = Path(path)
    if not file.exists():
        return []
    events: list[PipelineEvent] = []
    try:
        with file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event = PipelineEvent.from_dict(payload)
                if event.seq > after_seq:
                    events.append(event)
    except OSError:
        log.exception("could not read events from %s", file)
        return events
    return events


def iter_events(events: Iterable[PipelineEvent], kind: EventKind) -> Iterator[PipelineEvent]:
    """Filter an event stream by kind."""
    return (e for e in events if e.kind == kind)


__all__ = [
    "CallbackEventSink",
    "CompositeEventSink",
    "EventEmitter",
    "EventKind",
    "EventLevel",
    "EventSink",
    "JsonlEventSink",
    "MemoryEventSink",
    "NullEventSink",
    "PipelineEvent",
    "iter_events",
    "read_events",
    "utcnow",
]
