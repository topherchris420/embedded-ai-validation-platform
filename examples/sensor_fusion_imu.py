"""Standalone example: replay an IMU CSV through the Kalman filter.

Run: python examples/sensor_fusion_imu.py
"""
from __future__ import annotations

import json

from eaiv.sensor_fusion.experiments import FusionExperiment

if __name__ == "__main__":
    spec = {
        "source": "datasets/imu_run1.csv",
        "algorithm": "kalman",
        "sample_rate_hz": 200,
        "metrics": ["rmse", "drift_deg_per_min", "lag_ms"],
    }
    result = FusionExperiment(spec).run()
    print(json.dumps(result.metrics, indent=2))
    print("PASS" if result.passed else "FAIL")
