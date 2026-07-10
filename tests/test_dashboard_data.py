"""Tests for the dashboard data layer (and that reports feed it correctly)."""

from __future__ import annotations

import json

from eaiv.core.reporter import Reporter
from eaiv.core.results import AggregateResult, SuiteResult
from eaiv.dashboard import (
    latency_percentiles,
    load_reports,
    metric_history,
    numeric_metrics,
    suite_status,
)


def _publish(tmp_path, mean_ms: float, passed: bool = True) -> None:
    agg = AggregateResult()
    agg.add(
        SuiteResult(
            name="tinyml",
            passed=passed,
            metrics={"mean_ms": mean_ms, "p95_ms": mean_ms * 2, "backend": "mock"},
            notes="n",
        )
    )
    Reporter(str(tmp_path)).publish(agg)


def test_load_reports_reads_reporter_output_newest_first(tmp_path):
    _publish(tmp_path, 1.0)
    _publish(tmp_path, 2.0)
    reports = load_reports(tmp_path)
    assert len(reports) == 2
    assert reports[0]["timestamp"] >= reports[1]["timestamp"]


def test_load_reports_skips_latest_json_and_garbage(tmp_path):
    _publish(tmp_path, 1.0)
    (tmp_path / "report_zz-garbage.json").write_text("{not json")
    reports = load_reports(tmp_path)
    assert len(reports) == 1  # latest.json duplicate + garbage both excluded


def test_numeric_metrics_excludes_strings(tmp_path):
    _publish(tmp_path, 1.5)
    metrics = numeric_metrics(load_reports(tmp_path)[0], "tinyml")
    assert metrics["mean_ms"] == 1.5
    assert "backend" not in metrics


def test_metric_history_is_oldest_first(tmp_path):
    _publish(tmp_path, 1.0)
    _publish(tmp_path, 2.0)
    series = metric_history(load_reports(tmp_path), "tinyml", "mean_ms")
    assert [v for _, v in series] == [1.0, 2.0]


def test_suite_status_and_percentiles(tmp_path):
    _publish(tmp_path, 3.0, passed=False)
    report = load_reports(tmp_path)[0]
    assert suite_status(report) == [("tinyml", False, "n")]
    pct = latency_percentiles(numeric_metrics(report, "tinyml"))
    assert list(pct) == ["mean_ms", "p95_ms"]


def test_load_reports_missing_dir_is_empty():
    assert load_reports("does/not/exist") == []


def test_ignores_non_report_json(tmp_path):
    (tmp_path / "report_x.json").write_text(json.dumps({"unrelated": True}))
    assert load_reports(tmp_path) == []


def test_report_target_and_legacy_fallback(tmp_path):
    from eaiv.dashboard import report_target

    assert report_target({"meta": {"target": {"name": "esp32", "kind": "serial"}}}) == "esp32"
    assert report_target({"meta": {"target": {"kind": "serial"}}}) == "serial"
    assert report_target({}) == "?"  # legacy reports without meta


def test_metric_by_target_takes_latest_per_board():
    from eaiv.dashboard import metric_by_target

    def rep(ts, target, mean):
        return {
            "timestamp": ts,
            "meta": {"target": {"name": target}},
            "suites": [{"name": "tinyml", "passed": True, "metrics": {"mean_ms": mean}}],
        }

    reports = [  # newest first, as load_reports returns them
        rep("2026-03", "esp32", 3.0),
        rep("2026-02", "pico", 9.0),
        rep("2026-01", "esp32", 5.0),  # older esp32 run must be ignored
    ]
    assert metric_by_target(reports, "tinyml", "mean_ms") == {"esp32": 3.0, "pico": 9.0}


def test_regression_counts_classify_directions():
    from eaiv.core.regression import compare_reports

    def rep(**metrics):
        return {"suites": [{"name": "s", "passed": True, "metrics": metrics}]}

    base = rep(mean_ms=10.0, fps=100.0, attempts=1)
    curr = rep(mean_ms=5.0, fps=50.0, attempts=2)  # latency improved, fps regressed
    report = compare_reports(base, curr, max_regression_pct=10.0)
    counts = report.counts()
    assert counts == {"improved": 1, "regressed": 1, "unchanged": 0, "informational": 1}
