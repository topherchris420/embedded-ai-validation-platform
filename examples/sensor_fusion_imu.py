"""Example 1: validate an IMU fusion algorithm against a replay dataset.

Replays a recorded IMU log (with ground-truth orientation columns) through
two fusion filters and compares their RMSE — the workflow for qualifying a
filter change before it ships.

Run: python examples/sensor_fusion_imu.py
"""

from __future__ import annotations

from eaiv.sensor_fusion.experiments import FusionExperiment

DATASET = "datasets/imu/imu_run1.csv"

if __name__ == "__main__":
    for algorithm, params in (("ekf", {}), ("madgwick", {"beta": 0.2})):
        result = FusionExperiment(
            {"source": DATASET, "algorithm": algorithm, "params": params}
        ).run()
        print(
            f"{algorithm:<10} roll_rmse={result.metrics['roll_rmse_deg']:.3f} deg  "
            f"pitch_rmse={result.metrics['pitch_rmse_deg']:.3f} deg  "
            f"{'PASS' if result.passed else 'FAIL'}"
        )
