"""Report schema versioning, legacy migration, and metric provenance."""

from __future__ import annotations

import html
import json

import pytest

from eaiv.core.metrics import (
    MetricProvenance,
    MetricSource,
    format_value,
    infer_metric_info,
    metric_meta,
    target_provenance,
)
from eaiv.core.report_schema import (
    REPORT_SCHEMA_VERSION,
    file_identity,
    load_report_file,
    metric_info,
    normalize_report,
    overall_provenance,
    report_schema_version,
)
from eaiv.core.reporter import Reporter
from eaiv.core.results import AggregateResult, SuiteResult

LEGACY_REPORT = {
    "timestamp": "2024-05-01T10:00:00+00:00",
    "meta": {"eaiv_version": "0.2.0", "target": {"kind": "serial", "name": "esp32"}},
    "suites": [{"name": "tinyml", "passed": True, "metrics": {"mean_ms": 4.2}, "notes": "ok"}],
    "all_passed": True,
}


def test_legacy_report_has_no_schema_version_and_normalizes():
    assert report_schema_version(LEGACY_REPORT) == 1
    normalized = normalize_report(LEGACY_REPORT)
    assert normalized["legacy"] is True
    assert normalized["schema_version"] == 1
    # Every field the current shape promises is present, empty where the
    # legacy report genuinely had nothing.
    for key in ("host", "git", "config", "thresholds", "inputs", "plugins"):
        assert key in normalized["meta"]
    assert normalized["suites"][0]["metric_meta"] == {}
    assert normalized["run"] == {}


def test_normalize_does_not_mutate_its_input():
    payload = json.loads(json.dumps(LEGACY_REPORT))
    normalize_report(payload)
    assert payload == LEGACY_REPORT


def test_normalize_rejects_non_reports():
    with pytest.raises(ValueError, match="suites"):
        normalize_report({"nope": True})


def test_future_schema_versions_pass_through():
    """Forward compatibility: a newer writer must not make the file unreadable."""
    payload = {**LEGACY_REPORT, "schema_version": 99, "future_field": 1}
    normalized = normalize_report(payload)
    assert normalized["schema_version"] == 99
    assert normalized["future_field"] == 1
    # Newer than us is not "legacy" — only older payloads get that flag.
    assert normalized["legacy"] is False


def test_current_reporter_writes_the_current_schema(tmp_path):
    results = AggregateResult()
    results.add(
        SuiteResult(
            name="hil",
            passed=True,
            metrics={"drop_rate": 0.02},
            metric_meta=metric_meta(
                {"drop_rate": 0.02}, MetricProvenance.SIMULATED, MetricSource.SIMULATOR
            ),
        )
    )
    Reporter(tmp_path).publish(results, metadata={"eaiv_version": "9.9.9"}, quiet=True)
    payload = json.loads((tmp_path / "latest.json").read_text())
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["suites"][0]["metric_meta"]["drop_rate"]["provenance"] == "simulated"


def test_metric_info_prefers_declared_metadata_over_inference():
    report = normalize_report(
        {
            "suites": [
                {
                    "name": "memory",
                    "passed": True,
                    "metrics": {"rom_kb": 100},
                    "metric_meta": {
                        "rom_kb": {
                            "unit": "KB",
                            "direction": -1,
                            "provenance": "measured",
                            "source": "static-analysis",
                        }
                    },
                }
            ]
        }
    )
    info = metric_info(report, "memory", "rom_kb")
    assert info.provenance is MetricProvenance.MEASURED
    assert info.source is MetricSource.STATIC_ANALYSIS
    assert info.inferred is False

    # Undeclared metrics fall back to inference and say so.
    inferred = metric_info(report, "memory", "ram_static_kb")
    assert inferred.inferred is True
    assert inferred.provenance is MetricProvenance.UNKNOWN


def test_inference_derives_unit_and_direction_from_the_name():
    assert infer_metric_info("mean_ms").unit == "ms"
    assert infer_metric_info("mean_ms").direction == -1
    assert infer_metric_info("fps").direction == 1
    assert infer_metric_info("rom_kb").unit == "KB"
    assert infer_metric_info("roll_rmse_deg").unit == "°"
    assert infer_metric_info("attempts").direction == 0


