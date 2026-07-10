"""Tests for suite plugins, report metadata, and the extended tinyml metrics."""

from __future__ import annotations

import json

import pytest

from eaiv.config import Config
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.results import SuiteResult
from eaiv.plugins import PluginMetadata, get_registry
from eaiv.tinyml.benchmark import TinyMLBenchmark


class _DummySuite:
    def __init__(self, spec: dict) -> None:
        self.spec = spec

    def run(self) -> SuiteResult:
        return SuiteResult(
            name="dummy", passed=True, metrics={"threshold": self.spec.get("threshold", 0)}
        )


@pytest.fixture()
def dummy_suite_plugin():
    registry = get_registry()
    if registry.get("suite", "dummy") is None:
        registry.register(
            PluginMetadata(name="dummy", version="1.0", description="", plugin_type="suite"),
            lambda spec: _DummySuite(spec),
        )
    yield
    registry.unregister("suite", "dummy")


def _sim_cfg(**extra) -> Config:
    return Config(
        {
            "target": {"kind": "sim", "binary": "fw.elf", "sim": {"telemetry_lines": 3}},
            "firmware": {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
            "tinyml": {"model": "missing.tflite", "iterations": 3, "warmup": 1},
            "sensor_fusion": {"source": "datasets/imu/imu_run1.csv", "algorithm": "complementary"},
            "rt_perf": {"task_set": [], "duration_s": 1},
            **extra,
        }
    )


def test_extra_suite_plugin_runs(tmp_path, dummy_suite_plugin):
    cfg = _sim_cfg(extra_suites={"dummy": {"threshold": 7}})
    results = Orchestrator(cfg, report_dir=str(tmp_path)).run("dummy")
    names = [r.name for r in results]
    assert names == ["dummy"]
    assert results.suites[0].metrics["threshold"] == 7


def test_extra_suite_included_in_all(tmp_path, dummy_suite_plugin):
    cfg = _sim_cfg(extra_suites={"dummy": {}})
    results = Orchestrator(cfg, report_dir=str(tmp_path)).run("all")
    assert "dummy" in [r.name for r in results]


def test_unknown_suite_lists_available(tmp_path):
    with pytest.raises(ValueError, match="firmware"):
        Orchestrator(_sim_cfg(), report_dir=str(tmp_path)).run("nope")


def test_report_carries_target_metadata(tmp_path):
    Orchestrator(_sim_cfg(), report_dir=str(tmp_path)).run("firmware")
    payload = json.loads((tmp_path / "latest.json").read_text())
    assert payload["meta"]["target"]["kind"] == "sim"
    assert payload["meta"]["target"]["name"] == "sim"
    assert payload["meta"]["target"]["arch"] == "virtual"
    assert payload["meta"]["eaiv_version"]
    md = (tmp_path / "report.md").read_text()
    assert "Target: sim (virtual)" in md


def test_tinyml_emits_dashboard_percentiles_and_stability():
    result = TinyMLBenchmark(
        {"model": "missing.tflite", "iterations": 5, "warmup": 1}, target=None
    ).run()
    for key in ("p50_ms", "p95_ms", "fps", "confidence_stability"):
        assert key in result.metrics, key
    # Mock runtime is deterministic: outputs must be bit-stable.
    assert result.metrics["confidence_stability"] == 0.0
    # Mock backend has no tensor details; the estimate must be absent, not wrong.
    assert "tensor_arena_est_kb" not in result.metrics
