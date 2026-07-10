"""Tests for the synthetic IMU dataset generator and replay round-trip."""

from __future__ import annotations

import math

import pytest

from eaiv.datasets import (
    MotionProfile,
    generate_imu_trajectory,
    read_imu_csv,
    write_imu_csv,
)
from eaiv.sensor_fusion.experiments import FusionExperiment


def test_generator_is_deterministic():
    a = generate_imu_trajectory(duration_s=1, seed=5)
    b = generate_imu_trajectory(duration_s=1, seed=5)
    assert a == b
    c = generate_imu_trajectory(duration_s=1, seed=6)
    assert a != c


def test_static_profile_reads_gravity_only():
    samples = generate_imu_trajectory(
        duration_s=1, profile="static", gyro_noise_std=0.0, accel_noise_std=0.0
    )
    for s in samples:
        assert s.gx == s.gy == s.gz == 0.0
        assert (s.ax, s.ay) == (0.0, 0.0)
        assert math.isclose(s.az, 1.0)
        assert s.roll_ref_deg == s.pitch_ref_deg == 0.0


def test_reference_columns_match_trajectory_amplitude():
    profile = MotionProfile(roll_amp_deg=30, roll_freq_hz=0.5, pitch_amp_deg=0, pitch_freq_hz=0)
    samples = generate_imu_trajectory(duration_s=2, rate_hz=100, profile=profile)
    peak = max(abs(s.roll_ref_deg) for s in samples)
    assert 29.0 < peak <= 30.0


def test_csv_round_trip(tmp_path):
    samples = generate_imu_trajectory(duration_s=0.5, seed=1)
    path = write_imu_csv(samples, tmp_path / "log.csv")
    rows = read_imu_csv(path)
    assert len(rows) == len(samples)
    assert math.isclose(rows[0]["az"], samples[0].az, abs_tol=1e-5)
    assert "roll_ref_deg" in rows[0]


def test_unknown_profile_rejected():
    with pytest.raises(ValueError, match="motion profile"):
        generate_imu_trajectory(profile="warp-speed")


def test_generated_dataset_scores_well_through_fusion(tmp_path):
    path = write_imu_csv(
        generate_imu_trajectory(duration_s=5, rate_hz=100, profile="gentle", seed=42),
        tmp_path / "run.csv",
    )
    result = FusionExperiment(
        {"source": str(path), "algorithm": "madgwick", "params": {"beta": 0.2}}
    ).run()
    assert result.passed
    assert result.metrics["roll_rmse_deg"] < 5.0


def test_committed_replay_dataset_exists_and_replays():
    result = FusionExperiment({"source": "datasets/imu/imu_run1.csv", "algorithm": "ekf"}).run()
    assert result.passed
    assert result.metrics["samples"] == 2000
