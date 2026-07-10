"""The eaiv serial line protocol: typed records and a tolerant parser.

Protocol lines (emitted by ``firmware/src/main.cpp`` and mirrored by
``eaiv.hil.SimulatedTarget``):

    BOOT eaiv-fw board=esp32 cpu_hz=240000000 heap=294976
    T t=0.0100 gx=0.18850 gy=0.01406 ... roll=0.135 pitch=0.021
    B iters=1000 us_per_update=3.412 max_us=18
    ALL_TESTS_OK
    FAIL self-test-clock

The parser is tolerant: unknown lines yield ``None`` rather than raising,
because real serial links interleave garbage, partial lines, and vendor
boot ROM output with protocol traffic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Union


@dataclass(frozen=True)
class BootRecord:
    """Device (re)boot banner."""

    firmware: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def board(self) -> str:
        return self.fields.get("board", "unknown")


@dataclass(frozen=True)
class TelemetryRecord:
    """One periodic telemetry sample (``T`` line)."""

    t_s: float
    values: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchRecord:
    """On-device benchmark result (``B`` line)."""

    values: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class VerdictRecord:
    """Terminal self-test verdict."""

    passed: bool
    reason: str = ""


Record = Union[BootRecord, TelemetryRecord, BenchRecord, VerdictRecord]


def _parse_kv(tokens: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, _, v = tok.partition("=")
            out[k] = v
    return out


def _to_floats(raw: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[k] = float(v)
        except ValueError:
            continue
    return out


def parse_line(line: str) -> Record | None:
    """Parse one protocol line; returns None for non-protocol content."""
    line = line.strip()
    if not line:
        return None
    tokens = line.split()
    head = tokens[0]

    if head == "BOOT" and len(tokens) >= 2:
        return BootRecord(firmware=tokens[1], fields=_parse_kv(tokens[2:]))
    if head == "T":
        values = _to_floats(_parse_kv(tokens[1:]))
        t_s = values.pop("t", None)
        if t_s is None:
            return None
        return TelemetryRecord(t_s=t_s, values=values)
    if head == "B":
        return BenchRecord(values=_to_floats(_parse_kv(tokens[1:])))
    if head == "ALL_TESTS_OK":
        return VerdictRecord(passed=True)
    if head == "FAIL":
        return VerdictRecord(passed=False, reason=" ".join(tokens[1:]))
    return None


def parse_stream(text: str) -> Iterator[Record]:
    """Parse a chunk of serial output, skipping non-protocol lines."""
    for line in text.splitlines():
        record = parse_line(line)
        if record is not None:
            yield record
