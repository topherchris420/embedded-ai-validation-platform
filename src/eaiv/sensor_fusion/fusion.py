"""Orientation-fusion filters: complementary, Mahony, Madgwick, Kalman, EKF.

All filters operate on a stream of (dt, gyro_xyz_rad_s, accel_xyz_g) and
produce a running roll/pitch (and, for quaternion filters, yaw) estimate in
degrees. These are intentionally compact reference implementations for
benchmarking/regression purposes, not a full AHRS library.

Filters are registered as ``fusion_filter`` plugins, so external packages
can add algorithms without touching this module; ``build_filter`` resolves
names through the plugin registry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol, cast


@dataclass
class Orientation:
    roll_deg: float
    pitch_deg: float
    yaw_deg: float = 0.0


class FusionFilter(Protocol):
    """Structural interface every fusion filter (built-in or plugin) satisfies."""

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation: ...


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
        return float(s["angle"])

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation:
        gx, gy, _ = gyro
        ax, ay, az = accel
        acc_roll = math.degrees(math.atan2(ay, az))
        acc_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))

        roll = self._step("roll", math.degrees(gx), acc_roll, dt)
        pitch = self._step("pitch", math.degrees(gy), acc_pitch, dt)
        return Orientation(roll, pitch)


class MadgwickFilter:
    """Madgwick gradient-descent AHRS (IMU variant, gyro + accelerometer).

    Maintains a full orientation quaternion; yaw is reported but drifts
    without a magnetometer.
    """

    def __init__(self, beta: float = 0.1) -> None:
        self.beta = beta
        self.q = [1.0, 0.0, 0.0, 0.0]  # w, x, y, z

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation:
        q0, q1, q2, q3 = self.q
        gx, gy, gz = gyro
        ax, ay, az = accel

        # Quaternion rate from gyroscope
        qd0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        qd1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy)
        qd2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx)
        qd3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx)

        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if norm > 1e-12:
            ax, ay, az = ax / norm, ay / norm, az / norm

            # Objective function: rotated gravity vs measured accel
            f1 = 2.0 * (q1 * q3 - q0 * q2) - ax
            f2 = 2.0 * (q0 * q1 + q2 * q3) - ay
            f3 = 2.0 * (0.5 - q1 * q1 - q2 * q2) - az

            # Gradient (J^T * f)
            s0 = -2.0 * q2 * f1 + 2.0 * q1 * f2
            s1 = 2.0 * q3 * f1 + 2.0 * q0 * f2 - 4.0 * q1 * f3
            s2 = -2.0 * q0 * f1 + 2.0 * q3 * f2 - 4.0 * q2 * f3
            s3 = 2.0 * q1 * f1 + 2.0 * q2 * f2

            snorm = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if snorm > 1e-12:
                qd0 -= self.beta * s0 / snorm
                qd1 -= self.beta * s1 / snorm
                qd2 -= self.beta * s2 / snorm
                qd3 -= self.beta * s3 / snorm

        q0 += qd0 * dt
        q1 += qd1 * dt
        q2 += qd2 * dt
        q3 += qd3 * dt
        qnorm = math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3) or 1.0
        self.q = [q0 / qnorm, q1 / qnorm, q2 / qnorm, q3 / qnorm]
        return self._to_euler()

    def _to_euler(self) -> Orientation:
        q0, q1, q2, q3 = self.q
        roll = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1 * q1 + q2 * q2))
        sinp = max(-1.0, min(1.0, 2.0 * (q0 * q2 - q3 * q1)))
        pitch = math.asin(sinp)
        yaw = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2 * q2 + q3 * q3))
        return Orientation(math.degrees(roll), math.degrees(pitch), math.degrees(yaw))


class ExtendedKalmanFilter:
    """EKF over state [roll, pitch, gyro_bias_x, gyro_bias_y] (radians).

    Process model integrates full Euler kinematics driven by the gyro;
    measurement model is the accelerometer-derived roll/pitch. Estimating
    the gyro biases online is what distinguishes this from the independent
    1-D Kalman pair in :class:`KalmanFilter1D`.
    """

    def __init__(
        self,
        q_angle: float = 0.001,
        q_bias: float = 0.00003,
        r_measure: float = 0.03,
    ) -> None:
        import numpy as np

        self._np = np
        self.x = np.zeros(4)  # roll, pitch, bias_x, bias_y
        self.P = np.eye(4) * 0.1
        self.Q_diag = np.array([q_angle, q_angle, q_bias, q_bias])
        self.R = np.eye(2) * r_measure
        self.H = np.zeros((2, 4))
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0

    def update(self, dt: float, gyro: tuple, accel: tuple) -> Orientation:
        np = self._np
        gx, gy, gz = gyro
        ax, ay, az = accel

        phi, theta, bx, by = self.x
        p, q, r = gx - bx, gy - by, gz

        sin_phi, cos_phi = math.sin(phi), math.cos(phi)
        # Guard the tan/sec singularity at theta = +/-90 deg
        theta_c = max(-1.55, min(1.55, theta))
        tan_theta = math.tan(theta_c)
        sec2_theta = 1.0 + tan_theta * tan_theta

        # Predict: Euler kinematics
        phi_dot = p + q * sin_phi * tan_theta + r * cos_phi * tan_theta
        theta_dot = q * cos_phi - r * sin_phi
        self.x = self.x + np.array([phi_dot, theta_dot, 0.0, 0.0]) * dt

        # Jacobian of the process model
        A = np.zeros((4, 4))
        A[0, 0] = (q * cos_phi - r * sin_phi) * tan_theta
        A[0, 1] = (q * sin_phi + r * cos_phi) * sec2_theta
        A[0, 2] = -1.0
        A[0, 3] = -sin_phi * tan_theta
        A[1, 0] = -q * sin_phi - r * cos_phi
        A[1, 3] = -cos_phi
        F = np.eye(4) + A * dt

        self.P = F @ self.P @ F.T + np.diag(self.Q_diag) * dt

        # Update with accelerometer roll/pitch when the norm is sane
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if norm > 1e-12:
            z = np.array(
                [
                    math.atan2(ay, az),
                    math.atan2(-ax, math.sqrt(ay * ay + az * az)),
                ]
            )
            y = z - self.H @ self.x
            S = self.H @ self.P @ self.H.T + self.R
            K = self.P @ self.H.T @ np.linalg.inv(S)
            self.x = self.x + K @ y
            self.P = (np.eye(4) - K @ self.H) @ self.P

        return Orientation(math.degrees(self.x[0]), math.degrees(self.x[1]))


def _register_builtin_filters() -> None:
    from eaiv.plugins import get_registry, register_plugin

    builtin = {
        "complementary": (ComplementaryFilter, "First-order complementary filter"),
        "mahony": (MahonyFilter, "Mahony AHRS (proportional feedback)"),
        "madgwick": (MadgwickFilter, "Madgwick gradient-descent AHRS"),
        "kalman": (KalmanFilter1D, "Independent 1-D Kalman filters"),
        "ekf": (ExtendedKalmanFilter, "EKF with online gyro-bias estimation"),
    }

    def make_factory(cls: type) -> Callable[[dict], object]:
        def factory(cfg: dict) -> object:
            return cls(**cfg)

        return factory

    registry = get_registry()
    for name, (cls, description) in builtin.items():
        if registry.get("fusion_filter", name) is None:
            register_plugin(name, "fusion_filter", description, version="1.0.0")(make_factory(cls))


_register_builtin_filters()


def build_filter(algorithm: str, **params: object) -> FusionFilter:
    """Instantiate a fusion filter registered under ``algorithm``.

    Extra keyword arguments are forwarded to the filter constructor
    (e.g. ``build_filter("madgwick", beta=0.2)``).
    """
    from eaiv.plugins import get_registry

    registry = get_registry()
    try:
        return cast(FusionFilter, registry.create("fusion_filter", algorithm, params))
    except ValueError:
        available = [m.name for m in registry.list_plugins("fusion_filter")]
        raise ValueError(
            f"Unknown fusion algorithm: {algorithm!r} (expected one of {available})"
        ) from None