def test_overall_provenance_summarizes_the_whole_report():
    def build(*provenances: str) -> dict:
        return normalize_report(
            {
                "suites": [
                    {
                        "name": "s",
                        "passed": True,
                        "metrics": {f"m{i}_ms": float(i) for i in range(len(provenances))},
                        "metric_meta": {
                            f"m{i}_ms": {"provenance": p} for i, p in enumerate(provenances)
                        },
                    }
                ]
            }
        )

    assert overall_provenance(build("measured", "measured")) == "measured"
    assert overall_provenance(build("simulated", "mock")) == "simulated"
    assert overall_provenance(build("measured", "simulated")) == "mixed"
    assert overall_provenance(normalize_report(LEGACY_REPORT)) == "unknown"


def test_qemu_and_sim_targets_are_never_reported_as_measured():
    for kind in ("sim", "qemu", "mock"):
        provenance, source = target_provenance({"kind": kind})
        assert provenance is MetricProvenance.SIMULATED
        assert source is MetricSource.SIMULATOR
    provenance, source = target_provenance({"kind": "serial"})
    assert provenance is MetricProvenance.MEASURED
    assert source is MetricSource.DEVICE


def test_metric_meta_skips_non_numeric_values():
    meta = metric_meta(
        {"mean_ms": 1.0, "backend": "mock", "ok": True},
        MetricProvenance.MOCK,
        MetricSource.HOST,
    )
    assert set(meta) == {"mean_ms"}


def test_format_value_is_consistent_and_carries_units():
    info = infer_metric_info("mean_ms")
    assert format_value(1.5, info) == "1.500 ms"
    assert format_value(1234.5, info) == "1,234.5 ms"
    assert format_value(0.000123, info) == "0.000123 ms"
    assert format_value(True) == "yes"
    assert format_value("mock") == "mock"


def test_file_identity_hashes_inputs(tmp_path):
    model = tmp_path / "model.tflite"
    model.write_bytes(b"weights")
    identity = file_identity(model)
    assert identity["exists"] is True
    assert identity["size_bytes"] == 7
    assert len(identity["sha256"]) == 64

    missing = file_identity(tmp_path / "nope.tflite")
    assert missing["exists"] is False
    assert "sha256" not in missing


def test_load_report_file_reports_precise_errors(tmp_path):
    bad = tmp_path / "report.json"
    bad.write_text("{ not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_report_file(bad)
    with pytest.raises(ValueError, match="Cannot read"):
        load_report_file(tmp_path / "absent.json")


def test_html_report_escapes_untrusted_notes_and_metrics(tmp_path):
    """Device output and plugin-supplied metric names reach the HTML
    report verbatim; neither may be interpreted as markup."""
    results = AggregateResult()
    results.add(
        SuiteResult(
            name="firmware",
            passed=False,
            metrics={"<img src=x onerror=alert(1)>": 1},
            notes="<script>alert('device said this')</script>",
        )
    )
    Reporter(tmp_path).publish(results, quiet=True)
    document = (tmp_path / "report.html").read_text()
    # No live markup survives: the payloads appear only in escaped form,
    # so the browser renders them as text instead of executing them.
    assert "<script>alert(" not in document
    assert "<img src=x" not in document
    assert html.escape("<script>alert('device said this')</script>") in document
    assert "&lt;img src=x onerror=alert(1)&gt;" in document


def test_markdown_report_labels_simulated_runs(tmp_path):
    results = AggregateResult()
    results.add(
        SuiteResult(
            name="hil",
            passed=True,
            metrics={"drop_rate": 0.01},
            metric_meta=metric_meta(
                {"drop_rate": 0.01}, MetricProvenance.SIMULATED, MetricSource.SIMULATOR
            ),
        )
    )
    Reporter(tmp_path).publish(results, quiet=True)
    markdown = (tmp_path / "report.md").read_text()
    assert "Measurement provenance: **simulated**" in markdown
    assert "without physical hardware" in markdown


def test_csv_keeps_its_original_leading_columns(tmp_path):
    results = AggregateResult()
    results.add(SuiteResult(name="tinyml", passed=True, metrics={"mean_ms": 2.0}))
    Reporter(tmp_path).publish(results, quiet=True)
    header = (tmp_path / "report.csv").read_text().splitlines()[0]
    assert header.startswith("suite,metric,value,passed")
