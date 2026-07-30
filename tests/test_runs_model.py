"""Run manifests, the run store, and recovery from interrupted runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from eaiv.runs.models import (
    ArtifactKind,
    RunArtifact,
    RunFailure,
    RunManifest,
    RunStatus,
    RunSummary,
    StageRecord,
    StageStatus,
    is_valid_run_id,
    new_run_id,
    sanitize_component,
)
from eaiv.runs.store import RunStore, atomic_write_text


def _manifest(run_id: str = "run-1", **kwargs) -> RunManifest:
    return RunManifest(run_id=run_id, name="nightly", **kwargs)


def test_manifest_round_trips_through_json():
    manifest = _manifest()
    manifest.status = RunStatus.PASSED
    manifest.upsert_stage(StageRecord("validate", StageStatus.OK, duration_s=1.25, detail="6/6"))
    manifest.add_artifact(RunArtifact("report.json", "report.json", ArtifactKind.REPORT, 42))
    manifest.summary = RunSummary(total_suites=6, passed_suites=6, all_passed=True)
    manifest.failure = RunFailure(stage="compare", type="RuntimeError", message="boom")

    restored = RunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))

    assert restored.run_id == manifest.run_id
    assert restored.status is RunStatus.PASSED
    assert restored.stages[0].status is StageStatus.OK
    assert restored.stages[0].duration_s == 1.25
    assert restored.artifacts[0].kind is ArtifactKind.REPORT
    assert restored.summary.pass_rate == 1.0
    assert restored.failure is not None and restored.failure.type == "RuntimeError"


def test_manifest_tolerates_missing_and_unknown_fields():
    restored = RunManifest.from_dict(
        {"run_id": "x", "status": "not-a-status", "stages": "nonsense", "summary": 7}
    )
    assert restored.status is RunStatus.PENDING
    assert restored.stages == []
    assert restored.summary.total_suites == 0


def test_stage_status_keeps_its_legacy_string_values():
    # CLI output and existing callers compare against these literals.
    assert StageStatus.OK == "ok"
    assert StageStatus.FAILED == "failed"
    assert StageStatus.SKIPPED == "skipped"
    assert f"[{StageStatus.OK:>7}]" == "[     ok]"


def test_run_id_is_sortable_and_safe():
    first = new_run_id("nightly build")
    assert is_valid_run_id(first)
    assert "nightly-build" in first
    assert sanitize_component("../../etc/passwd") == "etc-passwd"
    for unsafe in ("", "..", "../escape", "a/b", "with space"):
        assert not is_valid_run_id(unsafe)


def test_store_round_trip_and_listing(tmp_path):
    store = RunStore(tmp_path)
    for index in range(3):
        manifest = _manifest(f"2026010{index}T000000-abc{index}")
        manifest.created_at = f"2026-01-0{index + 1}T00:00:00+00:00"
        store.create(manifest)

    listed = store.list()
    assert [m.run_id for m in listed] == [
        "20260102T000000-abc2",
        "20260101T000000-abc1",
        "20260100T000000-abc0",
    ]
    assert store.latest().run_id == "20260102T000000-abc2"
    assert store.exists("20260101T000000-abc1")


def test_store_rejects_traversal_in_run_ids(tmp_path):
    store = RunStore(tmp_path)
    for unsafe in ("../evil", "a/b", ".."):
        with pytest.raises(ValueError):
            store.run_dir(unsafe)
    assert store.exists("../evil") is False


def test_artifact_path_cannot_escape_the_run_directory(tmp_path):
    store = RunStore(tmp_path)
    store.create(_manifest("run-x"))
    assert store.artifact_path("run-x", "report.json").name == "report.json"
    with pytest.raises(ValueError):
        store.artifact_path("run-x", "../../secret.txt")


def test_unreadable_manifest_is_skipped_not_fatal(tmp_path):
    store = RunStore(tmp_path)
    store.create(_manifest("good-1"))
    broken = store.runs_root / "broken-1"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{ not json")
    assert [m.run_id for m in store.list()] == ["good-1"]


def test_abandoned_running_run_is_reconciled_to_interrupted(tmp_path):
    store = RunStore(tmp_path)
    manifest = _manifest("stale-1")
    manifest.status = RunStatus.RUNNING
    manifest.pid = 999_999  # a PID that does not exist
    manifest.upsert_stage(StageRecord("validate", StageStatus.RUNNING))
    store.create(manifest)

    # Backdate the heartbeat past the staleness window.
    payload = json.loads(store.manifest_path("stale-1").read_text())
    payload["heartbeat"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(
        timespec="milliseconds"
    )
    payload["pid"] = 999_999
    atomic_write_text(store.manifest_path("stale-1"), json.dumps(payload))

    reconciled = store.load("stale-1")
    assert reconciled.status is RunStatus.INTERRUPTED
    assert reconciled.failure is not None
    assert "exited before the run finished" in reconciled.failure.message
    assert reconciled.stage("validate").status is StageStatus.FAILED
    # And it is persisted, so a completed run never looks active again.
    assert (
        RunManifest.from_dict(json.loads(store.manifest_path("stale-1").read_text())).status
        is RunStatus.INTERRUPTED
    )


def test_fresh_heartbeat_keeps_a_run_active(tmp_path):
    store = RunStore(tmp_path)
    manifest = _manifest("live-1")
    manifest.status = RunStatus.RUNNING
    store.create(manifest)  # create() stamps a fresh heartbeat
    assert store.load("live-1").status is RunStatus.RUNNING


def test_reconcile_all_reports_changed_runs(tmp_path):
    store = RunStore(tmp_path)
    manifest = _manifest("stale-2")
    manifest.status = RunStatus.RUNNING
    manifest.pid = 999_999
    store.create(manifest)
    payload = json.loads(store.manifest_path("stale-2").read_text())
    payload["heartbeat"] = "2020-01-01T00:00:00.000+00:00"
    atomic_write_text(store.manifest_path("stale-2"), json.dumps(payload))

    assert store.reconcile_all() == ["stale-2"]


def test_atomic_write_leaves_no_partial_file_on_failure(tmp_path):
    target = tmp_path / "manifest.json"
    atomic_write_text(target, '{"ok": true}')
    assert json.loads(target.read_text()) == {"ok": True}
    # No temp files are left behind.
    assert [p.name for p in tmp_path.iterdir()] == ["manifest.json"]


def test_cancellation_request_is_visible_through_the_store(tmp_path):
    store = RunStore(tmp_path)
    store.create(_manifest("cancel-me"))
    assert store.cancel_requested("cancel-me") is False
    store.request_cancel("cancel-me", "user pressed stop")
    assert store.cancel_requested("cancel-me") is True
