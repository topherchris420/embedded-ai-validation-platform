"""Tests for hardware IMU sensor driver plugins (MPU-6050, LSM6DS3)."""

from __future__ import annotations

import numpy as np
import pytest

from eaiv.plugins import get_registry
from eaiv.plugins.sensors import IMUData, IMUSensor
from eaiv.power.i2c import MockI2CBus
from eaiv.sensors.lsm6ds3 import (
    REG_CTRL1_XL,
    REG_CTRL2_G,
    REG_CTRL3_C,
    REG_OUTX_L_G,
    REG_OUTX_L_XL,
    LSM6DS3Sensor,
)
from eaiv.sensors.mpu6050 import (
    REG_ACCEL_CONFIG,
    REG_ACCEL_XOUT_H,
    REG_CONFIG,
    REG_GYRO_CONFIG,
    REG_GYRO_XOUT_H,
    REG_PWR_MGMT_1,
    MPU6050Sensor,
)


def test_mpu6050_start_and_configuration() -> None:
    bus = MockI2CBus()
    addr = 0x68
    sensor = MPU6050Sensor(i2c_bus=bus, address=addr, accel_range_g=4, gyro_range_dps=2000)

    sensor.start()
    assert bus.read_word_data(addr, REG_PWR_MGMT_1) == 0x0100
    assert bus.read_word_data(addr, REG_CONFIG) == 0x0300
    assert bus.read_word_data(addr, REG_ACCEL_CONFIG) == (0x08 << 8)
    assert bus.read_word_data(addr, REG_GYRO_CONFIG) == (0x18 << 8)


def test_mpu6050_read_imu_math() -> None:
    bus = MockI2CBus()
    addr = 0x68
    # Mock Accel Z = 8192 (1g at +/-4g), Gyro Z = 164 (10 deg/s at +/-2000dps)
    bus.devices[addr] = {
        REG_ACCEL_XOUT_H: 0,
        REG_ACCEL_XOUT_H + 2: 0,
        REG_ACCEL_XOUT_H + 4: 8192,
        REG_GYRO_XOUT_H: 0,
        REG_GYRO_XOUT_H + 2: 0,
        REG_GYRO_XOUT_H + 4: 164,
    }

    sensor = MPU6050Sensor(i2c_bus=bus, address=addr, accel_range_g=4, gyro_range_dps=2000)
    data = sensor.read_imu()

    assert isinstance(data, IMUData)
    assert data.accel_xyz_g[0] == 0.0
    assert data.accel_xyz_g[1] == 0.0
    assert pytest.approx(data.accel_xyz_g[2], rel=1e-2) == 1.0

    assert data.gyro_xyz_rad_s[0] == 0.0
    assert pytest.approx(data.gyro_xyz_rad_s[2], rel=1e-2) == np.radians(10.0)

    reading = sensor.read()
    assert len(reading.values) == 6
    assert sensor.info()["name"] == "mpu6050"


def test_lsm6ds3_start_and_read_math() -> None:
    bus = MockI2CBus()
    addr = 0x6A
    sensor = LSM6DS3Sensor(i2c_bus=bus, address=addr, accel_range_g=4, gyro_range_dps=2000)

    sensor.start()
    assert bus.read_word_data(addr, REG_CTRL3_C) == 0x4400
    assert bus.read_word_data(addr, REG_CTRL1_XL) == 0x4800
    assert bus.read_word_data(addr, REG_CTRL2_G) == 0x4C00

    # Mock Accel Z = 8196 (~1.0g at 0.122mg/LSB), Gyro Z = 143 (~10 deg/s at 70mdps/LSB)
    bus.devices[addr] = {
        REG_OUTX_L_G: 0,
        REG_OUTX_L_G + 2: 0,
        REG_OUTX_L_G + 4: 143,
        REG_OUTX_L_XL: 0,
        REG_OUTX_L_XL + 2: 0,
        REG_OUTX_L_XL + 4: 8196,
    }

    data = sensor.read_imu()
    assert isinstance(data, IMUData)
    assert pytest.approx(data.accel_xyz_g[2], rel=1e-2) == 1.0
    assert pytest.approx(data.gyro_xyz_rad_s[2], rel=1e-2) == np.radians(10.0)


def test_sensor_plugin_registry_discovery() -> None:
    registry = get_registry()
    mpu = registry.create("sensor", "mpu6050", {"address": 0x69})
    assert isinstance(mpu, IMUSensor)
    assert mpu.info()["name"] == "mpu6050"

    lsm = registry.create("sensor", "lsm6ds3", {"address": 0x6B})
    assert isinstance(lsm, IMUSensor)
    assert lsm.info()["name"] == "lsm6ds3"
