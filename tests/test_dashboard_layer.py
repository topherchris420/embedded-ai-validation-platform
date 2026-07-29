"""Dashboard data layer: sources, path safety, and signal analysis.

None of this imports Streamlit — the whole layer is testable headlessly,
which is what keeps the presentation modules thin.
"""

from __future__ import annotations

import json

import pytest

from eaiv.core.reporter import Reporter
from eaiv.core.results import AggregateResult, SuiteResult
from eaiv.dashboard.runs import (
    all_sources,
    legacy_sources,
    load_run_report,
    recent_activity,
    run_sources,
    stage_timeline,
)
from eaiv.dashboard.safety import (
    MAX_UPLOAD_BYTES,
    PathPolicy,
    UnsafePathError,
    check_upload,
    resolve_within,
)
from eaiv.dashboard.signals import (
    analyze_sampling,
    analyze_signal,
    group_signals,
    orientation_error,
    reference_pairs,
)
from eaiv.runs.models import RunManifest, RunStatus, StageRecord, StageStatus
from eaiv.runs.store import RunStore

# -- path safety -----------------------------------------------------------


def test_paths_inside_the_policy_resolve(tmp_path):
    (tmp_path / "datasets").mkdir()
    policy = PathPolicy.build(tmp_path)
    assert resolve_within(policy, "datasets") == (tmp_path / "datasets").resolve()
    assert resolve_within(policy, tmp_path / "datasets") == (tmp_path / "datasets").resolve()


def test_traversal_out_of_the_policy_is_refused(tmp_path):
    policy = PathPolicy.build(tmp_path / "allowed")
    (tmp_path / "allowed").mkdir()
    for attempt in ("../secret", "/etc", "../../"):
        with pytest.raises(UnsafePathError):
            resolve_within(policy, attempt)


def test_symlinks_cannot_smuggle_a_path_out_of_the_policy(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.csv").write_text("t_s\n0\n")
    try:
        (allowed / "link.csv").symlink_to(outside / "secret.csv")
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("symlinks unavailable on this platform")
    policy = PathPolicy.build(allowed)
    with pytest.raises(UnsafePathError):
        resolve_within(policy, "link.csv")


def test_multiple_roots_are_all_allowed(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    policy = PathPolicy.build(first, second)
    assert resolve_within(policy, second) == second.resolve()
    assert first.resolve() in policy.roots


def test_oversized_uploads_are_rejected_with_a_useful_message():
    check_upload("small.csv", 1024)
    with pytest.raises(ValueError, match="the limit is"):
        check_upload("huge.csv", MAX_UPLOAD_BYTES + 1)


# -- report sources --------------------------------------------------------


def _publish_legacy(report_dir, mean_ms: float) -> None:
    results = AggregateResult()
    results.add(SuiteResult(name="tinyml", passed=True, metrics={"mean_ms": mean_ms}))
    Reporter(report_dir).publish(results, metadata={"target": {"name": "esp32"}}, quiet=True)


def _record_run(store: RunStore, run_id: str, created: str, status: RunStatus) -> RunManifest:
    manifest = RunManifest(run_id=run_id, name=run_id, status=status, created_at=created)
    manifest.target = {"kind": "sim", "name": "sim"}
    store.create(manifest)
    (store.run_dir(run_id) / "report.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "timestamp": created,
                "meta": {"target": {"name": "sim"}},
                "suites": [{"name": "hil", "passed": True, "metrics": {"drop_rate": 0.01}}],
                "all_passed": True,
            }
        )
    )
    return manifest


def test_legacy_report_files_are_first_class_sources(tmp_path):
    _publish_legacy(tmp_path, 1.0)
    sources = legacy_sources(tmp_path)
    assert len(sources) == 1
    assert sources[0].kind == "legacy"
    assert sources[0].target == "esp32"
    assert sources[0].report()["suites"][0]["metrics"]["mean_ms"] == 1.0


