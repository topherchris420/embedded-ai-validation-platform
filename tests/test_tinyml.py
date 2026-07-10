"""Tests for the tinyml benchmark using the built-in mock model backend."""

from __future__ import annotations

from eaiv.tinyml.benchmark import TinyMLBenchmark
from eaiv.tinyml.metrics import LatencyStats, estimate_macs


def test_benchmark_runs_with_mock_model(tmp_path):
    spec = {
        "model": str(tmp_path / "does_not_exist.tflite"),
        "iterations": 5,
        "warmup": 1,
    }
    result = TinyMLBenchmark(spec, target=None).run()
    assert result.passed
    assert result.metrics["count"] == 5
    assert result.metrics["backend"] == "mock"


def test_latency_stats_summary():
    stats = LatencyStats()
    for s in [0.010, 0.012, 0.011, 0.020, 0.009]:
        stats.add(s)
    summary = stats.summary()
    assert summary["count"] == 5
    assert summary["mean_ms"] > 0
    assert summary["max_ms"] >= summary["min_ms"]


def test_estimate_macs_nonzero():
    assert estimate_macs((1, 128, 128, 3), (1, 10)) > 0
