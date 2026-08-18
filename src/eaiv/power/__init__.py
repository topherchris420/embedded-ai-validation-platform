"""Power measurement interfaces and hardware drivers.

``PowerMonitor`` is the plugin interface for power-measurement hardware
(INA226, Nordic PPK2, Joulescope, ...). A deterministic
``SimulatedPowerMonitor`` ships as the ``sim`` plugin so power-aware
benchmarks run — and are testable — without instrumentation attached.

Hardware drivers include:
- ``INA226PowerMonitor`` (plugin: ``ina226``) - Texas Instruments I2C power monitor
- ``PPK2PowerMonitor`` (plugin: ``ppk2``) - Nordic Semiconductor Power Profiler Kit II

Usage:

    monitor = build_power_monitor({"kind": "ina226", "shunt_ohms": 0.1})
    monitor.start()
    ...workload...
    trace = monitor.stop()
    trace.mean_mw, trace.energy_mj
"""

from __future__ import annotations

from eaiv.power.i2c import (
    I2CBus,
    LinuxI2CBus,
    MockI2CBus,
    PyFtdiI2CBus,
    build_i2c_bus,
)
from eaiv.power.ina226 import INA226PowerMonitor
from eaiv.power.monitor import (
    PowerMonitor,
    PowerTrace,
    SimulatedPowerMonitor,
    build_power_monitor,
)
from eaiv.power.ppk2 import (
    MockPPK2Serial,
    PPK2PowerMonitor,
    PPK2SerialTransport,
    RealPPK2Serial,
)

__all__ = [
    "I2CBus",
    "INA226PowerMonitor",
    "LinuxI2CBus",
    "MockI2CBus",
    "MockPPK2Serial",
    "PPK2PowerMonitor",
    "PPK2SerialTransport",
    "PowerMonitor",
    "PowerTrace",
    "PyFtdiI2CBus",
    "RealPPK2Serial",
    "SimulatedPowerMonitor",
    "build_i2c_bus",
    "build_power_monitor",
]
