"""I2C Bus transport abstraction for hardware power monitors.

Provides a unified interface for communicating over I2C buses via:
- Linux native i2c-dev / smbus2
- PyFTDI USB-to-I2C bridge (FT232H / FT2232H)
- In-memory Mock I2C bus for headless unit testing and CI
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class I2CBus(ABC):
    """Abstract interface for 16-bit big-endian register operations on I2C devices."""

    @abstractmethod
    def read_word_data(self, address: int, register: int) -> int:
        """Read a 16-bit word from a register (Big-Endian / MSB first)."""
        ...

    @abstractmethod
    def write_word_data(self, address: int, register: int, value: int) -> None:
        """Write a 16-bit word to a register (Big-Endian / MSB first)."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release bus resources."""
        ...


class LinuxI2CBus(I2CBus):
    """I2C bus implementation backed by Linux `/dev/i2c-N` via ``smbus2``."""

    def __init__(self, bus_number: int = 1) -> None:
        self.bus_number = bus_number
        try:
            from smbus2 import SMBus
        except ImportError as e:
            raise ImportError(
                "smbus2 package is required for LinuxI2CBus. Install with 'pip install smbus2'."
            ) from e
        self._bus = SMBus(bus_number)

    def read_word_data(self, address: int, register: int) -> int:
        # INA226 registers are Big-Endian (MSB then LSB).
        # smbus2 read_word_data is Little-Endian on standard x86/ARM Linux architectures,
        # so we read two raw bytes or byte-swap standard word response.
        raw_bytes = self._bus.read_i2c_block_data(address, register, 2)
        return int((int(raw_bytes[0]) << 8) | int(raw_bytes[1]))

    def write_word_data(self, address: int, register: int, value: int) -> None:
        msb = (value >> 8) & 0xFF
        lsb = value & 0xFF
        self._bus.write_i2c_block_data(address, register, [msb, lsb])

    def close(self) -> None:
        self._bus.close()


class PyFtdiI2CBus(I2CBus):
    """I2C bus implementation over FTDI USB bridges (FT232H, FT2232H) via ``pyftdi``."""

    def __init__(self, url: str = "ftdi://ftdi:232h/1", frequency: float = 400000.0) -> None:
        self.url = url
        self.frequency = frequency
        try:
            from pyftdi.i2c import I2cController
        except ImportError as e:
            raise ImportError(
                "pyftdi package is required for PyFtdiI2CBus. Install with 'pip install pyftdi'."
            ) from e
        self._i2c = I2cController()
        self._i2c.configure(url, frequency=frequency)
        self._ports: dict[int, Any] = {}

    def _get_port(self, address: int) -> Any:
        if address not in self._ports:
            self._ports[address] = self._i2c.get_port(address)
        return self._ports[address]

    def read_word_data(self, address: int, register: int) -> int:
        port = self._get_port(address)
        data = port.read_from(register, 2)
        return int((int(data[0]) << 8) | int(data[1]))

    def write_word_data(self, address: int, register: int, value: int) -> None:
        port = self._get_port(address)
        msb = (value >> 8) & 0xFF
        lsb = value & 0xFF
        port.write_to(register, bytes([msb, lsb]))

    def close(self) -> None:
        self._i2c.terminate()


class MockI2CBus(I2CBus):
    """In-memory mock I2C bus storing register maps per device address for testing."""

    def __init__(self, initial_registers: dict[int, dict[int, int]] | None = None) -> None:
        # device_address -> (register_address -> 16-bit uint value)
        self.devices: dict[int, dict[int, int]] = initial_registers or {}
        self.closed: bool = False

    def read_word_data(self, address: int, register: int) -> int:
        if self.closed:
            raise RuntimeError("Cannot read from a closed I2C bus")
        dev = self.devices.get(address, {})
        return dev.get(register, 0x0000)

    def write_word_data(self, address: int, register: int, value: int) -> None:
        if self.closed:
            raise RuntimeError("Cannot write to a closed I2C bus")
        if address not in self.devices:
            self.devices[address] = {}
        self.devices[address][register] = value & 0xFFFF

    def close(self) -> None:
        self.closed = True


def build_i2c_bus(spec: dict[str, Any] | None) -> I2CBus:
    """Build an I2CBus from configuration dictionary."""
    if not spec:
        return MockI2CBus()
    backend = spec.get("backend", "mock").lower()
    if backend == "mock":
        return MockI2CBus()
    if backend in ("linux", "smbus"):
        bus_num = int(spec.get("bus_number", 1))
        return LinuxI2CBus(bus_number=bus_num)
    if backend in ("ftdi", "pyftdi"):
        url = str(spec.get("url", "ftdi://ftdi:232h/1"))
        freq = float(spec.get("frequency", 400000.0))
        return PyFtdiI2CBus(url=url, frequency=freq)
    raise ValueError(f"Unknown I2C bus backend: {backend!r}. Supported: mock, linux, ftdi")
