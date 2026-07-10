"""Tests for the end-to-end validation pipeline (simulated target)."""

from __future__ import annotations

import json

from click.testing import CliRunner

from eaiv.cli import main
from eaiv.config import Config
from eaiv.core.baseline import BaselineStore
from eaiv.core.pipeline import ValidationPipeline


def _cfg() -> Config:
    return Config(
        {
            "target": {"kind": "sim", "binary": "fw.elf", "sim": {"telemetry_lines": 5}},
            "firmware": {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
            "tinyml": {"model": "missing.tflite", "iterations": 3, "warmup": 1},
        }
    )


def test_pipeline_green_run_with_telemetry_and_baseline_promotion(tmp_path):
    store = BaselineStore(tmp_path / "baselines")
    pipe = ValidationPipeline(_cfg(), report_dir=str(tmp_path / "reports"), baseline_store=store)
    result = pipe.run(suite="firmware", telemetry_s=0.5, save_baseline="good")

    assert result.passed
    statuses = {s.name: s.status for s in result.stages}
    assert statuses == {
        "build": "skipped",
        "validate": "ok",
        "telemetry": "ok",
        "compare": "skipped",
        "save_baseline": "ok",
    }
    assert (tmp_path / "reports" / "telemetry.csv").exists()
    assert store.load("good")["all_passed"] is True


def test_pipeline_regression_gate_fails(tmp_path):
    store = BaselineStore(tmp_path / "baselines")
    report_dir = tmp_path / "reports"
    pipe = ValidationPipeline(_cfg(), report_dir=str(report_dir), baseline_store=store)

    assert pipe.run(suite="tinyml", save_baseline="base").passed

    # Regressed baseline: pretend the past was 100x faster.
    payload = store.load("base")
    for suite in payload["suites"]:
        if "mean_ms" in suite["metrics"]:
            suite["metrics"]["mean_ms"] /= 100.0
    store.path("base").write_text(json.dumps(payload))

    result = pipe.run(suite="tinyml", baseline="base")
    assert not result.passed
    compare = next(s for s in result.stages if s.name == "compare")
    assert compare.status == "failed"
    assert "regression" in compare.detail


def test_pipeline_failing_suite_marks_validate_and_blocks_promotion(tmp_path):
    cfg = Config(
        {
            "target": {"kind": "sim", "binary": "fw.elf", "sim": {"fail": True}},
            "firmware": {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
        }
    )
    store = BaselineStore(tmp_path / "baselines")
    pipe = ValidationPipeline(cfg, report_dir=str(tmp_path / "r"), baseline_store=store)
    result = pipe.run(suite="firmware", save_baseline="never")

    assert not result.passed
    statuses = {s.name: s.status for s in result.stages}
    assert statuses["validate"] == "failed"
    assert statuses["save_baseline"] == "failed"  # refuses to promote a failing run
    assert not store.path("never").exists()


def test_pipeline_build_failure_reported(tmp_path, monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        class P:
            returncode = 1
            stdout = "error: no such board"

        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    pipe = ValidationPipeline(_cfg(), report_dir=str(tmp_path / "r"))
    result = pipe.run(suite="firmware", build_env="esp32")
    build = next(s for s in result.stages if s.name == "build")
    assert build.status == "failed"
    assert "no such board" in build.detail
    assert not result.passed


def test_pipeline_cli(tmp_path):
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "target: {kind: sim, binary: fw.elf, sim: {telemetry_lines: 3}}\n"
        "firmware: {timeout_s: 1, retries: 0, pass_patterns: [ALL_TESTS_OK]}\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "pipeline",
            "--config",
            str(cfg_file),
            "--suite",
            "firmware",
            "--report-dir",
            str(tmp_path / "reports"),
            "--baseline-dir",
            str(tmp_path / "baselines"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "pipeline: PASS" in result.output
    assert "[     ok] validate" in result.output
