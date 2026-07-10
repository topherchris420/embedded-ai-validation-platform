"""Seeded synthetic IMU trajectory generator with ground-truth orientation.

The trajectory is a sum of low-frequency sinusoids in roll/pitch/yaw.
Because the Euler angles are analytic, the exact body rates and the exact
gravity direction in the body frame are known at every sample; sensor
imperfections (white noise, constant gyro bias) are then layered on top.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class MotionProfile:
    """Amplitude (deg) and frequency (Hz) per Euler axis."""

    roll_amp_deg: float
    roll_freq_hz: float
    pitch_amp_deg: float
    pitch_freq_hz: float
    yaw_amp_deg: float = 0.0
    yaw_freq_hz: float = 0.0

    @staticmethod
    def named(name: str) -> MotionProfile:
        profiles = {
            "static": MotionProfile(0.0, 0.0, 0.0, 0.0),
            "gentle": MotionProfile(15.0, 0.2, 10.0, 0.13, 20.0, 0.05),
            "aggressive": MotionProfile(45.0, 0.9, 30.0, 0.7, 90.0, 0.3),
        }
        if name not in profiles:
            raise ValueError(f"Unknown motion profile: {name!r} (expected {list(profiles)})")
        return profiles[name]


@dataclass
class ImuSample:
    t_s: float
    gx: float
    gy: float
    gz: float
    ax: float
    ay: float
    az: float
    roll_ref_deg: float
    pitch_ref_deg: float


def _euler_angles(profile: MotionProfile, t: float) -> tuple[float, float, float]:
    """Roll/pitch/yaw in radians at time t."""
    two_pi = 2.0 * math.pi
    roll = math.radians(profile.roll_amp_deg) * math.sin(two_pi * profile.roll_freq_hz * t)
    pitch = math.radians(profile.pitch_amp_deg) * math.sin(two_pi * profile.pitch_freq_hz * t)
    yaw = math.radians(profile.yaw_amp_deg) * math.sin(two_pi * profile.yaw_freq_hz * t)
    return roll, pitch, yaw


def _euler_rates(profile: MotionProfile, t: float) -> tuple[float, float, float]:
    """Analytic time-derivatives of the Euler angles (rad/s)."""
    two_pi = 2.0 * math.pi
    droll = (
        math.radians(profile.roll_amp_deg)
        * two_pi
        * profile.roll_freq_hz
        * math.cos(two_pi * profile.roll_freq_hz * t)
    )
    dpitch = (
        math.radians(profile.pitch_amp_deg)
        * two_pi
        * profile.pitch_freq_hz
        * math.cos(two_pi * profile.pitch_freq_hz * t)
    )
    dyaw = (
        math.radians(profile.yaw_amp_deg)
        * two_pi
        * profile.yaw_freq_hz
        * math.cos(two_pi * profile.yaw_freq_hz * t)
    )
    return droll, dpitch, dyaw


def generate_imu_trajectory(
    duration_s: float = 20.0,
    rate_hz: float = 100.0,
    profile: MotionProfile | str = "gentle",
    seed: int = 0,
    gyro_noise_std: float = 0.005,
    accel_noise_std: float = 0.01,
    gyro_bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[ImuSample]:
    """Generate a deterministic IMU log with ground-truth orientation.

    Args:
        duration_s: Length of the log.
        rate_hz: Sample rate.
        profile: MotionProfile or one of "static", "gentle", "aggressive".
        seed: RNG seed; identical arguments always produce identical logs.
        gyro_noise_std: White-noise standard deviation on gyro axes (rad/s).
        accel_noise_std: White-noise standard deviation on accel axes (g).
        gyro_bias: Constant rate bias per gyro axis (rad/s).
    """
    if isinstance(profile, str):
        profile = MotionProfile.named(profile)
    rng = random.Random(seed)
    dt = 1.0 / rate_hz
    n = int(duration_s * rate_hz)
    samples: list[ImuSample] = []

    for i in range(n):
        t = i * dt
        roll, pitch, yaw = _euler_angles(profile, t)
        droll, dpitch, dyaw = _euler_rates(profile, t)

        sin_r, cos_r = math.sin(roll), math.cos(roll)
        sin_p, cos_p = math.sin(pitch), math.cos(pitch)

        # Euler rates -> body rates (ZYX convention)
        p = droll - dyaw * sin_p
        q = dpitch * cos_r + dyaw * cos_p * sin_r
        r = -dpitch * sin_r + dyaw * cos_p * cos_r

        # Gravity direction in the body frame (accelerometer at rest, in g)
        ax = -sin_p
        ay = sin_r * cos_p
        az = cos_r * cos_p

        samples.append(
            ImuSample(
                t_s=round(t, 6),
                gx=p + gyro_bias[0] + rng.gauss(0.0, gyro_noise_std),
                gy=q + gyro_bias[1] + rng.gauss(0.0, gyro_noise_std),
                gz=r + gyro_bias[2] + rng.gauss(0.0, gyro_noise_std),
                ax=ax + rng.gauss(0.0, accel_noise_std),
                ay=ay + rng.gauss(0.0, accel_noise_std),
                az=az + rng.gauss(0.0, accel_noise_std),
                roll_ref_deg=math.degrees(roll),
                pitch_ref_deg=math.degrees(pitch),
            )
        )
    return samples


_CSV_COLUMNS = ["t_s", "gx", "gy", "gz", "ax", "ay", "az", "roll_ref_deg", "pitch_ref_deg"]


def write_imu_csv(samples: Iterable[ImuSample], path: str | Path) -> Path:
    """Write samples to CSV in the platform's replay schema."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_COLUMNS)
        for s in samples:
            writer.writerow(
                [
                    f"{s.t_s:.6f}",
                    f"{s.gx:.6f}",
                    f"{s.gy:.6f}",
                    f"{s.gz:.6f}",
                    f"{s.ax:.6f}",
                    f"{s.ay:.6f}",
                    f"{s.az:.6f}",
                    f"{s.roll_ref_deg:.4f}",
                    f"{s.pitch_ref_deg:.4f}",
                ]
            )
    return p


def read_imu_csv(path: str | Path) -> list[dict[str, float]]:
    """Read a replay CSV into a list of float dicts (one per row)."""
    with Path(path).open(newline="") as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]
