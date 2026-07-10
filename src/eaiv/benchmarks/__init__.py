"""Host-side benchmark suites beyond inference timing.

- ``memory``: static ROM/RAM footprint analysis of a firmware ELF plus
  model storage cost — no hardware required.

Inference latency/throughput/startup/power live in ``eaiv.tinyml``
(the ``tinyml`` suite); on-device fusion timing comes from the firmware
``bench`` command via ``eaiv.telemetry``.
"""

from __future__ import annotations

from eaiv.benchmarks.memory import MemoryBenchmark

__all__ = ["MemoryBenchmark"]
