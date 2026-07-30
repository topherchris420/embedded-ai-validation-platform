"""Host-side telemetry pipeline for device output.

The firmware (and the HIL ``SimulatedTarget``) emit a line protocol over
serial; this package turns that raw text into typed records, through
pluggable per-board adapters, and into artifacts the dashboard and
benchmark suites consume:

- ``protocol``: record dataclasses + parser for the native eaiv protocol
- ``adapter``: ``telemetry_adapter`` plugin type; boards with non-native
  output register an adapter instead of changing the platform
- ``collector``: pulls from a live ``Target``, accumulates records,
  computes summaries, exports CSV
"""

from __future__ import annotations

from eaiv.telemetry.adapter import TelemetryAdapter, build_adapter
from eaiv.telemetry.collector import TelemetryCollector, TelemetrySummary
from eaiv.telemetry.protocol import (
    BenchRecord,
    BootRecord,
    Record,
    StatRecord,
    TelemetryRecord,
    VerdictRecord,
    parse_line,
    parse_stream,
)
from eaiv.telemetry.provider import (
    LiveTelemetryProvider,
    ReplayTelemetryProvider,
    SimulatedTelemetryProvider,
    TelemetryProvider,
)

__all__ = [
    "BenchRecord",
    "BootRecord",
    "LiveTelemetryProvider",
    "Record",
    "ReplayTelemetryProvider",
    "SimulatedTelemetryProvider",
    "StatRecord",
    "TelemetryAdapter",
    "TelemetryCollector",
    "TelemetryProvider",
    "TelemetryRecord",
    "TelemetrySummary",
    "VerdictRecord",
    "build_adapter",
    "parse_line",
    "parse_stream",
]
