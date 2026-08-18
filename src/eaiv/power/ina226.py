"""Texas Instruments INA226 High-Side/Low-Side I2C Power Monitor Driver.

Provides real hardware current, voltage, and power measurements over I2C,
with programmable shunt resistance, calibration, and continuous background sampling.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from eaiv.plugins import get_registry, register_plugin
from eaiv.power.i2c import I2CBus, build_i2c_bus
from eaiv.power.monitor import PowerMonitor, PowerTrace

logger = logging.getLogger(__name__)

# INA226 Register Addresses
REG_CONFIG = 0x00
REG_SHUNTVOLTAGE = 0x01
REG_BUSVOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05
REG_MASK_ENABLE = 0x06
REG_ALERT_LIMIT = 0x07
REG_MANUFACTURER_ID = 0xFE
REG_DIE_ID = 0xFF

# Default Constants
TI_MANUFACTURER_ID = 0x5449
INA226_DIE_ID = 0x2260
SHUNT_VOLTAGE_LSB_V = 0.0000025  # 2.5 uV per LSB
BUS_VOLTAGE_LSB_V = 0.00125  # 1.25 mV per LSB


class INA226PowerMonitor(PowerMonitor):
    """Hardware PowerMonitor driver for the Texas Instruments INA226 IC."""

    def __init__(
        self,
        i2c_bus: I2CBus | dict[str, Any] | None = None,
        address: int = 0x40,
        shunt_ohms: float = 0.1,
        max_expected_a: float = 3.2,
        sample_rate_hz: float = 1000.0,
        averaging: int = 1,  # 1, 4, 16, 64, 128, 256, 512, 1024
        bus_conversion_time_us: int = 1100,
        shunt_conversion_time_us: int = 1100,
        **_kwargs: Any,
    ) -> None:
        if isinstance(i2c_bus, I2CBus):
            self.bus = i2c_bus
        elif isinstance(i2c_bus, dict):
            self.bus = build_i2c_bus(i2c_bus)
        else:
            self.bus = build_i2c_bus(None)

        self.address = address
        self.shunt_ohms = max(1e-6, shunt_ohms)
        self.max_expected_a = max(1e-4, max_expected_a)
        self.sample_rate_hz = max(1.0, sample_rate_hz)
        self.averaging = averaging
        self.bus_conversion_time_us = bus_conversion_time_us
        self.shunt_conversion_time_us = shunt_conversion_time_us

        # Calculate calibration parameters according to INA226 datasheet
        self.current_lsb_a = self.max_expected_a / 32768.0
        self.power_lsb_w = 25.0 * self.current_lsb_a
        cal_val = int(0.00512 / (self.current_lsb_a * self.shunt_ohms))
        self.calibration_val = max(1, min(0xFFFF, cal_val))

        self._configure_chip()

        # Threading state for background sampling
        self._sampling_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._samples: list[float] = []
        self._t0: float | None = None

    def _configure_chip(self) -> None:
        """Write configuration and calibration registers to the INA226."""
        # Averaging bits (11-9)
        avg_map = {1: 0, 4: 1, 16: 2, 64: 3, 128: 4, 256: 5, 512: 6, 1024: 7}
        avg_bits = avg_map.get(self.averaging, 0)

        # Conversion time bits (8-6 for VBUS, 5-3 for VSHUNT)
        conv_map = {
            140: 0,
            204: 1,
            332: 2,
            588: 3,
            1100: 4,
            2116: 5,
            4156: 6,
            8244: 7,
        }
        vbus_bits = conv_map.get(self.bus_conversion_time_us, 4)
        vshunt_bits = conv_map.get(self.shunt_conversion_time_us, 4)

        # Mode bits (2-0): 0b111 = Shunt and bus, continuous
        mode_bits = 0x07

        config_word = (avg_bits << 9) | (vbus_bits << 6) | (vshunt_bits << 3) | mode_bits
        self.bus.write_word_data(self.address, REG_CONFIG, config_word)
        self.bus.write_word_data(self.address, REG_CALIBRATION, self.calibration_val)

    @staticmethod
    def _to_signed(val: int) -> int:
        return val - 65536 if val > 32767 else val

    def read_bus_voltage_v(self) -> float:
        """Read bus supply rail voltage in Volts."""
        raw = self.bus.read_word_data(self.address, REG_BUSVOLTAGE)
        return raw * BUS_VOLTAGE_LSB_V

    def read_shunt_voltage_mv(self) -> float:
        """Read shunt differential voltage in millivolts."""
        raw = self._to_signed(self.bus.read_word_data(self.address, REG_SHUNTVOLTAGE))
        return raw * SHUNT_VOLTAGE_LSB_V * 1000.0

    def read_current_ma(self) -> float:
        """Read current in milliamperes."""
        raw = self._to_signed(self.bus.read_word_data(self.address, REG_CURRENT))
        return raw * self.current_lsb_a * 1000.0

    def read_power_mw(self) -> float:
        """Read instantaneous power in milliwatts."""
        raw = self.bus.read_word_data(self.address, REG_POWER)
        if raw > 0:
            return raw * self.power_lsb_w * 1000.0
        # If calibration register was not written or power reg is 0, compute from V * I
        v_bus = self.read_bus_voltage_v()
        i_ma = self.read_current_ma()
        return max(0.0, v_bus * i_ma)

    def _sample_loop(self) -> None:
        """Background sampling loop acquiring instantaneous power."""
        interval = 1.0 / self.sample_rate_hz
        while not self._stop_event.is_set():
            t_start = time.perf_counter()
            try:
                p_mw = self.read_power_mw()
                self._samples.append(p_mw)
            except Exception as e:  # noqa: BLE001
                logger.warning("Error reading INA226 sample: %s", e)
            dt = time.perf_counter() - t_start
            sleep_time = interval - dt
            if sleep_time > 0:
                time.sleep(sleep_time)

    def start(self) -> None:
        """Begin continuous power sampling window."""
        self._samples = []
        self._stop_event.clear()
        self._t0 = time.perf_counter()
        self._sampling_thread = threading.Thread(
            target=self._sample_loop, name="ina226_sampler", daemon=True
        )
        self._sampling_thread.start()

    def stop(self) -> PowerTrace:
        """End sampling window and return calculated power trace."""
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
            # Fallback if window was shorter than sample interval: take one point reading
            samples = [self.read_power_mw()]

        return PowerTrace(duration_s=duration, samples_mw=samples)


if get_registry().get("power_monitor", "ina226") is None:
    register_plugin(
        "ina226",
        "power_monitor",
        "Texas Instruments INA226 hardware I2C power monitor",
        version="1.0.0",
        supported_hardware=["*"],
    )(lambda cfg: INA226PowerMonitor(**cfg))
