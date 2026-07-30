"""First-class validation runs: manifests, events, cancellation, storage.

A report says what was measured; a *run* says what happened. This package
holds that second model — the one the dashboard, the CLI, and CI all need
to answer "is something running right now?", "why did it stop?", and
"what did it produce?".

    store = RunStore("reports")
    manifest = RunManifest(run_id=new_run_id("nightly"), name="nightly")
    session = RunSession(manifest, store=store)

``eaiv.core.pipeline`` drives a session for you; use these types directly
only when embedding the platform in another runner.
"""

from __future__ import annotations

from eaiv.runs.cancel import (
    CANCEL_FILENAME,
    CancellationToken,
    RunCancelled,
    clear_cancel,
    request_cancel,
)
from eaiv.runs.events import (
    CallbackEventSink,
    CompositeEventSink,
    EventEmitter,
    EventKind,
    EventLevel,
    EventSink,
    JsonlEventSink,
    MemoryEventSink,
    NullEventSink,
    PipelineEvent,
    read_events,
    utcnow,
)
from eaiv.runs.models import (
    MANIFEST_SCHEMA_VERSION,
    ArtifactKind,
    RunArtifact,
    RunFailure,
    RunManifest,
    RunStatus,
    RunSummary,
    StageRecord,
    StageStatus,
    eaiv_version,
    git_info,
    host_info,
    is_valid_run_id,
    new_run_id,
    sanitize_component,
)
from eaiv.runs.session import RunSession, null_session
from eaiv.runs.store import RunStore, atomic_write_json, atomic_write_text

__all__ = [
    "CANCEL_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "ArtifactKind",
    "CallbackEventSink",
    "CancellationToken",
    "CompositeEventSink",
    "EventEmitter",
    "EventKind",
    "EventLevel",
    "EventSink",
    "JsonlEventSink",
    "MemoryEventSink",
    "NullEventSink",
    "PipelineEvent",
    "RunArtifact",
    "RunCancelled",
    "RunFailure",
    "RunManifest",
    "RunSession",
    "RunStatus",
    "RunStore",
    "RunSummary",
    "StageRecord",
    "StageStatus",
    "atomic_write_json",
    "atomic_write_text",
    "clear_cancel",
    "eaiv_version",
    "git_info",
    "host_info",
    "is_valid_run_id",
    "new_run_id",
    "null_session",
    "read_events",
    "request_cancel",
    "sanitize_component",
    "utcnow",
]
