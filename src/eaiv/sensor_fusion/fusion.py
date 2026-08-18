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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast


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


class MadgwickAHRS9DOF:
    """9-DOF Madgwick gradient-descent AHRS fusing gyro, accel, and magnetometer.

    Compensates for magnetic distortion and provides drift-free yaw heading.
    """

    def __init__(self, beta: float = 0.1) -> None:
        self.beta = beta
        self.q = [1.0, 0.0, 0.0, 0.0]

    def update(
        self,
        dt: float,
        gyro: tuple[float, float, float] | tuple[float, ...],
        accel: tuple[float, float, float] | tuple[float, ...],
        mag: tuple[float, float, float] | tuple[float, ...] | None = None,
    ) -> Orientation:
        q0, q1, q2, q3 = self.q
        gx, gy, gz = gyro[0], gyro[1], gyro[2]
        ax, ay, az = accel[0], accel[1], accel[2]

        # Rate of change of quaternion from gyroscope
        qd0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        qd1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy)
        qd2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx)
        qd3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx)

        a_norm = math.sqrt(ax * ax + ay * ay + az * az)
        if a_norm > 1e-12:
            ax, ay, az = ax / a_norm, ay / a_norm, az / a_norm

            m_norm = math.sqrt(mag[0] ** 2 + mag[1] ** 2 + mag[2] ** 2) if mag else 0.0
            if mag is not None and m_norm > 1e-12:
                mx, my, mz = mag[0] / m_norm, mag[1] / m_norm, mag[2] / m_norm

                # Reference direction of Earth's magnetic field
                h_x = 2.0 * (
                    mx * (0.5 - q2 * q2 - q3 * q3)
                    + my * (q1 * q2 - q0 * q3)
                    + mz * (q1 * q3 + q0 * q2)
                )
                h_y = 2.0 * (
                    mx * (q1 * q2 + q0 * q3)
                    + my * (0.5 - q1 * q1 - q3 * q3)
                    + mz * (q2 * q3 - q0 * q1)
                )
                h_z = 2.0 * (
                    mx * (q1 * q3 - q0 * q2)
                    + my * (q2 * q3 + q0 * q1)
                    + mz * (0.5 - q1 * q1 - q2 * q2)
                )
                bx = math.sqrt(h_x * h_x + h_y * h_y)
                bz = h_z

                # Objective function [f_g; f_b]
                f1 = 2.0 * (q1 * q3 - q0 * q2) - ax
                f2 = 2.0 * (q0 * q1 + q2 * q3) - ay
                f3 = 2.0 * (0.5 - q1 * q1 - q2 * q2) - az
                f4 = 2.0 * bx * (0.5 - q2 * q2 - q3 * q3) + 2.0 * bz * (q1 * q3 - q0 * q2) - mx
                f5 = 2.0 * bx * (q1 * q2 - q0 * q3) + 2.0 * bz * (q0 * q1 + q2 * q3) - my
                f6 = 2.0 * bx * (q0 * q2 + q1 * q3) + 2.0 * bz * (0.5 - q1 * q1 - q2 * q2) - mz

                # Gradient J^T * f
                s0 = (
                    -2.0 * q2 * f1
                    + 2.0 * q1 * f2
                    - 2.0 * bz * q2 * f4
                    - 2.0 * bx * q3 * f5
                    + 2.0 * (bz * q1 + bx * q2) * f6
                )
                s1 = (
                    2.0 * q3 * f1
                    + 2.0 * q0 * f2
                    - 4.0 * q1 * f3
                    + 2.0 * bz * q3 * f4
                    + 2.0 * bx * q2 * f5
                    + 2.0 * (bx * q3 - 2.0 * bz * q1) * f6
                )
                s2 = (
                    -2.0 * q0 * f1
                    + 2.0 * q3 * f2
                    - 4.0 * q2 * f3
                    - 4.0 * bx * q2 * f4
                    + 2.0 * (bx * q1 + bz * q3) * f5
                    + 2.0 * (bx * q0 - 2.0 * bz * q2) * f6
                )
                s3 = (
                    2.0 * q1 * f1
                    + 2.0 * q2 * f2
                    - 4.0 * bx * q3 * f4
                    + 2.0 * (bz * q2 - bx * q0) * f5
                    + 2.0 * bx * q1 * f6
                )
            else:
                # 6-DOF fallback
                f1 = 2.0 * (q1 * q3 - q0 * q2) - ax
                f2 = 2.0 * (q0 * q1 + q2 * q3) - ay
                f3 = 2.0 * (0.5 - q1 * q1 - q2 * q2) - az
                s0 = -2.0 * q2 * f1 + 2.0 * q1 * f2
                s1 = 2.0 * q3 * f1 + 2.0 * q0 * f2 - 4.0 * q1 * f3
                s2 = -2.0 * q0 * f1 + 2.0 * q3 * f2 - 4.0 * q2 * f3
                s3 = 2.0 * q1 * f1 + 2.0 * q2 * f2

            s_norm = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if s_norm > 1e-12:
                qd0 -= self.beta * s0 / s_norm
                qd1 -= self.beta * s1 / s_norm
                qd2 -= self.beta * s2 / s_norm
                qd3 -= self.beta * s3 / s_norm

        q0 += qd0 * dt
        q1 += qd1 * dt
        q2 += qd2 * dt
        q3 += qd3 * dt
        q_norm = math.sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3) or 1.0
        self.q = [q0 / q_norm, q1 / q_norm, q2 / q_norm, q3 / q_norm]
        return self._to_euler()

    def _to_euler(self) -> Orientation:
        q0, q1, q2, q3 = self.q
        roll = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1 * q1 + q2 * q2))
        sinp = max(-1.0, min(1.0, 2.0 * (q0 * q2 - q3 * q1)))
        pitch = math.asin(sinp)
        yaw = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2 * q2 + q3 * q3))
        return Orientation(math.degrees(roll), math.degrees(pitch), math.degrees(yaw))


