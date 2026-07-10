"""Power measurement interfaces.

``PowerMonitor`` is the plugin interface for power-measurement hardware
(INA226, Nordic PPK2, Joulescope, ...). A deterministic
``SimulatedPowerMonitor`` ships as the ``sim`` plugin so power-aware
benchmarks run — and are testable — without instrumentation attached;
real drivers register under the same ``power_monitor`` plugin type.

Usage:

    monitor = build_power_monitor({"kind": "sim", "active_mw": 180.0})
    monitor.start()
    ...workload...
    trace = monitor.stop()
    trace.mean_mw, trace.energy_mj
"""

from __future__ import annotations

from eaiv.power.monitor import (
    PowerMonitor,
    PowerTrace,
    SimulatedPowerMonitor,
    build_power_monitor,
)

__all__ = [
    "PowerMonitor",
    "PowerTrace",
    "SimulatedPowerMonitor",
    "build_power_monitor",
]
