"""Run comparison: compatibility, deltas, coverage changes, exports."""

from __future__ import annotations

import json
from typing import Any

from eaiv.core.comparison import (
    CompatibilityLevel,
    check_compatibility,
    compare_runs,
    to_json,
    to_markdown,
)


def _report(
    metrics: dict[str, Any],
    target: str = "esp32",
    provenance: str = "measured",
    version: str = "0.4.0",
    inputs: dict[str, Any] | None = None,
    suite: str = "tinyml",
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "meta": {
            "eaiv_version": version,
            "target": {"kind": "serial", "name": target},
            "inputs": inputs or {},
        },
        "suites": [
            {
                "name": suite,
                "passed": True,
                "metrics": metrics,
                "notes": "",
                "metric_meta": {
                    key: {"provenance": provenance, "source": "device"}
                    for key, value in metrics.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                },
            }
        ],
        "all_passed": True,
    }


def test_identical_setups_are_directly_comparable():
    comparison = compare_runs(_report({"mean_ms": 10.0}), _report({"mean_ms": 10.2}))
    assert comparison.compatibility.level is CompatibilityLevel.COMPARABLE
    assert comparison.compatibility.issues == []


def test_different_targets_block_the_comparison():
    compatibility = check_compatibility(
        _report({"mean_ms": 10.0}, target="esp32"), _report({"mean_ms": 3.0}, target="stm32h7")
    )
    assert compatibility.level is CompatibilityLevel.INCOMPARABLE
    assert not compatibility.ok
    issue = next(i for i in compatibility.issues if i.field == "Target")
    assert issue.blocking
    assert "measure the board, not the change" in issue.explanation


def test_simulated_versus_measured_blocks_the_comparison():
    compatibility = check_compatibility(
        _report({"mean_ms": 10.0}, provenance="simulated"),
        _report({"mean_ms": 3.0}, provenance="measured"),
    )
    assert compatibility.level is CompatibilityLevel.INCOMPARABLE
    assert any(i.field == "Measurement provenance" for i in compatibility.issues)


def test_changed_model_hash_is_a_caveat_not_a_blocker():
    baseline = _report(
        {"mean_ms": 10.0}, inputs={"model": {"name": "a.tflite", "sha256": "aa" * 32}}
    )
    current = _report({"mean_ms": 8.0}, inputs={"model": {"name": "b.tflite", "sha256": "bb" * 32}})
    compatibility = check_compatibility(baseline, current)
    assert compatibility.level is CompatibilityLevel.CAVEATED
    assert compatibility.ok
    issue = next(i for i in compatibility.issues if i.field == "Model")
    assert "may come from the input" in issue.explanation


def test_differing_suite_coverage_is_explained():
    baseline = _report({"mean_ms": 10.0}, suite="tinyml")
    current = _report({"drop_rate": 0.1}, suite="hil")
    compatibility = check_compatibility(baseline, current)
    issue = next(i for i in compatibility.issues if i.field == "Suite coverage")
    assert "tinyml" in issue.baseline and "hil" in issue.current


def test_version_differences_are_noted():
    compatibility = check_compatibility(
        _report({"mean_ms": 1.0}, version="0.3.0"), _report({"mean_ms": 1.0}, version="0.4.0")
    )
    assert any(i.field == "eaiv version" for i in compatibility.issues)


def test_direction_aware_verdicts():
    comparison = compare_runs(
        _report({"mean_ms": 10.0, "fps": 100.0, "attempts": 1}),
        _report({"mean_ms": 5.0, "fps": 50.0, "attempts": 2}),
        max_regression_pct=10.0,
    )
    by_metric = {c.metric: c for c in comparison.changes}
    assert by_metric["mean_ms"].status == "improved"  # lower latency is better
    assert by_metric["fps"].status == "regressed"  # lower throughput is worse
    assert by_metric["attempts"].status == "informational"  # direction unknown


def test_absolute_and_percentage_changes_are_both_available():
    comparison = compare_runs(_report({"mean_ms": 10.0}), _report({"mean_ms": 12.5}))
    change = comparison.changes[0]
    assert change.absolute_change == 2.5
    assert change.change_pct == 25.0


