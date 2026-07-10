"""Sensor plugin base classes and registry.

Sensors provide data streams for sensor fusion and validation. This module
provides the plugin interface for sensor backends including IMU, GPS, barometer,
and virtual/simulated sensors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from eaiv.plugins import PluginMetadata

import numpy as np


@dataclass
class SensorReading:
    """A single sensor reading with timestamp."""
    timestamp_s: float
    values: np.ndarray  # Shape depends on sensor type


@dataclass
class IMUData:
    """IMU sensor data (accelerometer, gyroscope, magnetometer)."""
    accel_xyz_g: np.ndarray  # Accelerometer in g
    gyro_xyz_rad_s: np.ndarray  # Gyroscope in rad/s
    mag_xyz_muT: np.ndarray | None = None  # Magnetometer in microTesla


@dataclass
class GPSData:
    """GPS sensor data."""
    latitude: float  # degrees
    longitude: float  # degrees
    altitude_m: float  # meters
    hdop: float = 0.0  # Horizontal dilution of precision
    speed_m_s: float = 0.0  # Speed in m/s
    heading_deg: float = 0.0  # Heading in degrees


@dataclass
class BarometerData:
    """Barometer sensor data."""
    pressure_hpa: float  # Pressure in hectopascals
    temperature_c: float | None = None  # Temperature in Celsius
    altitude_m: float | None = None  # Calculated altitude


class Sensor(ABC):
    """Abstract sensor interface.

    Sensors provide time-series data streams. Implementations must provide:
    - read(): Get a single reading
    - stream(): Get an iterator of readings
    - info(): Get sensor metadata
    - start(): Initialize the sensor
    - stop(): Clean up the sensor
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    def start(self) -> None:
        """Initialize and start the sensor."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop and clean up the sensor."""
        ...

    @abstractmethod
    def read(self) -> SensorReading:
        """Get a single sensor reading.

        Returns:
            SensorReading with timestamp and values
        """
        ...

    @abstractmethod
    def info(self) -> dict:
        """Get sensor metadata.

        Returns:
            Dict with sensor info (type, units, sample_rate, etc.)
        """
        ...

    def stream(self) -> Iterator[SensorReading]:
        """Get an iterator of sensor readings.

        Default implementation uses read() in a loop. Override for
        more efficient implementations.
        """
        while True:
            yield self.read()


class IMUSensor(Sensor):
    """Specialized IMU sensor interface.

    Provides accelerometer, gyroscope, and optionally magnetometer data.
    """

    @abstractmethod
    def read_imu(self) -> IMUData:
        """Get IMU sensor data.

        Returns:
            IMUData with accel, gyro, optionally mag
        """
        ...


class GPSSensor(Sensor):
    """Specialized GPS sensor interface."""

    @abstractmethod
    def read_gps(self) -> GPSData:
        """Get GPS sensor data.

        Returns:
            GPSData with position, speed, heading
        """
        ...


class BarometerSensor(Sensor):
    """Specialized barometer sensor interface."""

    @abstractmethod
    def read_pressure(self) -> BarometerData:
        """Get barometer sensor data.

        Returns:
            BarometerData with pressure, temperature, altitude
        """
        ...


class VirtualSensor(Sensor):
    """Virtual/simulated sensor for testing and HIL.

    Generates synthetic data based on configuration for replay,
    fault injection, and simulation scenarios.
    """

    @abstractmethod
    def set_replay_data(self, data: list[SensorReading]) -> None:
        """Set replay data for the virtual sensor.

        Args:
            data: List of sensor readings to replay
        """
        ...

    @abstractmethod
    def inject_fault(self, fault_type: str, params: dict) -> None:
        """Inject a fault for testing.

        Args:
            fault_type: Type of fault (noise, drift, dropout, etc.)
            params: Fault parameters
        """
        ...

    @abstractmethod
    def enable_noise(self, noise_level: float) -> None:
        """Enable synthetic noise injection.

        Args:
            noise_level: Noise level (standard deviation in sensor units)
        """
        ...


class SensorPluginMixin:
    """Mixin to provide plugin metadata for sensors."""

    PLUGIN_METADATA: PluginMetadata = None  # type: ignore[assignment]


# Export plugin registration helper
from eaiv.plugins import register_plugin

__all__ = [
    "Sensor",
    "IMUSensor",
    "GPSSensor",
    "BarometerSensor",
    "VirtualSensor",
    "SensorReading",
    "IMUData",
    "GPSData",
    "BarometerData",
    "SensorPluginMixin",
    "register_plugin",
]