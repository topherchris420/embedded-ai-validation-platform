"""Collect telemetry from a live target and turn it into artifacts.

``TelemetryCollector`` reads from any ``Target``, runs the output through
a ``TelemetryAdapter``, and accumulates typed records. From there it can
summarize per-field statistics or export a CSV the dashboard (or any
external tool) plots directly.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING

from eaiv.plugins.targets import Target
from eaiv.telemetry.adapter import TelemetryAdapter, build_adapter
from eaiv.telemetry.protocol import (
    BenchRecord,
    BootRecord,
    Record,
    StatRecord,
    TelemetryRecord,
    VerdictRecord,
)

if TYPE_CHECKING:
    from eaiv.telemetry.provider import TelemetryProvider


@dataclass
class TelemetrySummary:
    """Per-field statistics over the collected telemetry samples."""

    samples: int
    duration_s: float
    rate_hz: float
    fields: dict[str, dict[str, float]] = field(default_factory=dict)  # name -> min/max/mean


class TelemetryCollector:
    """Accumulates records from raw chunks or a live target."""

    def __init__(self, adapter: TelemetryAdapter | None = None) -> None:
        self.adapter = adapter if adapter is not None else build_adapter()
        self.records: list[Record] = []

    def feed(self, chunk: str) -> None:
        """Push a chunk of raw device output through the adapter."""
        self.records.extend(self.adapter.feed(chunk))

    def collect(self, target: Target, duration_s: float) -> None:
        """Read serial output from a target for a duration and ingest it."""
        self.feed(target.read_serial(duration_s))

    def ingest(self, provider: "TelemetryProvider") -> None:
        """Consume every record from a telemetry provider (live, replay,
        or simulated — see ``eaiv.telemetry.provider``)."""
        self.records.extend(provider.records())

    # -- typed views -------------------------------------------------------

    @property
    def telemetry(self) -> list[TelemetryRecord]:
        return [r for r in self.records if isinstance(r, TelemetryRecord)]

    @property
    def boots(self) -> list[BootRecord]:
        return [r for r in self.records if isinstance(r, BootRecord)]

    @property
    def benchmarks(self) -> list[BenchRecord]:
        return [r for r in self.records if isinstance(r, BenchRecord)]

    @property
    def stats(self) -> list[StatRecord]:
        return [r for r in self.records if isinstance(r, StatRecord)]

    @property
    def verdict(self) -> VerdictRecord | None:
        """The last verdict seen, if any."""
        for r in reversed(self.records):
            if isinstance(r, VerdictRecord):
                return r
        return None

    # -- artifacts ---------------------------------------------------------

    def summary(self) -> TelemetrySummary:
        samples = self.telemetry
        if not samples:
            return TelemetrySummary(samples=0, duration_s=0.0, rate_hz=0.0)
        duration = samples[-1].t_s - samples[0].t_s
        rate = (len(samples) - 1) / duration if duration > 0 else 0.0

        names = sorted({name for s in samples for name in s.values})
        stats: dict[str, dict[str, float]] = {}
        for name in names:
            series = [s.values[name] for s in samples if name in s.values]
            mean = sum(series) / len(series)
            stats[name] = {
                "min": min(series),
                "max": max(series),
                "mean": mean,
                "std": math.sqrt(sum((x - mean) ** 2 for x in series) / len(series)),
            }
        return TelemetrySummary(
            samples=len(samples),
            duration_s=round(duration, 6),
            rate_hz=round(rate, 3),
            fields=stats,
        )

    def to_csv(self, path: str | Path) -> Path:
        """Write telemetry samples as a CSV with a ``t_s`` column."""
        samples = self.telemetry
        names = sorted({name for s in samples for name in s.values})
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["t_s", *names])
            for s in samples:
                writer.writerow([s.t_s, *[s.values.get(n, "") for n in names]])
        return p
