"""Reusable, replay-capable datasets for validation and HIL testing.

The generator produces deterministic (seeded) synthetic IMU logs with
ground-truth orientation columns, so fusion filters can be scored with an
exact reference and regressions detected bit-for-bit across CI runs.

CSV schema (matches ``eaiv.sensor_fusion.experiments.FusionExperiment``):

    t_s, gx, gy, gz, ax, ay, az, roll_ref_deg, pitch_ref_deg

Gyro rates are rad/s, accelerometer is in g.
"""

from __future__ import annotations

from eaiv.datasets.generator import (
    ImuSample,
    MotionProfile,
    generate_imu_trajectory,
    read_imu_csv,
    write_imu_csv,
)

__all__ = [
    "ImuSample",
    "MotionProfile",
    "generate_imu_trajectory",
    "read_imu_csv",
    "write_imu_csv",
]
