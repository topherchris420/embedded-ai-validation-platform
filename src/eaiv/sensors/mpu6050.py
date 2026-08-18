"""MPU-6050 / MPU-6500 6-Axis MotionTracking IMU Sensor Plugin.

Provides accelerometer and gyroscope measurement data over I2C with
configurable sensitivity scales and digital low-pass filtering.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from eaiv.plugins.sensors import IMUData, IMUSensor, SensorReading, register_plugin
from eaiv.power.i2c import I2CBus, build_i2c_bus

logger = logging.getLogger(__name__)

# MPU-6050 Register Map
REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_XOUT_H = 0x3B
REG_TEMP_OUT_H = 0x41
REG_GYRO_XOUT_H = 0x43
REG_PWR_MGMT_1 = 0x6B
REG_WHO_AM_I = 0x75

# Sensitivity Scales
ACCEL_SCALE_MAP = {
    2: (0x00, 16384.0),  # +/- 2g: 16384 LSB/g
    4: (0x08, 8192.0),  # +/- 4g: 8192 LSB/g
    8: (0x10, 4096.0),  # +/- 8g: 4096 LSB/g
    16: (0x18, 2048.0),  # +/- 16g: 2048 LSB/g
}

GYRO_SCALE_MAP = {
    250: (0x00, 131.0),  # +/- 250 dps: 131.0 LSB/(deg/s)
    500: (0x08, 65.5),  # +/- 500 dps: 65.5 LSB/(deg/s)
    1000: (0x10, 32.8),  # +/- 1000 dps: 32.8 LSB/(deg/s)
    2000: (0x18, 16.4),  # +/- 2000 dps: 16.4 LSB/(deg/s)
}


class MPU6050Sensor(IMUSensor):
    """Hardware driver for MPU-6050 6-DOF IMU over I2C."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        i2c_bus: I2CBus | None = None,
        address: int = 0x68,
        accel_range_g: int = 4,
        gyro_range_dps: int = 2000,
        sample_rate_hz: float = 100.0,
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

        accel_bits, self.accel_lsb_per_g = ACCEL_SCALE_MAP.get(
            self.accel_range_g, ACCEL_SCALE_MAP[4]
        )
        gyro_bits, self.gyro_lsb_per_dps = GYRO_SCALE_MAP.get(
            self.gyro_range_dps, GYRO_SCALE_MAP[2000]
        )
        self._accel_bits = accel_bits
        self._gyro_bits = gyro_bits

        self._t0: float = time.perf_counter()
        self._started: bool = False

    def start(self) -> None:
        """Initialize MPU-6050 registers."""
        # Clear SLEEP bit in PWR_MGMT_1 and set clock to X gyro PLL
        self.bus.write_word_data(self.address, REG_PWR_MGMT_1, 0x0100)
        # Configure DLPF
        self.bus.write_word_data(self.address, REG_CONFIG, 0x0300)
        # Gyro and Accel configurations
        self.bus.write_word_data(self.address, REG_GYRO_CONFIG, (self._gyro_bits << 8))
        self.bus.write_word_data(self.address, REG_ACCEL_CONFIG, (self._accel_bits << 8))
        self._t0 = time.perf_counter()
        self._started = True

    def stop(self) -> None:
        self._started = False

    @staticmethod
    def _to_signed(val: int) -> int:
        return val - 65536 if val > 32767 else val

    def read_imu(self) -> IMUData:
        """Read 3-axis accelerometer and 3-axis gyroscope data."""
        # Read Accel X, Y, Z
        raw_ax = self._to_signed(self.bus.read_word_data(self.address, REG_ACCEL_XOUT_H))
        raw_ay = self._to_signed(self.bus.read_word_data(self.address, REG_ACCEL_XOUT_H + 2))
        raw_az = self._to_signed(self.bus.read_word_data(self.address, REG_ACCEL_XOUT_H + 4))

        # Read Gyro X, Y, Z
        raw_gx = self._to_signed(self.bus.read_word_data(self.address, REG_GYRO_XOUT_H))
        raw_gy = self._to_signed(self.bus.read_word_data(self.address, REG_GYRO_XOUT_H + 2))
        raw_gz = self._to_signed(self.bus.read_word_data(self.address, REG_GYRO_XOUT_H + 4))

        # Convert to g and rad/s
        deg_to_rad = np.pi / 180.0
        accel_g = np.array(
            [
                raw_ax / self.accel_lsb_per_g,
                raw_ay / self.accel_lsb_per_g,
                raw_az / self.accel_lsb_per_g,
            ],
            dtype=np.float32,
        )
        gyro_rad_s = np.array(
            [
                (raw_gx / self.gyro_lsb_per_dps) * deg_to_rad,
                (raw_gy / self.gyro_lsb_per_dps) * deg_to_rad,
                (raw_gz / self.gyro_lsb_per_dps) * deg_to_rad,
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
            "name": "mpu6050",
            "type": "imu",
            "accel_range_g": self.accel_range_g,
            "gyro_range_dps": self.gyro_range_dps,
            "sample_rate_hz": self.sample_rate_hz,
            "units": {"accel": "g", "gyro": "rad/s"},
        }


@register_plugin(
    "mpu6050",
    "sensor",
    "InvenSense MPU-6050 6-Axis MotionTracking IMU",
    version="1.0.0",
    supported_hardware=["*"],
)
def create_mpu6050(config: dict) -> IMUSensor:
    return MPU6050Sensor(config=config)
