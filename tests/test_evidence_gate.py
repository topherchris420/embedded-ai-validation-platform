"""Release decisions must not become greener when evidence is lost or corrupted."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from click.testing import CliRunner

from eaiv.cli import main
from eaiv.core.baseline import BaselineStore
from eaiv.core.comparison import compare_runs, to_json, to_markdown
from eaiv.core.evidence import report_issues
from eaiv.core.metrics import MetricProvenance, MetricSource, dataset_provenance
from eaiv.core.regression import compare_reports
from eaiv.core.results import AggregateResult, SuiteResult
from eaiv.dashboard.runs import ReportSource
from eaiv.insights import Verdict, decide, generate_insights
from eaiv.runs import RunManifest, RunStatus


def report(value=10.0, **extra):
    metrics = {"mean_ms": value, **extra}
    return {
        "schema_version": 2,
        "meta": {"target": {"name": "esp32", "kind": "serial"}},
        "suites": [
            {
                "name": "tinyml",
                "passed": True,
                "metrics": metrics,
                "metric_meta": {
                    k: {"unit": "ms", "direction": -1, "provenance": "measured", "source": "device"}
                    for k in metrics
                },
            }
        ],
        "all_passed": True,
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, None, "1", True])
def test_faster_but_invalid_candidate_cannot_pass(value):
    comparison = compare_runs(report(), report(value))
    assert not comparison.passed
    assert comparison.issues
    assert "Safe to promote" not in comparison.recommendation
    # Exports must be usable by strict JSON consumers even for corrupt input.
    payload = json.loads(to_json(comparison), parse_constant=lambda v: pytest.fail(v))
    assert payload["passed"] is False
    assert payload["issues"]


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_nonfinite_baseline_is_also_invalid(side):
    base, current = report(), report(5)
    bad = base if side == "baseline" else current
    bad["suites"][0]["metrics"]["mean_ms"] = math.nan
    assert not compare_reports(base, current).passed


def test_lost_metric_blocks_even_when_remaining_latency_improves():
    comparison = compare_runs(report(10, tail_ms=20), report(5))
    assert comparison.improvements
    assert not comparison.passed
    assert any(i.code == "missing-metric" and i.metric == "tail_ms" for i in comparison.issues)
    assert "Gate blockers" in to_markdown(comparison)


def test_lost_suite_and_no_shared_metrics_cannot_pass_vacuously():
    current = report(5)
    current["suites"][0]["name"] = "other"
    result = compare_reports(report(), current)
    assert not result.passed
    assert {i.code for i in result.issues} >= {"missing-suite", "no-shared-metrics"}


@pytest.mark.parametrize(
    "field,value",
    [("unit", "us"), ("direction", 1), ("provenance", "simulated"), ("source", "host")],
)
def test_changed_measurement_definition_cannot_masquerade_as_improvement(field, value):
    current = report(1)
    current["suites"][0]["metric_meta"]["mean_ms"][field] = value
    result = compare_runs(report(), current)
    assert not result.passed
    assert not result.improvements
    assert any(field in i.message for i in result.issues)


def test_removing_metadata_cannot_bypass_the_gate():
    current = report(1)
    current["suites"][0]["metric_meta"] = {}
    assert not compare_reports(report(), current).passed


def test_explicit_metric_direction_overrides_name_guessing():
    base, current = report(10), report(5)
    for payload in (base, current):
        payload["suites"][0]["metric_meta"]["mean_ms"]["direction"] = 1
    result = compare_reports(base, current)
    assert not result.passed
    assert result.regressions[0].direction == 1


def test_mock_on_either_side_never_produces_a_gated_delta():
    for side in (0, 1):
        reports = [report(10), report(50)]
        reports[side]["suites"][0]["metric_meta"]["mean_ms"]["provenance"] = "mock"
        result = compare_reports(*reports)
        assert result.deltas[0].direction == 0
        assert not result.regressions
        assert not result.passed  # changed provenance still blocks comparison


@pytest.mark.parametrize(
    "direction,current,regressed", [(1, -1, True), (1, 1, False), (-1, -1, False), (-1, 1, True)]
)
def test_zero_baseline_preserves_direction_and_exports_strict_json(direction, current, regressed):
    base, candidate = report(0), report(current)
    for payload in (base, candidate):
        payload["suites"][0]["metric_meta"]["mean_ms"]["direction"] = direction
    result = compare_runs(base, candidate)
    assert bool(result.regressions) is regressed
    exported = json.loads(to_json(result), parse_constant=lambda v: pytest.fail(v))
    change = exported["changes"][0]
    assert change["change_pct"] is None
    assert change["percentage_defined"] is False
    assert "zero baseline" in to_markdown(result)


@pytest.mark.parametrize("limit", [-1, math.nan, math.inf, True])
def test_invalid_allowance_is_rejected(limit):
    with pytest.raises(ValueError, match="finite, non-negative"):
        compare_reports(report(), report(), limit)


@pytest.mark.parametrize("field", ["kind", "name"])
def test_target_identity_cannot_be_changed_or_deleted(field):
    current = report(1)
    del current["meta"]["target"][field]
    assert not compare_reports(report(), current).passed
    current["meta"]["target"][field] = "different"
    assert not compare_reports(report(), current).passed


def test_failing_candidate_with_better_numbers_is_not_promotable():
    candidate = report(1)
    candidate["suites"][0]["passed"] = False
    comparison = compare_runs(report(), candidate)
    assert not comparison.passed
    assert "Hold the release" in comparison.recommendation
    assert decide(candidate).verdict is Verdict.DO_NOT_SHIP


@pytest.mark.parametrize(
    "mutation", ["duplicate", "bad-status", "bad-suite", "bad-metrics", "bad-meta", "bad-direction"]
)
def test_malformed_evidence_never_produces_a_clean_decision(mutation):
    candidate = report()
    suite = candidate["suites"][0]
    if mutation == "duplicate":
        candidate["suites"].append(copy.deepcopy(suite))
    elif mutation == "bad-status":
        suite["passed"] = "false"
    elif mutation == "bad-suite":
        candidate["suites"].append("not a suite")
    elif mutation == "bad-metrics":
        suite["metrics"] = []
    elif mutation == "bad-meta":
        candidate["meta"] = "not metadata"
    else:
        suite["metric_meta"]["mean_ms"]["direction"] = 5
    assert report_issues(candidate)
    assert not compare_runs(report(), candidate).passed
    assert decide(candidate).verdict is Verdict.DO_NOT_SHIP


@pytest.mark.parametrize("source", ["host", "dataset", "unknown", "static-analysis"])
def test_measured_does_not_mean_measured_on_device(source):
    candidate = report()
    candidate["suites"][0]["metric_meta"]["mean_ms"]["source"] = source
    decision = decide(candidate)
    assert decision.verdict is Verdict.SHIP_WITH_RISK
    assert "Target-device" in decision.headline
    assert any(i.id == "provenance-not-device" for i in generate_insights(candidate))


def test_dataset_without_metadata_is_not_invented_hardware_evidence(tmp_path):
    path = tmp_path / "unknown.csv"
    path.write_text("t_s,ax\n0,1\n")
    assert dataset_provenance(path) == (MetricProvenance.UNKNOWN, MetricSource.DATASET)


def test_empty_or_nonfinite_suite_collection_does_not_pass():
    assert not AggregateResult().all_passed()
    results = AggregateResult([SuiteResult("custom", True, {"nested": {"latency": math.nan}})])
    assert not results.all_passed()


def test_refused_promotion_preserves_existing_baseline(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(report(), "release")
    original = store.path("release").read_bytes()
    candidate = report(1)
    candidate["suites"][0]["passed"] = False
    with pytest.raises(ValueError, match="Cannot promote"):
        store.save(candidate, "release")
    assert store.path("release").read_bytes() == original


def test_interrupted_baseline_write_preserves_previous_file(tmp_path, monkeypatch):
    store = BaselineStore(tmp_path)
    store.save(report(), "release")
    original = store.path("release").read_bytes()

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("eaiv.runs.store.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.save(report(1), "release")
    assert store.path("release").read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("fmt", ["text", "json", "markdown"])
def test_cli_coverage_gate_and_exports(tmp_path, fmt):
    baseline, candidate = tmp_path / "baseline.json", tmp_path / "candidate.json"
    baseline.write_text(json.dumps(report(10, tail_ms=20)))
    candidate.write_text(json.dumps(report(1)))
    result = CliRunner().invoke(main, ["compare", str(baseline), str(candidate), "--format", fmt])
    assert result.exit_code == 1, result.output
    assert "missing-metric" in result.output
    assert "tail_ms" in result.output
    if fmt == "json":
        assert json.loads(result.output)["passed"] is False


def test_cli_promotion_failure_is_actionable(tmp_path):
    path = tmp_path / "failed.json"
    candidate = report()
    candidate["all_passed"] = False
    path.write_text(json.dumps(candidate))
    result = CliRunner().invoke(
        main, ["baseline", "save", str(path), "--name", "x", "--dir", str(tmp_path / "baselines")]
    )
    assert result.exit_code == 1
    assert "Cannot promote" in result.output
    assert not (tmp_path / "baselines" / "x.json").exists()


def test_dashboard_respects_failed_execution_even_with_a_passing_report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report()))
    source = ReportSource(
        "r", "r", "", "esp32", path, manifest=RunManifest(run_id="r", status=RunStatus.FAILED)
    )
    assert source.passed is False
    assert not compare_runs(report(), source.report()).passed


def test_evidence_issue_is_explained_by_the_insight_engine():
    candidate = report(1)
    regression = compare_reports(report(10, tail_ms=20), candidate)
    insights = generate_insights(candidate, regression=regression)
    decision = decide(candidate, insights)
    assert decision.verdict is Verdict.DO_NOT_SHIP
    assert any(i.id == "comparison-evidence-blocked" for i in decision.blockers)


def test_power_capture_stops_when_the_workload_raises(monkeypatch):
    from eaiv.power import PowerMonitor, PowerTrace
    from eaiv.tinyml.benchmark import TinyMLBenchmark

    class Monitor(PowerMonitor):
        stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True
            return PowerTrace(0.1, [10.0])

    monitor = Monitor()
    bench = TinyMLBenchmark({"runtime": "mock", "iterations": 2}, None)
    monkeypatch.setattr(bench, "_build_monitor", lambda: monitor)
    invoke = bench._invoke
    calls = 0

    def fail_during_workload(*args):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("inference disconnected")
        return invoke(*args)

    monkeypatch.setattr(bench, "_invoke", fail_during_workload)
    result = bench.run()
    assert monitor.stopped
    assert not result.passed
    assert "inference disconnected" in result.notes


def test_an_empty_power_capture_cannot_report_zero_energy(monkeypatch):
    from eaiv.power import PowerMonitor, PowerTrace
    from eaiv.tinyml.benchmark import TinyMLBenchmark

    class SilentMonitor(PowerMonitor):
        def start(self):
            pass

        def stop(self):
            return PowerTrace(1.0, [])

    bench = TinyMLBenchmark({"runtime": "mock", "iterations": 2}, None)
    monkeypatch.setattr(bench, "_build_monitor", SilentMonitor)
    result = bench.run()
    assert not result.passed
    assert "no samples" in result.notes
    assert "energy_per_inference_mj" not in result.metrics


def test_power_window_excludes_output_stability_work(monkeypatch):
    from eaiv.power import PowerMonitor, PowerTrace
    from eaiv.tinyml.benchmark import TinyMLBenchmark

    class Monitor(PowerMonitor):
        stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True
            return PowerTrace(1.0, [10.0])

    monitor = Monitor()
    bench = TinyMLBenchmark({"runtime": "mock", "iterations": 2, "warmup": 0}, None)
    monkeypatch.setattr(bench, "_build_monitor", lambda: monitor)

    def stability(*args):
        assert (
            monitor.stopped
        ), "Stability inference must not inflate energy per benchmark inference"
        return 0.0

    monkeypatch.setattr(bench, "_confidence_stability", stability)
    result = bench.run()
    assert result.passed
    assert result.metrics["energy_per_inference_mj"] == 5.0
    assert result.metric_meta["mean_power_mw"]["provenance"] == "unknown"


def test_ppk2_missing_samples_are_not_replaced_with_nominal_current():
    import time

    from eaiv.power import PPK2PowerMonitor

    monitor = PPK2PowerMonitor(port="mock")
    monitor._t0 = time.perf_counter() - 1
    assert monitor.stop().samples_mw == []
    assert monitor.measurement_origin == (MetricProvenance.SIMULATED, MetricSource.SIMULATOR)


@pytest.mark.parametrize("iterations,warmup", [(0, 0), (-1, 1), (1, -1)])
def test_empty_workloads_cannot_pass(iterations, warmup):
    from eaiv.tinyml.benchmark import TinyMLBenchmark

    result = TinyMLBenchmark({"iterations": iterations, "warmup": warmup}, None).run()
    assert not result.passed
    assert "iterations" in result.notes


def test_pipeline_cannot_promote_after_losing_baseline_coverage(tmp_path):
    from eaiv import load_config
    from eaiv.core.pipeline import ValidationPipeline

    store = BaselineStore(tmp_path / "baselines")
    pipeline = ValidationPipeline(
        load_config("configs/sim.yaml"),
        report_dir=str(tmp_path / "reports"),
        baseline_store=store,
        quiet=True,
    )
    assert pipeline.run(suite="fusion", save_baseline="reference").passed
    baseline = store.load("reference")
    baseline["suites"][0]["metrics"]["required_tail_ms"] = 10
    store.save(baseline, "reference")
    candidate = pipeline.run(suite="fusion", baseline="reference", save_baseline="candidate")
    assert not candidate.passed
    assert candidate.stage("compare").status == "failed"
    assert "required_tail_ms" in candidate.stage("compare").detail
    assert not store.path("candidate").exists()


def test_compare_page_explains_missing_evidence_without_crashing(tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    baseline, candidate = report(10, tail_ms=20), report(1)
    baseline["timestamp"] = "2026-10-21T12:00:00+00:00"
    candidate["timestamp"] = "2026-10-22T12:00:00+00:00"
    (report_dir / "report_reference.json").write_text(json.dumps(baseline))
    (report_dir / "report_candidate.json").write_text(json.dumps(candidate))
    app = AppTest.from_file(str(Path("src/eaiv/dashboard/ui/app.py").resolve()), default_timeout=20)
    app.session_state["page"] = "Compare"
    app.session_state["report_dir"] = str(report_dir)
    app.session_state["baseline_dir"] = str(tmp_path / "baselines")
    app.session_state["mission_dir"] = str(tmp_path / "missions")
    app.run()
    assert not app.exception
    assert any("Gate blocked" in error.value for error in app.error)
    assert any("missing-metric" in str(frame.value) for frame in app.dataframe)