class EKF9DOF:
    """9-DOF Extended Kalman Filter estimating [roll, pitch, yaw, bx, by, bz]."""

    def __init__(
        self,
        q_angle: float = 0.001,
        q_bias: float = 0.00003,
        r_accel: float = 0.03,
        r_mag: float = 0.05,
    ) -> None:
        import numpy as np

        self._np = np
        self.x = np.zeros(6)  # roll, pitch, yaw, bx, by, bz
        self.P = np.eye(6) * 0.1
        self.Q_diag = np.array([q_angle, q_angle, q_angle, q_bias, q_bias, q_bias])
        self.r_accel = r_accel
        self.r_mag = r_mag

    def update(
        self,
        dt: float,
        gyro: tuple[float, float, float] | tuple[float, ...],
        accel: tuple[float, float, float] | tuple[float, ...],
        mag: tuple[float, float, float] | tuple[float, ...] | None = None,
    ) -> Orientation:
        np = self._np
        gx, gy, gz = gyro[0], gyro[1], gyro[2]
        ax, ay, az = accel[0], accel[1], accel[2]

        phi, theta, _psi, bx, by, bz = self.x
        p, q, r = gx - bx, gy - by, gz - bz

        sin_phi, cos_phi = math.sin(phi), math.cos(phi)
        theta_c = max(-1.55, min(1.55, theta))
        tan_theta = math.tan(theta_c)
        cos_theta = math.cos(theta_c)
        sec_theta = 1.0 / cos_theta if abs(cos_theta) > 1e-6 else 1.0

        # Predict
        phi_dot = p + (q * sin_phi + r * cos_phi) * tan_theta
        theta_dot = q * cos_phi - r * sin_phi
        psi_dot = (q * sin_phi + r * cos_phi) * sec_theta
        self.x = self.x + np.array([phi_dot, theta_dot, psi_dot, 0.0, 0.0, 0.0]) * dt

        # Process Jacobian F
        F = np.eye(6)
        F[0, 3] = -dt
        F[1, 4] = -dt
        F[2, 5] = -dt
        self.P = F @ self.P @ F.T + np.diag(self.Q_diag) * dt

        # Accel measurement update
        a_norm = math.sqrt(ax * ax + ay * ay + az * az)
        if a_norm > 1e-12:
            acc_roll = math.atan2(ay, az)
            acc_pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az))
            H_a = np.zeros((2, 6))
            H_a[0, 0] = 1.0
            H_a[1, 1] = 1.0
            R_a = np.eye(2) * self.r_accel
            z_a = np.array([acc_roll, acc_pitch])
            y_a = z_a - H_a @ self.x
            S_a = H_a @ self.P @ H_a.T + R_a
            K_a = self.P @ H_a.T @ np.linalg.inv(S_a)
            self.x = self.x + K_a @ y_a
            self.P = (np.eye(6) - K_a @ H_a) @ self.P

        # Mag measurement update for yaw
        if mag is not None:
            mx, my, mz = mag[0], mag[1], mag[2]
            m_norm = math.sqrt(mx * mx + my * my + mz * mz)
            if m_norm > 1e-12:
                phi, theta = self.x[0], self.x[1]
                sin_p, cos_p = math.sin(phi), math.cos(phi)
                sin_t, cos_t = math.sin(theta), math.cos(theta)
                mag_x_comp = mx * cos_t + my * sin_p * sin_t + mz * cos_p * sin_t
                mag_y_comp = my * cos_p - mz * sin_p
                mag_yaw = math.atan2(-mag_y_comp, mag_x_comp)

                H_m = np.zeros((1, 6))
                H_m[0, 2] = 1.0
                R_m = np.array([[self.r_mag]])

                res_yaw = (mag_yaw - self.x[2] + math.pi) % (2.0 * math.pi) - math.pi
                S_m = H_m @ self.P @ H_m.T + R_m
                K_m = self.P @ H_m.T @ np.linalg.inv(S_m)
                self.x = self.x + (K_m @ np.array([res_yaw])).ravel()
                self.P = (np.eye(6) - K_m @ H_m) @ self.P

        return Orientation(
            math.degrees(self.x[0]), math.degrees(self.x[1]), math.degrees(self.x[2])
        )


def _register_builtin_filters() -> None:
    from eaiv.plugins import get_registry, register_plugin

    builtin = {
        "complementary": (ComplementaryFilter, "First-order complementary filter"),
        "mahony": (MahonyFilter, "Mahony AHRS (proportional feedback)"),
        "madgwick": (MadgwickFilter, "Madgwick gradient-descent AHRS"),
        "madgwick9dof": (MadgwickAHRS9DOF, "9-DOF Madgwick AHRS with magnetometer"),
        "kalman": (KalmanFilter1D, "Independent 1-D Kalman filters"),
        "ekf": (ExtendedKalmanFilter, "EKF with online gyro-bias estimation"),
        "ekf9dof": (EKF9DOF, "9-DOF EKF with online gyro-bias and magnetometer heading"),
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
