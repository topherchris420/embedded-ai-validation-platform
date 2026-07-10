"""Tests for the power monitor, memory benchmark, and tinyml extensions."""

from __future__ import annotations

import pytest

from eaiv.benchmarks import MemoryBenchmark
from eaiv.power import PowerTrace, SimulatedPowerMonitor, build_power_monitor
from eaiv.tinyml.benchmark import TinyMLBenchmark


def test_power_trace_energy_math():
    trace = PowerTrace(duration_s=2.0, samples_mw=[100.0, 200.0])
    assert trace.mean_mw == 150.0
    assert trace.peak_mw == 200.0
    assert trace.energy_mj == 300.0  # 150 mW * 2 s


def test_simulated_monitor_measures_window():
    monitor = SimulatedPowerMonitor(active_mw=100.0, noise_mw=0.0, seed=1)
    monitor.start()
    trace = monitor.stop()
    assert trace.duration_s >= 0.0
    assert trace.mean_mw == pytest.approx(100.0)


def test_monitor_stop_without_start_raises():
    with pytest.raises(RuntimeError, match="start"):
        SimulatedPowerMonitor().stop()


def test_build_power_monitor_via_plugin_registry():
    monitor = build_power_monitor({"kind": "sim", "active_mw": 42.0})
    assert isinstance(monitor, SimulatedPowerMonitor)
    assert monitor.active_mw == 42.0


def test_tinyml_reports_startup_and_energy_with_sim_power():
    result = TinyMLBenchmark(
        {"model": "missing.tflite", "iterations": 10, "warmup": 2, "power": {"kind": "sim"}},
        target=None,
    ).run()
    assert result.passed
    assert result.metrics["startup_ms"] >= 0.0
    assert result.metrics["mean_power_mw"] > 0.0
    assert result.metrics["energy_per_inference_mj"] > 0.0


def test_tinyml_power_is_opt_in():
    result = TinyMLBenchmark(
        {"model": "missing.tflite", "iterations": 5, "warmup": 1}, target=None
    ).run()
    assert result.passed
    assert "mean_power_mw" not in result.metrics
    assert "startup_ms" in result.metrics


def test_memory_benchmark_skips_when_binary_missing():
    result = MemoryBenchmark({"binary": "does/not/exist.elf"}).run()
    assert result.passed
    assert result.metrics.get("skipped") is True


def test_memory_benchmark_requires_binary_when_asked():
    result = MemoryBenchmark({"binary": "does/not/exist.elf", "require": True}).run()
    assert not result.passed


def test_memory_benchmark_analyzes_real_elf(tmp_path):
    elf = _minimal_elf(tmp_path)
    result = MemoryBenchmark({"binary": str(elf)}).run()
    assert result.passed
    assert result.metrics["rom_kb"] >= 0.0
    assert "ram_static_kb" in result.metrics


def test_memory_benchmark_threshold_gates(tmp_path):
    elf = _minimal_elf(tmp_path)
    result = MemoryBenchmark({"binary": str(elf), "max_rom_kb": 0.0000001}).run()
    assert not result.passed


def _minimal_elf(tmp_path):
    """Compile a trivial object into a real host ELF for footprint analysis."""
    import shutil
    import subprocess

    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    src = tmp_path / "t.c"
    src.write_text("int data[64] = {1}; int bss[64]; int main(void){return data[0]+bss[0];}\n")
    out = tmp_path / "t.elf"
    subprocess.run([cc, str(src), "-o", str(out)], check=True, capture_output=True)
    return out
