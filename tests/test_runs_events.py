"""Pipeline events: ordering, persistence, sinks, and cancellation."""

from __future__ import annotations

import json
import threading

import pytest

from eaiv.runs.cancel import CancellationToken, RunCancelled, request_cancel
from eaiv.runs.events import (
    CallbackEventSink,
    CompositeEventSink,
    EventEmitter,
    EventKind,
    EventLevel,
    JsonlEventSink,
    MemoryEventSink,
    PipelineEvent,
    read_events,
)
from eaiv.runs.models import RunManifest, RunStatus
from eaiv.runs.session import RunSession
from eaiv.runs.store import RunStore


def test_sequence_numbers_are_monotonic_and_start_at_one():
    sink = MemoryEventSink()
    emitter = EventEmitter(sink, run_id="r1")
    for index in range(5):
        emitter.emit(EventKind.LOG, f"line {index}")
    assert [e.seq for e in sink.events] == [1, 2, 3, 4, 5]
    assert all(e.run_id == "r1" for e in sink.events)


def test_event_payload_may_carry_reserved_key_names():
    # 'kind', 'stage' and 'level' are also parameter names; payload data
    # must not collide with them.
    sink = MemoryEventSink()
    EventEmitter(sink).emit(
        EventKind.ARTIFACT, "artifact", stage="validate", data={"kind": "report", "level": 3}
    )
    event = sink.events[0]
    assert event.kind is EventKind.ARTIFACT
    assert event.stage == "validate"
    assert event.data == {"kind": "report", "level": 3}


def test_events_round_trip_through_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    emitter = EventEmitter(JsonlEventSink(path), run_id="r2")
    emitter.emit(EventKind.RUN_CREATED, "started")
    emitter.emit(
        EventKind.SUITE_FAILED, "hil failed", level=EventLevel.ERROR, data={"suite": "hil"}
    )

    events = read_events(path)
    assert [str(e.kind) for e in events] == ["run_created", "suite_failed"]
    assert events[1].level is EventLevel.ERROR
    assert events[1].data["suite"] == "hil"
    assert read_events(path, after_seq=1) == events[1:]


def test_truncated_final_line_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "events.jsonl"
    sink = JsonlEventSink(path)
    sink.emit(PipelineEvent(kind=EventKind.LOG, seq=1, message="complete"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "log", "seq": 2, "mess')  # a write cut short
    events = read_events(path)
    assert len(events) == 1 and events[0].message == "complete"


def test_unknown_kinds_and_levels_degrade_to_defaults():
    event = PipelineEvent.from_dict({"kind": "from_the_future", "level": "shouty", "seq": "3"})
    assert event.kind is EventKind.LOG
    assert event.level is EventLevel.INFO
    assert event.seq == 3


def test_callback_sink_survives_a_broken_observer(caplog):
    def explode(event: PipelineEvent) -> None:
        raise RuntimeError("observer bug")

    sink = MemoryEventSink()
    composite = CompositeEventSink([CallbackEventSink(explode), sink])
    EventEmitter(composite).emit(EventKind.LOG, "still delivered")
    assert len(sink.events) == 1


def test_memory_sink_is_bounded():
    sink = MemoryEventSink(max_events=3)
    for index in range(10):
        sink.emit(PipelineEvent(kind=EventKind.LOG, seq=index))
    assert [e.seq for e in sink.events] == [7, 8, 9]


def test_cancellation_token_raises_on_check():
    token = CancellationToken()
    token.check()  # no-op while not cancelled
    token.cancel("stop now")
    assert token.cancelled
    with pytest.raises(RunCancelled, match="stop now"):
        token.check()


def test_file_backed_cancellation_is_visible_across_processes(tmp_path):
    token = CancellationToken(watch_file=tmp_path / "cancel.request", poll_interval_s=0.0)
    assert token.cancelled is False
    request_cancel(tmp_path, "cancelled from the dashboard")
    assert token.cancelled is True
    assert token.reason == "cancelled from the dashboard"


def test_cancellation_token_wait_returns_early():
    token = CancellationToken(poll_interval_s=0.01)
    threading.Timer(0.05, lambda: token.cancel()).start()
    assert token.wait(5.0) is True


def test_session_records_ordered_events_and_manifest(tmp_path):
    store = RunStore(tmp_path)
    sink = MemoryEventSink()
    session = RunSession(RunManifest(run_id="s1", name="test"), store=store, sink=sink)

    session.start()
    with session.stage("validate") as record:
        session.suite_result("hil", False, {"drop_rate": 0.2}, "faults injected")
        session.metric("hil", "drop_rate", 0.2, "ratio")
        record.detail = "1 of 1 suites failed"
    session.finish(RunStatus.FAILED)

    kinds = sink.kinds()
    assert kinds[0] == "run_created"
    assert kinds.index("stage_started") < kinds.index("suite_failed")
    assert kinds.index("suite_failed") < kinds.index("stage_completed")
    assert kinds[-1] == "run_failed"

    persisted = store.load("s1")
    assert persisted.status is RunStatus.FAILED
    assert persisted.stage("validate").detail == "1 of 1 suites failed"
    assert "hil" in persisted.suites
    # The same stream is on disk, so another process sees identical ordering.
    assert [str(e.kind) for e in store.events("s1")] == kinds


def test_session_without_a_store_writes_nothing(tmp_path):
    sink = MemoryEventSink()
    session = RunSession(RunManifest(run_id="ephemeral"), sink=sink)
    session.start()
    session.log("hello")
    session.finish(RunStatus.PASSED)
    assert sink.kinds()[0] == "run_created"
    assert list(tmp_path.iterdir()) == []


def test_session_artifact_registration_is_relative_to_the_run_dir(tmp_path):
    store = RunStore(tmp_path)
    session = RunSession(RunManifest(run_id="a1"), store=store)
    report = store.run_dir("a1") / "report.json"
    report.write_text('{"suites": []}')
    session.artifact("report.json", report)
    assert session.manifest.artifacts[0].path == "report.json"
    assert session.manifest.artifacts[0].size_bytes > 0


def test_run_log_file_is_written(tmp_path):
    store = RunStore(tmp_path)
    session = RunSession(RunManifest(run_id="l1"), store=store)
    session.log("device did not answer", stage="firmware", level=EventLevel.ERROR)
    text = (store.run_dir("l1") / "logs" / "run.log").read_text()
    assert "device did not answer" in text
    assert "firmware" in text


def test_events_file_is_valid_jsonl(tmp_path):
    store = RunStore(tmp_path)
    session = RunSession(RunManifest(run_id="j1"), store=store)
    session.start()
    session.finish(RunStatus.PASSED)
    lines = store.events_path("j1").read_text().strip().splitlines()
    assert lines
    for line in lines:
        assert isinstance(json.loads(line), dict)
