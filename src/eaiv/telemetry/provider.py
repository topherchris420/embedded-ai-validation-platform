"""Telemetry providers: one interface over live, replayed, and simulated data.

A provider yields typed protocol records regardless of where they come
from, so collectors, suites, and the dashboard never care whether the
source was a device on a bench, a recorded log, or a synthetic trajectory:

    collector = TelemetryCollector()
    collector.ingest(LiveTelemetryProvider(target, duration_s=5.0))
    collector.ingest(ReplayTelemetryProvider("datasets/imu/imu_run1.csv"))
    collector.ingest(SimulatedTelemetryProvider(duration_s=2.0, seed=1))

Board-specific metrics (temperature, battery, rail voltages) are the
firmware HAL's job: boards extend ``eaiv::board_temperature_c()`` /
the ``status`` command and the extra ``S``-line fields flow through
every provider and consumer unchanged — no per-board host classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from eaiv.plugins.targets import Target
from eaiv.telemetry.adapter import TelemetryAdapter, build_adapter
from eaiv.telemetry.protocol import Record, TelemetryRecord


class TelemetryProvider(ABC):
    """A source of typed telemetry records."""

    @abstractmethod
    def records(self) -> Iterator[Record]:
        """Yield records; finite for replay/simulation, bounded by a
        duration for live capture."""
        ...


class LiveTelemetryProvider(TelemetryProvider):
    """Capture from a live ``Target`` through a telemetry adapter.

    Optionally polls the firmware ``status`` command between reads so
    board health metrics (heap, temperature, ...) land in the stream.
    """

    def __init__(
        self,
        target: Target,
        duration_s: float = 10.0,
        adapter: TelemetryAdapter | None = None,
        poll_status: bool = False,
    ) -> None:
        self.target = target
        self.duration_s = duration_s
        self.adapter = adapter if adapter is not None else build_adapter()
        self.poll_status = poll_status

    def records(self) -> Iterator[Record]:
        raw = self.target.read_serial(self.duration_s)
        yield from self.adapter.feed(raw)
        if self.poll_status:
            status = self.target.run_command("status")
            yield from self.adapter.feed(status + "\n")


class ReplayTelemetryProvider(TelemetryProvider):
    """Replay a recorded CSV log (the platform's dataset schema)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def records(self) -> Iterator[Record]:
        from eaiv.datasets import read_imu_csv

        for row in read_imu_csv(self.path):
            values = dict(row)
            t_s = values.pop("t_s")
            yield TelemetryRecord(t_s=t_s, values=values)


class SimulatedTelemetryProvider(TelemetryProvider):
    """Deterministic synthetic telemetry (seeded IMU trajectory)."""

    def __init__(
        self,
        duration_s: float = 10.0,
        rate_hz: float = 100.0,
        profile: str = "gentle",
        seed: int = 0,
    ) -> None:
        self.duration_s = duration_s
        self.rate_hz = rate_hz
        self.profile = profile
        self.seed = seed

    def records(self) -> Iterator[Record]:
        from eaiv.hil.replay import synthetic_imu_stream

        for t_s, values in synthetic_imu_stream(
            duration_s=self.duration_s,
            rate_hz=self.rate_hz,
            profile=self.profile,
            seed=self.seed,
        ):
            yield TelemetryRecord(t_s=t_s, values=values)
