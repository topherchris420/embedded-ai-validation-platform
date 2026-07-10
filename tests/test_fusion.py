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
