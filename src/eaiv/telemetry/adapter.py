"""Telemetry adapters: normalize per-board device output into records.

Boards whose firmware speaks the native eaiv line protocol need nothing —
the default ``eaiv-line`` adapter handles them. Boards with different
output (vendor SDK logging, binary framing, NMEA, ...) register a
``telemetry_adapter`` plugin translating their format into the same typed
records, so dashboards, collectors, and suites stay board-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from eaiv.plugins import get_registry, register_plugin
from eaiv.telemetry.protocol import Record, parse_stream


class TelemetryAdapter(ABC):
    """Translates raw device output chunks into typed records."""

    @abstractmethod
    def feed(self, chunk: str) -> Iterator[Record]:
        """Consume a chunk of raw output, yielding completed records.

        Implementations must buffer partial trailing lines across calls;
        serial reads do not align with line boundaries.
        """
        ...


class LineProtocolAdapter(TelemetryAdapter):
    """Default adapter for the native eaiv line protocol."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> Iterator[Record]:
        self._buffer += chunk
        complete, sep, rest = self._buffer.rpartition("\n")
        self._buffer = rest
        if sep:
            yield from parse_stream(complete)


if get_registry().get("telemetry_adapter", "eaiv-line") is None:
    register_plugin(
        "eaiv-line",
        "telemetry_adapter",
        "Native eaiv serial line protocol",
        version="1.0.0",
        supported_hardware=["*"],
    )(lambda cfg: LineProtocolAdapter())


def build_adapter(name: str = "eaiv-line", config: dict | None = None) -> TelemetryAdapter:
    """Build a telemetry adapter registered under ``name``."""
    adapter = get_registry().create("telemetry_adapter", name, config or {})
    if not isinstance(adapter, TelemetryAdapter):
        raise TypeError(
            f"Plugin 'telemetry_adapter:{name}' did not produce a TelemetryAdapter: "
            f"{type(adapter)!r}"
        )
    return adapter
