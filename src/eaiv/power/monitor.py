"""Power monitor plugin interface and the simulated reference monitor."""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from eaiv.plugins import get_registry, register_plugin


@dataclass
class PowerTrace:
    """Result of one measurement window."""

    duration_s: float
    samples_mw: list[float] = field(default_factory=list)

    @property
    def mean_mw(self) -> float:
        return sum(self.samples_mw) / len(self.samples_mw) if self.samples_mw else 0.0

    @property
    def peak_mw(self) -> float:
        return max(self.samples_mw) if self.samples_mw else 0.0

    @property
    def energy_mj(self) -> float:
        """Energy over the window in millijoules (mW x s)."""
        return self.mean_mw * self.duration_s


class PowerMonitor(ABC):
    """Measurement window over a supply rail.

    Implementations wrap real instruments (INA226 over I2C, PPK2 over
    USB, ...). ``start()``/``stop()`` bracket the workload; ``stop()``
    returns the trace for the elapsed window.
    """

    @abstractmethod
    def start(self) -> None:
        """Begin capturing."""
        ...

    @abstractmethod
    def stop(self) -> PowerTrace:
        """End capturing and return the trace since ``start()``."""
        ...


class SimulatedPowerMonitor(PowerMonitor):
    """Deterministic synthetic monitor: seeded noise around a set-point.

    Models a device drawing ``idle_mw`` at rest and ``active_mw`` under
    load; the measurement window is assumed active. Real wall-clock time
    is used for the window duration, so energy figures scale with the
    actual workload length.
    """

    def __init__(
        self,
        active_mw: float = 150.0,
        idle_mw: float = 20.0,
        noise_mw: float = 5.0,
        sample_rate_hz: float = 1000.0,
        seed: int = 0,
    ) -> None:
        self.active_mw = active_mw
        self.idle_mw = idle_mw
        self.noise_mw = noise_mw
        self.sample_rate_hz = sample_rate_hz
        self._rng = random.Random(seed)
        self._t0: float | None = None

    def start(self) -> None:
        self._t0 = time.perf_counter()

    def stop(self) -> PowerTrace:
        if self._t0 is None:
            raise RuntimeError("stop() called before start()")
        duration = time.perf_counter() - self._t0
        self._t0 = None
        n = max(1, int(duration * self.sample_rate_hz))
        samples = [self.active_mw + self._rng.gauss(0.0, self.noise_mw) for _ in range(n)]
        return PowerTrace(duration_s=duration, samples_mw=samples)


if get_registry().get("power_monitor", "sim") is None:
    register_plugin(
        "sim",
        "power_monitor",
        "Deterministic simulated power monitor (no instrumentation required)",
        version="1.0.0",
        supported_hardware=["*"],
    )(lambda cfg: SimulatedPowerMonitor(**cfg))


def build_power_monitor(spec: dict) -> PowerMonitor:
    """Build a power monitor from ``{"kind": "sim", ...constructor args}``."""
    spec = dict(spec)
    kind = spec.pop("kind", "sim")
    monitor = get_registry().create("power_monitor", kind, spec)
    if not isinstance(monitor, PowerMonitor):
        raise TypeError(
            f"Plugin 'power_monitor:{kind}' did not produce a PowerMonitor: {type(monitor)!r}"
        )
    return monitor