def test_malformed_report_files_are_skipped(tmp_path):
    _publish_legacy(tmp_path, 1.0)
    (tmp_path / "report_broken.json").write_text("{ not json")
    (tmp_path / "report_unrelated.json").write_text(json.dumps({"other": True}))
    assert len(legacy_sources(tmp_path)) == 1


def test_recorded_runs_become_sources(tmp_path):
    store = RunStore(tmp_path)
    _record_run(store, "20260101T000000-a", "2026-01-01T00:00:00+00:00", RunStatus.PASSED)
    sources = run_sources(store)
    assert len(sources) == 1
    assert sources[0].kind == "run"
    assert sources[0].manifest is not None
    assert sources[0].passed is True


def test_a_run_without_a_report_is_not_offered_as_a_source(tmp_path):
    store = RunStore(tmp_path)
    store.create(RunManifest(run_id="empty-1", status=RunStatus.FAILED))
    assert run_sources(store) == []
    assert load_run_report(store, "empty-1") is None


def test_all_sources_drops_the_duplicate_legacy_copy_of_a_recorded_run(tmp_path):
    """A recorded run also writes report_<timestamp>.json; the richer run
    entry must win so the list is not doubled."""
    store = RunStore(tmp_path)
    manifest = _record_run(
        store, "20260101T000000-a", "2026-01-01T00:00:00+00:00", RunStatus.PASSED
    )
    (tmp_path / "report_2026-01-01T00-00-00+00-00.json").write_text(
        json.dumps(
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "meta": {"target": {"name": "sim"}},
                "suites": [{"name": "hil", "passed": True, "metrics": {}}],
                "all_passed": True,
            }
        )
    )
    sources = all_sources(store, tmp_path)
    assert [s.id for s in sources] == [manifest.run_id]


def test_all_sources_keeps_independent_legacy_reports(tmp_path):
    store = RunStore(tmp_path)
    _record_run(store, "20260102T000000-b", "2026-01-02T00:00:00+00:00", RunStatus.PASSED)
    _publish_legacy(tmp_path, 3.0)  # a separate `eaiv run` invocation
    sources = all_sources(store, tmp_path)
    assert {s.kind for s in sources} == {"run", "legacy"}
    assert sources[0].timestamp >= sources[1].timestamp  # newest first


def test_activity_points_are_oldest_first_for_plotting(tmp_path):
    store = RunStore(tmp_path)
    _record_run(store, "20260101T000000-a", "2026-01-01T00:00:00+00:00", RunStatus.PASSED)
    _record_run(store, "20260102T000000-b", "2026-01-02T00:00:00+00:00", RunStatus.FAILED)
    points = recent_activity(store)
    assert [p.run_id for p in points] == ["20260101T000000-a", "20260102T000000-b"]


def test_stage_timeline_includes_stages_not_reached_yet():
    manifest = RunManifest(run_id="r1")
    manifest.upsert_stage(StageRecord("build", StageStatus.SKIPPED))
    manifest.upsert_stage(StageRecord("validate", StageStatus.RUNNING))
    rows = stage_timeline(manifest)
    by_stage = {r["stage"]: r["status"] for r in rows}
    assert by_stage["build"] == "skipped"
    assert by_stage["validate"] == "running"
    assert by_stage["compare"] == "pending"  # not started, still shown
    assert by_stage["save_baseline"] == "pending"


def test_stage_timeline_includes_unexpected_stage_names():
    manifest = RunManifest(run_id="r1")
    manifest.upsert_stage(StageRecord("custom_stage", StageStatus.OK))
    assert "custom_stage" in {r["stage"] for r in stage_timeline(manifest)}


# -- signal analysis -------------------------------------------------------


