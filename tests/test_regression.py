"""Tests for report regression comparison and the compare/datasets CLI."""

from __future__ import annotations

import json

from click.testing import CliRunner

from eaiv.cli import main
from eaiv.core.regression import compare_reports, metric_direction


def _report(**suite_metrics: dict) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "suites": [{"name": k, "passed": True, "metrics": v} for k, v in suite_metrics.items()],
        "all_passed": True,
    }


def test_metric_direction_heuristics():
    assert metric_direction("mean_ms") == -1
    assert metric_direction("roll_rmse_deg") == -1
    assert metric_direction("fps") == 1
    assert metric_direction("attempts") == 0


def test_latency_increase_is_a_regression():
    base = _report(tinyml={"mean_ms": 10.0})
    curr = _report(tinyml={"mean_ms": 12.0})
    report = compare_reports(base, curr, max_regression_pct=10.0)
    assert not report.passed
    assert report.regressions[0].metric == "mean_ms"


def test_latency_improvement_and_small_noise_pass():
    base = _report(tinyml={"mean_ms": 10.0, "fps": 100.0})
    curr = _report(tinyml={"mean_ms": 9.0, "fps": 105.0})
    assert compare_reports(base, curr).passed


def test_throughput_drop_is_a_regression():
    base = _report(tinyml={"fps": 100.0})
    curr = _report(tinyml={"fps": 80.0})
    assert not compare_reports(base, curr).passed


def test_unknown_direction_metrics_never_gate():
    base = _report(firmware={"attempts": 1})
    curr = _report(firmware={"attempts": 3})
    report = compare_reports(base, curr)
    assert report.passed
    assert len(report.deltas) == 1


def test_non_numeric_metrics_skipped():
    base = _report(fusion={"algorithm": "ekf", "roll_rmse_deg": 1.0})
    curr = _report(fusion={"algorithm": "madgwick", "roll_rmse_deg": 1.0})
    report = compare_reports(base, curr)
    assert [d.metric for d in report.deltas] == ["roll_rmse_deg"]


def test_compare_cli_gates(tmp_path):
    base = tmp_path / "base.json"
    curr = tmp_path / "curr.json"
    base.write_text(json.dumps(_report(tinyml={"mean_ms": 10.0})))
    curr.write_text(json.dumps(_report(tinyml={"mean_ms": 20.0})))

    runner = CliRunner()
    result = runner.invoke(main, ["compare", str(base), str(curr)])
    assert result.exit_code == 1
    assert "REGRESSED" in result.output

    result = runner.invoke(main, ["compare", str(base), str(base)])
    assert result.exit_code == 0


def test_datasets_generate_cli(tmp_path):
    out = tmp_path / "log.csv"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["datasets", "generate", "--duration", "1", "--rate", "50", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "wrote 50 samples" in result.output


def test_plugins_cli_lists_all_types():
    runner = CliRunner()
    result = runner.invoke(main, ["plugins"])
    assert result.exit_code == 0, result.output
    for expected in ("target", "fusion_filter", "fault"):
        assert expected in result.output


def test_flash_cli_with_simulated_target(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("target:\n  kind: sim\n  sim: {}\n")
    binary = tmp_path / "fw.elf"
    binary.write_bytes(b"\x7fELF")
    runner = CliRunner()
    result = runner.invoke(main, ["flash", str(binary), "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "flashed" in result.output
