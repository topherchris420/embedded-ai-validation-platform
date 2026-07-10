"""Tests for the RT profiler, including the synthetic-trace fallback."""

from __future__ import annotations

from eaiv.rt_perf.profiler import RTProfiler


def test_rt_profiler_synthetic_fallback_no_target():
    spec = {
        "task_set": [
            {"name": "control_loop", "period_ms": 5, "deadline_ms": 5, "wcet_budget_ms": 4},
        ],
        "duration_s": 0.05,  # keep test fast; still produces several samples
    }
    result = RTProfiler(spec, target=None).run()
    assert "control_loop" in result.metrics
    assert result.metrics["control_loop"]["samples"] > 0


def test_rt_profiler_empty_task_set_fails():
    result = RTProfiler({"task_set": [], "duration_s": 1}, target=None).run()
    assert not result.passed
