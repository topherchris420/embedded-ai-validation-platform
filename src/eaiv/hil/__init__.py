"""Hardware-in-the-loop simulation: virtual sensors, faults, replay.

The HIL layer lets firmware-level validation logic run with no hardware
attached:

- **Streams** (`eaiv.hil.replay`): iterators of ``(t_s, values)`` samples
  sourced from recorded CSV logs or the synthetic dataset generator.
- **Faults** (`eaiv.hil.faults`): composable transformations injected into
  a stream — Gaussian noise, packet loss, timing jitter, sensor outages.
  Fault models are ``fault`` plugins.
- **Simulator** (`eaiv.hil.simulator`): drives a stream through a fault
  chain and collects statistics; ``SimulatedTarget`` is a ``Target``
  plugin ("sim") that emulates a device running the validation firmware.
- **Suite** (`eaiv.hil.suite`): orchestrator-facing experiment measuring
  how much injected faults degrade a fusion algorithm.
"""

from __future__ import annotations

from eaiv.hil.faults import (
    Fault,
    GaussianNoise,
    PacketLoss,
    SensorOutage,
    TimingJitter,
    build_fault,
)
from eaiv.hil.replay import replay_csv, synthetic_imu_stream
from eaiv.hil.simulator import SimulatedTarget, SimulationResult, Simulator
from eaiv.hil.suite import HILExperiment

__all__ = [
    "Fault",
    "GaussianNoise",
    "PacketLoss",
    "SensorOutage",
    "TimingJitter",
    "build_fault",
    "replay_csv",
    "synthetic_imu_stream",
    "Simulator",
    "SimulationResult",
    "SimulatedTarget",
    "HILExperiment",
]