def test_signals_are_grouped_by_physical_meaning():
    groups = group_signals(["t_s", "gx", "gy", "gz", "ax", "ay", "az", "roll", "custom_field"])
    assert groups["Gyroscope (rad/s)"] == ["gx", "gy", "gz"]
    assert groups["Accelerometer (g)"] == ["ax", "ay", "az"]
    assert groups["Orientation (deg)"] == ["roll"]
    # Nothing is dropped: a plugin's own telemetry field is still plottable.
    assert groups["Other"] == ["custom_field"]
    assert "t_s" not in [c for members in groups.values() for c in members]


def test_sampling_analysis_measures_rate_and_finds_gaps():
    times = [i * 0.01 for i in range(100)]
    del times[50:55]  # a 50 ms hole
    report = analyze_sampling(times, declared_rate_hz=100.0)
    assert report.samples == 95
    assert 90 < report.mean_rate_hz < 100
    assert len(report.gaps) == 1
    assert report.missing_estimate == 5
    assert report.rate_matches_declaration is False
    assert any("gap" in issue for issue in report.issues)


def test_clean_capture_reports_no_issues():
    report = analyze_sampling([i * 0.01 for i in range(200)], declared_rate_hz=100.0)
    assert report.gaps == []
    assert report.non_monotonic == 0
    assert report.rate_matches_declaration is True
    assert report.issues == []


def test_non_monotonic_timestamps_are_reported():
    report = analyze_sampling([0.0, 0.01, 0.005, 0.02])
    assert report.non_monotonic == 1
    assert any("backwards" in issue for issue in report.issues)


def test_sampling_analysis_handles_degenerate_input():
    assert analyze_sampling([]).samples == 0
    assert analyze_sampling([1.0]).mean_rate_hz == 0.0


def test_outliers_are_found_with_a_median_based_score():
    values = [1.0] * 100 + [50.0]
    stats = analyze_signal("gx", values)
    assert stats.count == 101
    assert stats.outliers == 1
    assert stats.outlier_indices == [100]
    assert stats.median == 1.0


def test_a_uniform_signal_has_no_outliers():
    stats = analyze_signal("gx", [1.0, 1.0, 1.0, 1.0])
    assert stats.outliers == 0
    assert stats.stdev == 0.0


def test_signal_stats_ignore_missing_values():
    stats = analyze_signal("gx", [1.0, float("nan"), 3.0, None])
    assert stats.count == 2
    assert stats.mean == 2.0


def test_orientation_error_reports_rmse_bias_and_drift():
    times = [i * 0.1 for i in range(601)]  # 60 s
    reference = [0.0] * len(times)
    estimated = [t * (1.0 / 60.0) for t in times]  # exactly 1 deg/min of drift
    error = orientation_error(times, estimated, reference, "roll")
    assert error is not None
    assert error.drift_deg_per_min == pytest.approx(1.0, abs=1e-6)
    assert error.max_error_deg == pytest.approx(1.0, abs=1e-6)
    assert error.mean_error_deg > 0
    assert error.samples == 601


def test_orientation_error_needs_at_least_two_samples():
    assert orientation_error([0.0], [0.0], [0.0]) is None


def test_reference_pairs_finds_matching_columns():
    columns = ["t_s", "roll", "roll_ref_deg", "pitch", "pitch_ref_deg", "yaw"]
    assert reference_pairs(columns) == [
        ("roll", "roll", "roll_ref_deg"),
        ("pitch", "pitch", "pitch_ref_deg"),
    ]
    assert reference_pairs(["t_s", "gx"]) == []


def test_committed_datasets_pass_the_signal_analysis():
    """The shipped replay logs must be clean by the lab's own standards."""
    import csv
    from pathlib import Path

    dataset = Path("datasets/imu/imu_run1.csv")
    if not dataset.exists():  # pragma: no cover - datasets are committed
        pytest.skip("committed dataset not present")
    with dataset.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    times = [float(r["t_s"]) for r in rows]
    report = analyze_sampling(times)
    assert report.non_monotonic == 0
    assert report.gaps == []
