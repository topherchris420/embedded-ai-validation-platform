"""Tests for 9-DOF Magnetometer-aware sensor fusion filters."""

from __future__ import annotations

import math

import pytest

from eaiv.sensor_fusion.fusion import EKF9DOF, MadgwickAHRS9DOF, Orientation, build_filter


def test_madgwick_9dof_level_north_convergence() -> None:
    # Level device pointing North (Accel = (0, 0, 1) g, Mag = (20, 0, 40) uT)
    filter_9dof = MadgwickAHRS9DOF(beta=0.5)
    gyro = (0.0, 0.0, 0.0)
    accel = (0.0, 0.0, 1.0)
    mag = (20.0, 0.0, 40.0)

    dt = 0.01
    o = Orientation(0.0, 0.0, 0.0)
    for _ in range(200):
        o = filter_9dof.update(dt, gyro, accel, mag)

    assert abs(o.roll_deg) < 2.0
    assert abs(o.pitch_deg) < 2.0
    assert abs(o.yaw_deg) < 2.0


def test_madgwick_9dof_east_yaw() -> None:
    # Device pointing East in NED coordinates (Mag = (0, -20, 40) uT)
    filter_9dof = MadgwickAHRS9DOF(beta=0.8)
    gyro = (0.0, 0.0, 0.0)
    accel = (0.0, 0.0, 1.0)
    mag = (0.0, -20.0, 40.0)

    dt = 0.01
    o = Orientation(0.0, 0.0, 0.0)
    for _ in range(300):
        o = filter_9dof.update(dt, gyro, accel, mag)

    assert abs(o.roll_deg) < 3.0
    assert abs(o.pitch_deg) < 3.0
    # Expected heading East is ~ +90 deg
    assert pytest.approx(o.yaw_deg, abs=5.0) == 90.0


def test_ekf_9dof_yaw_tracking() -> None:
    # EKF 9-DOF pointing North-East (45 deg)
    ekf_9dof = EKF9DOF()
    gyro = (0.0, 0.0, 0.0)
    accel = (0.0, 0.0, 1.0)
    # Mag components for 45 deg yaw: mx = 20*cos(45), my = -20*sin(45), mz = 40
    mx = 20.0 * math.cos(math.radians(45.0))
    my = -20.0 * math.sin(math.radians(45.0))
    mag = (mx, my, 40.0)

    dt = 0.01
    o = Orientation(0.0, 0.0, 0.0)
    for _ in range(100):
        o = ekf_9dof.update(dt, gyro, accel, mag)

    assert abs(o.roll_deg) < 2.0
    assert abs(o.pitch_deg) < 2.0
    assert pytest.approx(o.yaw_deg, abs=3.0) == 45.0


def test_build_filter_9dof_plugins() -> None:
    f_mad = build_filter("madgwick9dof", beta=0.2)
    assert isinstance(f_mad, MadgwickAHRS9DOF)

    f_ekf = build_filter("ekf9dof")
    assert isinstance(f_ekf, EKF9DOF)
