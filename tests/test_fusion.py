"""Tests for sensor fusion filters and the CSV-replay experiment."""

from __future__ import annotations

import csv

from eaiv.sensor_fusion.experiments import FusionExperiment
from eaiv.sensor_fusion.fusion import build_filter


def test_kalman_filter_converges_to_level():
    f = build_filter("kalman")
    o = None
    for _ in range(500):
        # Steady-state level orientation: gyro ~0, accel points down (+1g on z)
        o = f.update(0.005, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert abs(o.roll_deg) < 5
    assert abs(o.pitch_deg) < 5


def test_unknown_algorithm_raises():
    try:
        build_filter("nonexistent")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_fusion_experiment_missing_file_reports_failure():
    result = FusionExperiment({"source": "does/not/exist.csv", "algorithm": "kalman"}).run()
    assert not result.passed


def test_fusion_experiment_replays_synthetic_csv(tmp_path):
    csv_path = tmp_path / "imu.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t_s", "gx", "gy", "gz", "ax", "ay", "az"])
        for i in range(100):
            writer.writerow([i * 0.005, 0, 0, 0, 0, 0, 1.0])

    result = FusionExperiment(
        {"source": str(csv_path), "algorithm": "complementary", "metrics": ["drift_deg_per_min"]}
    ).run()
    assert result.passed
    assert result.metrics["samples"] == 100


def test_madgwick_converges_to_static_tilt():
    import math

    f = build_filter("madgwick", beta=0.2)
    roll_ref = 20.0
    ay, az = math.sin(math.radians(roll_ref)), math.cos(math.radians(roll_ref))
    o = None
    for _ in range(4000):
        o = f.update(0.005, (0.0, 0.0, 0.0), (0.0, ay, az))
    assert abs(o.roll_deg - roll_ref) < 1.0
    assert abs(o.pitch_deg) < 1.0


def test_ekf_estimates_gyro_bias():
    # Constant gyro bias on x while the device sits level: the EKF should
    # absorb it into the bias state instead of drifting in roll.
    f = build_filter("ekf")
    bias = 0.05  # rad/s
    o = None
    for _ in range(4000):
        o = f.update(0.005, (bias, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert abs(o.roll_deg) < 2.0
    assert abs(f.x[2] - bias) < 0.02


def test_all_builtin_filters_run_and_stay_level():
    for name in ("complementary", "mahony", "madgwick", "kalman", "ekf"):
        f = build_filter(name)
        o = None
        for _ in range(500):
            o = f.update(0.005, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert abs(o.roll_deg) < 5, name
        assert abs(o.pitch_deg) < 5, name


def test_build_filter_forwards_params():
    f = build_filter("complementary", alpha=0.5)
    assert f.alpha == 0.5
