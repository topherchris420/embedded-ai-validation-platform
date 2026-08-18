"""STMicroelectronics LSM6DS3 6-Axis Accelerometer & Gyroscope Sensor Plugin.

Provides ultra-low-noise inertial sensing data over I2C.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from eaiv.plugins.sensors import IMUData, IMUSensor, SensorReading, register_plugin
from eaiv.power.i2c import I2CBus, build_i2c_bus

logger = logging.getLogger(__name__)

# LSM6DS3 Registers
REG_WHO_AM_I = 0x0F
REG_CTRL1_XL = 0x10
REG_CTRL2_G = 0x11
REG_CTRL3_C = 0x12
REG_OUTX_L_G = 0x22
REG_OUTX_L_XL = 0x28

# Sensitivities (g/LSB and dps/LSB)
ACCEL_SENSITIVITY_G = {
    2: 0.000061,  # +/- 2g: 0.061 mg/LSB
    4: 0.000122,  # +/- 4g: 0.122 mg/LSB
    8: 0.000244,  # +/- 8g: 0.244 mg/LSB
    16: 0.000488,  # +/- 16g: 0.488 mg/LSB
}

GYRO_SENSITIVITY_DPS = {
    125: 0.004375,  # +/- 125 dps: 4.375 mdps/LSB
    250: 0.00875,  # +/- 250 dps: 8.75 mdps/LSB
    500: 0.0175,  # +/- 500 dps: 17.5 mdps/LSB
    1000: 0.035,  # +/- 1000 dps: 35.0 mdps/LSB
    2000: 0.070,  # +/- 2000 dps: 70.0 mdps/LSB
}


class LSM6DS3Sensor(IMUSensor):
    """Hardware driver for STMicroelectronics LSM6DS3 6-DOF IMU over I2C."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        i2c_bus: I2CBus | None = None,
        address: int = 0x6A,
        accel_range_g: int = 4,
        gyro_range_dps: int = 2000,
        sample_rate_hz: float = 104.0,
    ) -> None:
        cfg = config or {}
        super().__init__(cfg)
        bus_spec = cfg.get("i2c_bus")
        if i2c_bus is not None:
            self.bus = i2c_bus
        elif isinstance(bus_spec, dict):
            self.bus = build_i2c_bus(bus_spec)
        else:
            self.bus = build_i2c_bus(None)

        self.address = int(cfg.get("address", address))
        self.accel_range_g = int(cfg.get("accel_range_g", accel_range_g))
        self.gyro_range_dps = int(cfg.get("gyro_range_dps", gyro_range_dps))
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", sample_rate_hz))

        self.accel_scale = ACCEL_SENSITIVITY_G.get(self.accel_range_g, 0.000122)
        self.gyro_scale = GYRO_SENSITIVITY_DPS.get(self.gyro_range_dps, 0.070)

        self._t0: float = time.perf_counter()
        self._started: bool = False

    def start(self) -> None:
        """Initialize LSM6DS3 registers."""
        # Enable auto-increment (IF_INC) and Block Data Update (BDU) in CTRL3_C
        self.bus.write_word_data(self.address, REG_CTRL3_C, 0x4400)
        # Configure Accelerometer (104Hz ODR, +/- 4g full scale)
        self.bus.write_word_data(self.address, REG_CTRL1_XL, 0x4800)
        # Configure Gyroscope (104Hz ODR, +/- 2000 dps full scale)
        self.bus.write_word_data(self.address, REG_CTRL2_G, 0x4C00)
        self._t0 = time.perf_counter()
        self._started = True

    def stop(self) -> None:
        self._started = False

    @staticmethod
    def _to_signed_16(val: int) -> int:
        return val - 65536 if val > 32767 else val

    def read_imu(self) -> IMUData:
        """Read 3-axis accelerometer and 3-axis gyroscope data."""
        # LSM6DS3 registers are Little-Endian
        raw_gx = self._to_signed_16(self.bus.read_word_data(self.address, REG_OUTX_L_G))
        raw_gy = self._to_signed_16(self.bus.read_word_data(self.address, REG_OUTX_L_G + 2))
        raw_gz = self._to_signed_16(self.bus.read_word_data(self.address, REG_OUTX_L_G + 4))

        raw_ax = self._to_signed_16(self.bus.read_word_data(self.address, REG_OUTX_L_XL))
        raw_ay = self._to_signed_16(self.bus.read_word_data(self.address, REG_OUTX_L_XL + 2))
        raw_az = self._to_signed_16(self.bus.read_word_data(self.address, REG_OUTX_L_XL + 4))

        deg_to_rad = np.pi / 180.0
        accel_g = np.array(
            [raw_ax * self.accel_scale, raw_ay * self.accel_scale, raw_az * self.accel_scale],
            dtype=np.float32,
        )
        gyro_rad_s = np.array(
            [
                (raw_gx * self.gyro_scale) * deg_to_rad,
                (raw_gy * self.gyro_scale) * deg_to_rad,
                (raw_gz * self.gyro_scale) * deg_to_rad,
            ],
            dtype=np.float32,
        )
        return IMUData(accel_xyz_g=accel_g, gyro_xyz_rad_s=gyro_rad_s)

    def read(self) -> SensorReading:
        data = self.read_imu()
        t = time.perf_counter() - self._t0
        values = np.concatenate([data.accel_xyz_g, data.gyro_xyz_rad_s])
        return SensorReading(timestamp_s=t, values=values)

    def info(self) -> dict[str, Any]:
        return {
            "name": "lsm6ds3",
            "type": "imu",
            "accel_range_g": self.accel_range_g,
            "gyro_range_dps": self.gyro_range_dps,
            "sample_rate_hz": self.sample_rate_hz,
            "units": {"accel": "g", "gyro": "rad/s"},
        }


@register_plugin(
    "lsm6ds3",
    "sensor",
    "STMicroelectronics LSM6DS3 6-Axis MotionTracking IMU",
    version="1.0.0",
    supported_hardware=["*"],
)
def create_lsm6ds3(config: dict) -> IMUSensor:
    return LSM6DS3Sensor(config=config)
