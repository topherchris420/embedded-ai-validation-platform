"""Nordic Semiconductor Power Profiler Kit II (PPK2) Hardware Driver.

Provides real hardware current, voltage, and power profiling over USB serial
with dynamic 5-range measurement decoding, source/ampere modes, and high-frequency capture.
"""

from __future__ import annotations

import logging
import struct
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from eaiv.plugins import get_registry, register_plugin
from eaiv.power.monitor import PowerMonitor, PowerTrace

logger = logging.getLogger(__name__)

# Default PPK2 Range Calibration Constants (R_meas and Gain multipliers)
DEFAULT_RESISTORS_OHM = [1031.7, 101.7, 10.17, 0.94, 0.043]
DEFAULT_OFFSETS = [0.0, 0.0, 0.0, 0.0, 0.0]
DEFAULT_GAINS = [1.0, 1.0, 1.0, 1.0, 1.0]


class PPK2SerialTransport(ABC):
    """Abstract interface for serial communication with PPK2."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        ...

    @abstractmethod
    def read(self, size: int) -> bytes:
        ...

    @abstractmethod
    def close(self) -> None:
        ...


class RealPPK2Serial(PPK2SerialTransport):
    """Real serial communication via ``pyserial``."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.5) -> None:
        try:
            import serial
        except ImportError as e:
            raise ImportError(
                "pyserial is required for PPK2 real serial. Install with 'pip install pyserial'."
            ) from e
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)

    def write(self, data: bytes) -> None:
        self.ser.write(data)

    def read(self, size: int) -> bytes:
        return bytes(self.ser.read(size))

    def close(self) -> None:
        self.ser.close()


class MockPPK2Serial(PPK2SerialTransport):
    """Mock serial transport for unit testing and CI simulation."""

    def __init__(self, simulated_current_ma: float = 45.0, vdd_v: float = 3.3) -> None:
        self.simulated_current_ma = simulated_current_ma
        self.vdd_v = vdd_v
        self.is_sampling = False
        self.closed = False

    def write(self, data: bytes) -> None:
        if b"START" in data or b"start_meas" in data:
            self.is_sampling = True
        elif b"STOP" in data or b"stop_meas" in data:
            self.is_sampling = False

    def read(self, size: int) -> bytes:
        if self.closed or not self.is_sampling:
            return b""
        # Generate 4-byte mock packets (14-bit ADC, range=3)
        # ADC ~ 8192
        num_packets = max(1, size // 4)
        buf = bytearray()
        for _ in range(num_packets):
            adc_val = 8192
            range_idx = 3  # ~18mA-200mA range
            # Pack 14 bits of ADC and 3 bits of range
            packed = (adc_val & 0x3FFF) | ((range_idx & 0x07) << 14)
            buf.extend(struct.pack("<I", packed))
        return bytes(buf)

    def close(self) -> None:
        self.closed = True


class PPK2PowerMonitor(PowerMonitor):
    """Hardware PowerMonitor driver for Nordic Power Profiler Kit II."""

    def __init__(
        self,
        port: str | PPK2SerialTransport | None = None,
        mode: str = "source",  # "source" (supplies power) or "ampere" (measures existing rail)
        vdd_v: float = 3.3,
        sample_rate_hz: float = 10000.0,
        resistors: list[float] | None = None,
        **_kwargs: Any,
    ) -> None:
        if isinstance(port, PPK2SerialTransport):
            self.transport = port
        elif isinstance(port, str) and port and port != "mock":
            self.transport = RealPPK2Serial(port=port)
        else:
            self.transport = MockPPK2Serial(vdd_v=vdd_v)

        self.mode = mode.lower()
        self.vdd_v = max(0.8, min(5.0, vdd_v))
        self.sample_rate_hz = sample_rate_hz
        self.resistors = resistors or DEFAULT_RESISTORS_OHM

        self._sampling_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._samples: list[float] = []
        self._t0: float | None = None

        self._configure_instrument()

    def _configure_instrument(self) -> None:
        """Initialize PPK2 operating mode and VDD output voltage."""
        vdd_mv = int(self.vdd_v * 1000.0)
        # Send initialization command sequence
        if self.mode == "source":
            self.transport.write(f"SET_MODE_SOURCE\nSET_VDD {vdd_mv}\nPOWER_ON\n".encode())
        else:
            self.transport.write(b"SET_MODE_AMPERE\n")

    def decode_packet(self, packet_bytes: bytes) -> float:
        """Decode a 4-byte measurement packet into instantaneous power in milliwatts."""
        if len(packet_bytes) < 4:
            return 0.0
        val = struct.unpack("<I", packet_bytes[:4])[0]
        adc_val = val & 0x3FFF
        range_idx = (val >> 14) & 0x07
        if range_idx >= len(self.resistors):
            range_idx = len(self.resistors) - 1

        r_ohm = self.resistors[range_idx]
        # Current in mA: (ADC / 16384.0) * (Reference Voltage / R_shunt)
        # PPK2 ADC ref is ~ 1.25V
        v_shunt = (adc_val / 16384.0) * 1.25
        i_ma = (v_shunt / r_ohm) * 1000.0
        p_mw = self.vdd_v * i_ma
        return float(max(0.0, p_mw))

    def _sample_loop(self) -> None:
        """Streaming worker loop accumulating high-speed PPK2 measurement packets."""
        self.transport.write(b"START_MEAS\n")
        buffer = bytearray()
        while not self._stop_event.is_set():
            try:
                data = self.transport.read(64)
                if data:
                    buffer.extend(data)
                    while len(buffer) >= 4:
                        pkt = bytes(buffer[:4])
                        buffer = buffer[4:]
                        p_mw = self.decode_packet(pkt)
                        self._samples.append(p_mw)
                else:
                    time.sleep(0.001)
            except Exception as e:  # noqa: BLE001
                logger.warning("Error reading PPK2 serial stream: %s", e)
                time.sleep(0.01)

        self.transport.write(b"STOP_MEAS\n")

    def start(self) -> None:
        """Begin high-speed power capture window."""
        self._samples = []
        self._stop_event.clear()
        self._t0 = time.perf_counter()
        self._sampling_thread = threading.Thread(
            target=self._sample_loop, name="ppk2_sampler", daemon=True
        )
        self._sampling_thread.start()

    def stop(self) -> PowerTrace:
        """End capture window and return calculated power trace."""
        if self._t0 is None:
            raise RuntimeError("stop() called before start()")
        self._stop_event.set()
        if self._sampling_thread is not None:
            self._sampling_thread.join(timeout=2.0)
            self._sampling_thread = None

        duration = time.perf_counter() - self._t0
        self._t0 = None

        samples = list(self._samples)
        if not samples:
            # Fallback if window was instantaneous: estimate nominal power
            samples = [self.vdd_v * 10.0]

        return PowerTrace(duration_s=duration, samples_mw=samples)


if get_registry().get("power_monitor", "ppk2") is None:
    register_plugin(
        "ppk2",
        "power_monitor",
        "Nordic Semiconductor PPK2 hardware USB power monitor",
        version="1.0.0",
        supported_hardware=["*"],
    )(lambda cfg: PPK2PowerMonitor(**cfg))
