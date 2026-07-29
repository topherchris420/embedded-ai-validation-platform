"""The insight engine: which findings appear, why, and in what order.

Every test here asserts on the *reason* an insight exists, not just its
presence — the engine's value is that its conclusions are auditable.
"""

from __future__ import annotations

from typing import Any

from eaiv.core.regression import compare_reports
from eaiv.insights import (
    Confidence,
    InsightCategory,
    Severity,
    Verdict,
    blocking_insights,
    decide,
    generate_insights,
    top_insight,
)
from eaiv.runs.models import RunFailure, RunManifest, RunStatus, StageRecord, StageStatus


def _report(
    suites: list[dict[str, Any]],
    thresholds: dict[str, Any] | None = None,
    all_passed: bool | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "meta": {
            "eaiv_version": "0.4.0",
            "target": {"kind": "serial", "name": "esp32", "arch": "xtensa"},
            "thresholds": thresholds or {},
        },
        "suites": suites,
        "all_passed": all(s.get("passed") for s in suites) if all_passed is None else all_passed,
    }


def _suite(
    name: str,
    passed: bool,
    metrics: dict[str, Any],
    notes: str = "",
    provenance: str = "measured",
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "metrics": metrics,
        "notes": notes,
        "metric_meta": {
            key: {"provenance": provenance, "source": "device"}
            for key, value in metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
    }


def _ids(insights) -> list[str]:
    return [i.id for i in insights]


# -- deadlines -------------------------------------------------------------


def test_deadline_miss_is_critical_and_quotes_the_evidence():
    report = _report(
        [
            _suite(
                "rt_perf",
                False,
                {
                    "control_loop": {
                        "deadline_misses": 7,
                        "deadline_ms": 5.0,
                        "wcet_observed_ms": 6.2,
                        "wcet_budget_ms": 4.0,
                        "budget_overruns": 12,
                        "samples": 100,
                    },
                    "control_loop.deadline_misses": 7,
                },
            )
        ]
    )
    insight = next(i for i in generate_insights(report) if i.id == "deadline-miss-control_loop")
    assert insight.severity is Severity.CRITICAL
    assert insight.category is InsightCategory.DEADLINE
    assert "7 sample(s)" in insight.title
    evidence = {e.label: e.value for e in insight.evidence}
    assert evidence["Deadline"] == "5.0 ms"
    assert evidence["Worst observed execution"] == "6.2 ms"
    assert evidence["Misses"] == "7 of 100 executions"
    assert insight.action is not None
    assert "deadline_ms" in insight.action.config_path


def test_budget_overrun_without_a_miss_is_only_a_headroom_warning():
    report = _report(
        [
            _suite(
                "rt_perf",
                True,
                {
                    "inference": {
                        "deadline_misses": 0,
                        "budget_overruns": 3,
                        "wcet_budget_ms": 80.0,
                        "wcet_observed_ms": 88.0,
                        "deadline_ms": 100.0,
                        "samples": 50,
                    }
                },
            )
        ]
    )
    insight = next(i for i in generate_insights(report) if i.id == "wcet-overrun-inference")
    assert insight.severity is Severity.MEDIUM
    assert insight.category is InsightCategory.HEADROOM
    assert "deadline was still met" in insight.impact


# -- budgets ---------------------------------------------------------------


def test_exceeded_memory_budget_is_critical_with_the_overshoot():
    report = _report(
        [_suite("memory", False, {"rom_kb": 620.0, "ram_static_kb": 40.0})],
        thresholds={"memory.max_rom_kb": 512.0, "memory.max_ram_kb": 128.0},
    )
    insight = next(i for i in generate_insights(report) if i.id == "budget-exceeded-rom_kb")
    assert insight.severity is Severity.CRITICAL
    assert insight.category is InsightCategory.BUDGET
    assert "108.0 KB over" in insight.title
    assert insight.magnitude == 108.0
    assert insight.confidence is Confidence.MEASURED


def test_thin_headroom_is_flagged_before_it_breaks():
    report = _report(
        [_suite("memory", True, {"rom_kb": 100.0, "ram_static_kb": 123.8})],
        thresholds={"memory.max_ram_kb": 128.0},
    )
    insight = next(i for i in generate_insights(report) if i.id == "budget-headroom-ram_static_kb")
    assert insight.severity is Severity.MEDIUM
    assert "4.2 KB of remaining budget" in insight.title
    assert insight.confidence is Confidence.DERIVED


def test_comfortable_headroom_produces_no_finding():
    report = _report(
        [_suite("memory", True, {"rom_kb": 100.0, "ram_static_kb": 40.0})],
        thresholds={"memory.max_rom_kb": 512.0, "memory.max_ram_kb": 128.0},
    )
    assert not [i for i in generate_insights(report) if i.category is InsightCategory.BUDGET]
    assert not [i for i in generate_insights(report) if i.id.startswith("budget-headroom")]


def test_no_configured_budget_means_no_budget_finding():
    report = _report([_suite("memory", True, {"rom_kb": 9_000.0})])
    assert not [i for i in generate_insights(report) if i.id.startswith("budget-")]


# -- accuracy and robustness ----------------------------------------------


def test_fusion_rmse_over_the_configured_limit():
    report = _report(
        [
            _suite(
                "fusion",
                False,
                {"roll_rmse_deg": 12.5, "pitch_rmse_deg": 3.0, "algorithm": "ekf", "samples": 500},
            )
        ],
        thresholds={"sensor_fusion.max_rmse_deg": 10.0},
    )
    insights = generate_insights(report)
    roll = next(i for i in insights if i.id == "fusion-rmse-roll")
    assert roll.severity is Severity.HIGH
    assert "configured 10° limit" in roll.title
    evidence = {e.label: e.value for e in roll.evidence}
    assert evidence["Observed RMSE"] == "12.500°"
    assert evidence["Exceeded by"] == "2.500°"
    # Pitch stayed inside the limit, so there is no pitch finding.
    assert "fusion-rmse-pitch" not in _ids(insights)


def test_fault_injected_rmse_reports_the_degradation_and_chain():
    report = _report(
        [
            _suite(
                "hil",
                False,
                {
                    "faulted_rmse_deg": 17.4,
                    "clean_rmse_deg": 0.28,
                    "drop_rate": 0.13,
                    "samples_in": 2000,
                    "samples_out": 1740,
                    "faults": ["noise", "packet_loss"],
                },
                provenance="simulated",
            )
        ],
        thresholds={"hil.max_faulted_rmse_deg": 15.0},
    )
    insight = next(i for i in generate_insights(report) if i.id == "hil-faulted-rmse")
    evidence = {e.label: e.value for e in insight.evidence}
    assert evidence["Faulted RMSE"] == "17.400°"
    assert evidence["Clean-stream RMSE"] == "0.280°"
    assert evidence["Degradation caused by faults"] == "17.120°"
    assert "noise" in evidence["Fault chain"]
    assert insight.provenance == "simulated"


def test_high_drop_rate_is_reported_separately():
    report = _report(
        [_suite("hil", True, {"drop_rate": 0.22, "samples_in": 100, "samples_out": 78})]
    )
    insight = next(i for i in generate_insights(report) if i.id == "hil-drop-rate")
    assert "22.0% of samples were dropped" in insight.title
    assert insight.severity is Severity.MEDIUM


def test_unstable_model_output_is_labelled_inferred():
    report = _report([_suite("tinyml", True, {"confidence_stability": 0.004})])
    insight = next(i for i in generate_insights(report) if i.id == "tinyml-unstable-output")
    # The engine can see the instability but not its cause, and says so.
    assert insight.confidence is Confidence.INFERRED
    assert insight.is_inferred


def test_deterministic_output_produces_no_stability_finding():
    report = _report([_suite("tinyml", True, {"confidence_stability": 0.0})])
    assert "tinyml-unstable-output" not in _ids(generate_insights(report))


# -- regressions -----------------------------------------------------------


def _regression(baseline_ms: float, current_ms: float):
    base = _report([_suite("tinyml", True, {"mean_ms": baseline_ms})])
    curr = _report([_suite("tinyml", True, {"mean_ms": current_ms})])
    return curr, compare_reports(base, curr, max_regression_pct=10.0)


def test_regression_states_the_metric_direction_and_magnitude():
    report, regression = _regression(10.0, 11.84)
    insight = next(
        i
        for i in generate_insights(report, regression=regression, baseline_name="release-1")
        if i.category is InsightCategory.REGRESSION
    )
    assert "increased 18.4%" in insight.title
    assert "release-1" in insight.title
    assert "lower is better" in insight.impact
    evidence = {e.label: e.value for e in insight.evidence}
    assert evidence["Baseline"] == "10.000 ms"
    assert evidence["This run"] == "11.840 ms"
    assert evidence["Change"] == "+18.40%"


def test_movement_inside_the_gate_is_not_a_regression():
    report, regression = _regression(10.0, 10.5)
    assert not [
        i
        for i in generate_insights(report, regression=regression)
        if i.category is InsightCategory.REGRESSION
    ]


def test_significant_improvements_are_reported_as_informational():
    report, regression = _regression(10.0, 5.0)
    insight = next(
        i for i in generate_insights(report, regression=regression) if i.id == "improvements"
    )
    assert insight.severity is Severity.INFO
    assert insight.category is InsightCategory.IMPROVEMENT
    assert "50.0%" in insight.title


# -- execution -------------------------------------------------------------


def _manifest(status: RunStatus, **kwargs) -> RunManifest:
    return RunManifest(run_id="r1", name="nightly", status=status, **kwargs)


def test_interrupted_run_outranks_everything_else():
    report = _report(
        [_suite("memory", False, {"rom_kb": 900.0})], thresholds={"memory.max_rom_kb": 512.0}
    )
    manifest = _manifest(RunStatus.INTERRUPTED)
    insights = generate_insights(report, manifest=manifest)
    assert insights[0].id == "run-interrupted"
    assert insights[0].severity is Severity.CRITICAL
    assert "cannot be used as a release decision" in insights[0].impact


def test_connection_failure_is_reported_as_such():
    manifest = _manifest(RunStatus.FAILED)
    manifest.upsert_stage(
        StageRecord(
            "validate",
            StageStatus.FAILED,
            failure=RunFailure(
                stage="validate",
                type="SerialException",
                message="could not open port /dev/ttyACM0",
                hint="Check the cable.",
            ),
        )
    )
    insight = next(
        i
        for i in generate_insights(_report([]), manifest=manifest)
        if i.id == "stage-failed-validate"
    )
    assert "Could not reach the target" in insight.title
    assert insight.action is not None and insight.action.summary == "Check the cable."


def test_a_stage_that_merely_aggregates_suite_failures_is_not_called_a_crash():
    """`validate` fails whenever a suite fails; reporting that as a crash
    would bury the actual suite diagnosis under a generic one."""
    report = _report(
        [_suite("fusion", False, {"roll_rmse_deg": 20.0, "pitch_rmse_deg": 1.0})],
        thresholds={"sensor_fusion.max_rmse_deg": 10.0},
    )
    manifest = _manifest(RunStatus.FAILED)
    manifest.upsert_stage(
        StageRecord(
            "validate",
            StageStatus.FAILED,
            failure=RunFailure(
                stage="validate", type="RuntimeError", message="1 of 1 suites failed: fusion"
            ),
        )
    )
    insights = generate_insights(report, manifest=manifest)
    assert "stage-failed-validate" not in _ids(insights)
    assert insights[0].id == "fusion-rmse-roll"


def test_a_failing_suite_always_gets_a_diagnosis():
    """Even when no threshold rule matches, the failure is explained."""
    report = _report([_suite("fusion", False, {}, notes="no data loaded from 'missing.csv'")])
    insight = next(i for i in generate_insights(report) if i.id == "suite-failed-fusion")
    assert insight.severity is Severity.HIGH
    assert "missing.csv" in " ".join(e.value for e in insight.evidence)


def test_cancelled_run_is_reported_without_alarm():
    manifest = _manifest(RunStatus.CANCELLED)
    manifest.cancel_reason = "cancelled from the dashboard"
    insight = next(
        i for i in generate_insights(_report([]), manifest=manifest) if i.id == "run-cancelled"
    )
    assert insight.severity is Severity.MEDIUM


def test_empty_report_is_critical():
    insight = next(i for i in generate_insights(_report([])) if i.id == "report-empty")
    assert insight.severity is Severity.CRITICAL


# -- provenance and coverage ----------------------------------------------


def test_a_fully_simulated_run_says_so():
    report = _report([_suite("hil", True, {"drop_rate": 0.01}, provenance="simulated")])
    insight = next(i for i in generate_insights(report) if i.id == "provenance-not-hardware")
    assert insight.title == "All measurements in this run are simulated"
    assert "cannot certify timing or power" in insight.impact


def test_a_measured_run_gets_no_provenance_caveat():
    report = _report([_suite("tinyml", True, {"mean_ms": 1.0}, provenance="measured")])
    assert "provenance-not-hardware" not in _ids(generate_insights(report))


def test_a_legacy_report_is_flagged_as_provenance_unknown():
    legacy = {"suites": [{"name": "tinyml", "passed": True, "metrics": {"mean_ms": 1.0}}]}
    assert "provenance-unknown" in _ids(generate_insights(legacy))


def test_skipped_footprint_analysis_is_a_coverage_gap():
    report = _report(
        [_suite("memory", True, {"skipped": True}, notes="skipped: binary not found ('')")]
    )
    insight = next(i for i in generate_insights(report) if i.id == "memory-skipped")
    assert insight.category is InsightCategory.COVERAGE
    assert insight.severity is Severity.MEDIUM


def test_partial_suite_selection_is_noted():
    manifest = _manifest(RunStatus.PASSED, suite_selection="fusion", suites=["fusion"])
    report = _report([_suite("fusion", True, {"roll_rmse_deg": 1.0})])
    insight = next(
        i for i in generate_insights(report, manifest=manifest) if i.id == "partial-suite-selection"
    )
    assert "not a full release gate" in insight.impact


# -- ordering and verdict --------------------------------------------------


def test_priority_order_follows_the_documented_rules():
    report = _report(
        [
            _suite("rt_perf", False, {"loop": {"deadline_misses": 1, "samples": 10}}),
            _suite("fusion", False, {"roll_rmse_deg": 30.0, "pitch_rmse_deg": 1.0}),
            _suite("memory", True, {"rom_kb": 500.0, "ram_static_kb": 126.0}),
            _suite("hil", True, {"drop_rate": 0.01}, provenance="simulated"),
        ],
        thresholds={"sensor_fusion.max_rmse_deg": 10.0, "memory.max_ram_kb": 128.0},
    )
    base = _report([_suite("hil", True, {"drop_rate": 0.001}, provenance="simulated")])
    regression = compare_reports(base, report, max_regression_pct=10.0)
    categories = [i.category for i in generate_insights(report, regression=regression)]
    order = [
        InsightCategory.DEADLINE,
        InsightCategory.REGRESSION,
        InsightCategory.ACCURACY,
        InsightCategory.HEADROOM,
        InsightCategory.PROVENANCE,
    ]
    positions = [categories.index(c) for c in order if c in categories]
    assert positions == sorted(positions)


def test_top_insight_is_the_thing_to_do_next():
    report = _report([_suite("rt_perf", False, {"loop": {"deadline_misses": 3, "samples": 10}})])
    assert top_insight(generate_insights(report)).category is InsightCategory.DEADLINE
    assert top_insight([]) is None


def test_blocking_insights_exclude_advisories():
    report = _report([_suite("hil", True, {"drop_rate": 0.01}, provenance="simulated")])
    insights = generate_insights(report)
    assert insights  # there is at least the provenance advisory
    assert blocking_insights(insights) == []


def test_verdict_blocks_on_a_critical_finding():
    report = _report([_suite("rt_perf", False, {"loop": {"deadline_misses": 3, "samples": 10}})])
    decision = decide(report, generate_insights(report))
    assert decision.verdict is Verdict.DO_NOT_SHIP
    assert "deadline" in decision.headline.lower()


def test_verdict_is_at_risk_for_a_clean_simulated_run():
    report = _report([_suite("hil", True, {"drop_rate": 0.01}, provenance="simulated")])
    decision = decide(report, generate_insights(report))
    assert decision.verdict is Verdict.SHIP_WITH_RISK
    assert "hardware validation still required" in decision.headline


def test_verdict_is_clean_only_for_measured_passing_runs():
    report = _report([_suite("tinyml", True, {"mean_ms": 1.0}, provenance="measured")])
    decision = decide(report, generate_insights(report))
    assert decision.verdict is Verdict.SHIP
    assert decision.blockers == [] and decision.risks == []


def test_verdict_without_a_report_is_unknown():
    decision = decide(None, [])
    assert decision.verdict is Verdict.UNKNOWN
    assert "Run a validation mission" in decision.reasons[0]


def test_insights_serialize_for_export():
    report = _report([_suite("rt_perf", False, {"loop": {"deadline_misses": 1, "samples": 5}})])
    payload = generate_insights(report)[0].to_dict()
    assert payload["severity"] == "critical"
    assert payload["action"]["summary"]
    assert isinstance(payload["evidence"], list)
