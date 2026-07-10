"""Kalman / complementary / Mahony filters for IMU orientation fusion.

All filters operate on a stream of (dt, gyro_xyz_rad_s, accel_xyz_g) and
produce a running roll/pitch estimate in degrees. These are intentionally
compact reference implementations for benchmarking/regression purposes,
not a full AHRS library.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Orientation:
    roll_deg: float
    pitch_deg: float


class ComplementaryFilter:
    def __init__(self, alpha: float = 0.98) -> None:
        self.alpha = alpha
        self.roll = 0.0
        self.pitch = 0.0

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation:
        gx, gy, _ = gyro
        ax, ay, az = accel

        acc_roll = math.degrees(math.atan2(ay, az))
        acc_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))

        gyro_roll = self.roll + math.degrees(gx) * dt
        gyro_pitch = self.pitch + math.degrees(gy) * dt

        self.roll = self.alpha * gyro_roll + (1 - self.alpha) * acc_roll
        self.pitch = self.alpha * gyro_pitch + (1 - self.alpha) * acc_pitch
        return Orientation(self.roll, self.pitch)


class MahonyFilter:
    """Simplified Mahony AHRS (proportional-only, no magnetometer)."""

    def __init__(self, kp: float = 2.0) -> None:
        self.kp = kp
        self.roll = 0.0
        self.pitch = 0.0

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation:
        gx, gy, _ = gyro
        ax, ay, az = accel
        norm = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
        ax, ay, az = ax / norm, ay / norm, az / norm

        acc_roll = math.atan2(ay, az)
        acc_pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az))

        roll_rad = math.radians(self.roll)
        pitch_rad = math.radians(self.pitch)

        err_roll = acc_roll - roll_rad
        err_pitch = acc_pitch - pitch_rad

        roll_rate = gx + self.kp * err_roll
        pitch_rate = gy + self.kp * err_pitch

        self.roll += math.degrees(roll_rate) * dt
        self.pitch += math.degrees(pitch_rate) * dt
        return Orientation(self.roll, self.pitch)


class KalmanFilter1D:
    """Independent 1-D Kalman filters for roll and pitch, each fusing a
    gyro-integrated prediction with an accelerometer-derived measurement."""

    def __init__(self, q_angle: float = 0.001, q_bias: float = 0.003, r_measure: float = 0.03):
        self.q_angle = q_angle
        self.q_bias = q_bias
        self.r_measure = r_measure
        self._states = {
            "roll": self._new_state(),
            "pitch": self._new_state(),
        }

    @staticmethod
    def _new_state() -> dict:
        return {"angle": 0.0, "bias": 0.0, "P": [[0.0, 0.0], [0.0, 0.0]]}

    def _step(self, key: str, new_rate: float, new_angle: float, dt: float) -> float:
        s = self._states[key]
        rate = new_rate - s["bias"]
        s["angle"] += dt * rate

        P = s["P"]
        P[0][0] += dt * (dt * P[1][1] - P[0][1] - P[1][0] + self.q_angle)
        P[0][1] -= dt * P[1][1]
        P[1][0] -= dt * P[1][1]
        P[1][1] += self.q_bias * dt

        S = P[0][0] + self.r_measure
        K = [P[0][0] / S, P[1][0] / S]

        y = new_angle - s["angle"]
        s["angle"] += K[0] * y
        s["bias"] += K[1] * y

        P00, P01 = P[0][0], P[0][1]
        P[0][0] -= K[0] * P00
        P[0][1] -= K[0] * P01
        P[1][0] -= K[1] * P00
        P[1][1] -= K[1] * P01
        return s["angle"]

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation:
        gx, gy, _ = gyro
        ax, ay, az = accel
        acc_roll = math.degrees(math.atan2(ay, az))
        acc_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))

        roll = self._step("roll", math.degrees(gx), acc_roll, dt)
        pitch = self._step("pitch", math.degrees(gy), acc_pitch, dt)
        return Orientation(roll, pitch)


def build_filter(algorithm: str):
    mapping = {
        "kalman": KalmanFilter1D,
        "complementary": ComplementaryFilter,
        "mahony": MahonyFilter,
    }
    if algorithm not in mapping:
        raise ValueError(f"Unknown fusion algorithm: {algorithm!r} (expected {list(mapping)})")
    return mapping[algorithm]()