def test_new_and_missing_metrics_are_detected():
    comparison = compare_runs(
        _report({"mean_ms": 10.0, "retired_ms": 1.0}),
        _report({"mean_ms": 10.0, "brand_new_ms": 2.0}),
    )
    assert [c.metric for c in comparison.added] == ["brand_new_ms"]
    assert [c.metric for c in comparison.removed] == ["retired_ms"]
    assert comparison.added[0].baseline is None
    assert comparison.removed[0].current is None


def test_grouping_by_suite_sorts_by_magnitude():
    baseline = {
        "schema_version": 2,
        "meta": {"target": {"name": "esp32"}},
        "suites": [
            {"name": "a", "passed": True, "metrics": {"x_ms": 10.0, "y_ms": 10.0}},
            {"name": "b", "passed": True, "metrics": {"z_ms": 10.0}},
        ],
        "all_passed": True,
    }
    current = json.loads(json.dumps(baseline))
    current["suites"][0]["metrics"] = {"x_ms": 11.0, "y_ms": 20.0}
    grouped = compare_runs(baseline, current).by_suite()
    assert list(grouped) == ["a", "b"]
    assert [c.metric for c in grouped["a"]] == ["y_ms", "x_ms"]


def test_recommendation_holds_the_release_on_a_gated_regression():
    comparison = compare_runs(
        _report({"mean_ms": 10.0}), _report({"mean_ms": 20.0}), max_regression_pct=10.0
    )
    assert "Hold the release" in comparison.recommendation
    assert "mean_ms" in comparison.recommendation


def test_recommendation_refuses_to_conclude_from_an_incomparable_pair():
    comparison = compare_runs(
        _report({"mean_ms": 10.0}, target="esp32"), _report({"mean_ms": 1.0}, target="pico")
    )
    assert "Do not draw conclusions" in comparison.recommendation


def test_recommendation_flags_caveats_even_without_regressions():
    comparison = compare_runs(
        _report({"mean_ms": 10.0}, version="0.3.0"), _report({"mean_ms": 10.0}, version="0.4.0")
    )
    assert "differ in setup" in comparison.recommendation


def test_recommendation_endorses_a_clean_improvement():
    comparison = compare_runs(_report({"mean_ms": 10.0}), _report({"mean_ms": 5.0}))
    assert "Safe to promote" in comparison.recommendation


def test_counts_cover_every_status():
    comparison = compare_runs(
        _report({"mean_ms": 10.0, "fps": 100.0, "attempts": 1, "gone_ms": 1.0}),
        _report({"mean_ms": 5.0, "fps": 50.0, "attempts": 1, "new_ms": 1.0}),
    )
    counts = comparison.counts
    assert counts["improved"] == 1
    assert counts["regressed"] == 1
    assert counts["added"] == 1
    assert counts["removed"] == 1
    assert counts["informational"] == 1


def test_markdown_export_is_complete():
    comparison = compare_runs(
        _report({"mean_ms": 10.0}, target="esp32"),
        _report({"mean_ms": 20.0}, target="pico"),
        baseline_label="release-1",
        current_label="candidate",
    )
    markdown = to_markdown(comparison)
    assert "# Validation comparison" in markdown
    assert "release-1" in markdown and "candidate" in markdown
    assert "Not directly comparable" in markdown
    assert "## Compatibility notes" in markdown
    assert "| mean_ms |" in markdown
    assert "**Recommendation:**" in markdown


def test_json_export_round_trips():
    comparison = compare_runs(_report({"mean_ms": 10.0}), _report({"mean_ms": 12.0}))
    payload = json.loads(to_json(comparison))
    assert payload["counts"]["regressed"] == 1
    assert payload["compatibility"]["level"] == "comparable"
    assert payload["changes"][0]["metric"] == "mean_ms"
    assert payload["changes"][0]["unit"] == "ms"


def test_legacy_reports_can_be_compared_with_current_ones():
    legacy = {
        "timestamp": "2024-01-01T00:00:00+00:00",
        "meta": {"eaiv_version": "0.2.0", "target": {"kind": "serial", "name": "esp32"}},
        "suites": [{"name": "tinyml", "passed": True, "metrics": {"mean_ms": 10.0}}],
        "all_passed": True,
    }
    comparison = compare_runs(legacy, _report({"mean_ms": 11.0}))
    assert comparison.shared
    # Provenance is unknown on one side, so it is not treated as a mismatch.
    assert comparison.compatibility.ok
