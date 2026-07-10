"""Tests for the HIL fault models, simulator, simulated target, and suite."""

from __future__ import annotations

import pytest

from eaiv.hil import (
    GaussianNoise,
    HILExperiment,
    PacketLoss,
    SensorOutage,
    SimulatedTarget,
    Simulator,
    TimingJitter,
    build_fault,
    synthetic_imu_stream,
)
from eaiv.firmware.tester import FirmwareTester
from eaiv.targets import build_target


def _static_stream(n: int = 100, dt: float = 0.01):
    for i in range(n):
        yield i * dt, {"gx": 0.0, "gy": 0.0, "gz": 0.0, "ax": 0.0, "ay": 0.0, "az": 1.0}


def test_noise_perturbs_only_selected_fields():
    fault = GaussianNoise(std=0.5, fields=["az"], seed=3)
    t, values = fault.apply(0.0, {"ax": 0.0, "az": 1.0})
    assert values["ax"] == 0.0
    assert values["az"] != 1.0


def test_packet_loss_drop_rate_close_to_probability():
    sim = Simulator(_static_stream(2000), [PacketLoss(probability=0.2, seed=42)])
    result = sim.run(keep_samples=False)
    assert result.total == 2000
    assert 0.15 < result.drop_rate < 0.25


def test_packet_loss_rejects_bad_probability():
    with pytest.raises(ValueError):
        PacketLoss(probability=1.5)


def test_timing_jitter_keeps_timestamps_monotonic():
    sim = Simulator(_static_stream(500, dt=0.001), [TimingJitter(std_s=0.005, seed=1)])
    times = [t for t, _ in sim.stream()]
    assert all(b > a for a, b in zip(times, times[1:]))


def test_outage_drops_window_only():
    sim = Simulator(_static_stream(100, dt=0.01), [SensorOutage(start_s=0.2, duration_s=0.3)])
    result = sim.run()
    assert result.dropped == 30
    assert all(not (0.2 <= t < 0.5) for t, _ in result.samples)


def test_fault_chain_composes():
    sim = Simulator(
        _static_stream(1000),
        [GaussianNoise(std=0.01, seed=0), PacketLoss(probability=0.1, seed=0)],
    )
    result = sim.run()
    assert result.dropped > 0
    assert result.emitted + result.dropped == 1000


def test_build_fault_from_config():
    fault = build_fault({"kind": "noise", "std": 0.2})
    assert isinstance(fault, GaussianNoise)
    with pytest.raises(ValueError, match="kind"):
        build_fault({"std": 0.2})


def test_simulated_target_runs_firmware_suite():
    target = build_target({"kind": "sim", "binary": "fake.elf", "sim": {"telemetry_lines": 5}})
    assert isinstance(target, SimulatedTarget)
    spec = {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]}
    result = FirmwareTester(spec, target).run()
    assert result.passed


def test_simulated_target_failure_mode():
    target = build_target({"kind": "sim", "binary": "fake.elf", "sim": {"fail": True}})
    spec = {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]}
    result = FirmwareTester(spec, target).run()
    assert not result.passed


def test_synthetic_stream_matches_generator_schema():
    first = next(synthetic_imu_stream(duration_s=0.1, rate_hz=100))
    t, values = first
    assert t == 0.0
    assert {"gx", "gy", "gz", "ax", "ay", "az", "roll_ref_deg"} <= set(values)


def test_hil_experiment_reports_degradation():
    result = HILExperiment(
        {
            "source": "datasets/imu/imu_run1.csv",
            "algorithm": "madgwick",
            "params": {"beta": 0.2},
            "faults": [
                {"kind": "noise", "std": 0.05, "fields": ["gx", "gy", "gz"], "seed": 2},
                {"kind": "packet_loss", "probability": 0.02, "seed": 1},
            ],
        }
    ).run()
    assert result.passed
    assert result.metrics["samples_dropped"] > 0
    assert result.metrics["faulted_rmse_deg"] >= 0.0
    assert "degradation_deg" in result.metrics


def test_hil_experiment_missing_dataset_fails_cleanly():
    result = HILExperiment({"source": "nope/missing.csv"}).run()
    assert not result.passed
    assert "not found" in result.notes
