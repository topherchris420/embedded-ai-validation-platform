"""Metric identity: unit, direction, and how the number was obtained.

A bare ``{"mean_ms": 4.2}`` is not enough to make a release decision. The
reader also needs to know that milliseconds are lower-is-better, and —
crucially — whether 4.2 came off a physical board, out of a host-side
runtime, out of a static ELF analysis, or out of a simulator. Presenting
a simulated number as a hardware measurement is the single most damaging
thing a validation tool can do, so provenance travels with every metric.

Suites attach explicit metadata via ``SuiteResult.metric_meta``; anything
without explicit metadata falls back to deterministic inference from the
metric name, and is marked as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from eaiv.core.regression import metric_direction


class MetricProvenance(StrEnum):
    """How a metric value came to exist."""

    MEASURED = "measured"
    SIMULATED = "simulated"
    ESTIMATED = "estimated"
    MOCK = "mock"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            MetricProvenance.MEASURED: "Measured",
            MetricProvenance.SIMULATED: "Simulated",
            MetricProvenance.ESTIMATED: "Estimated",
            MetricProvenance.MOCK: "Mock",
            MetricProvenance.UNKNOWN: "Unverified",
        }[self]

    @property
    def is_physical(self) -> bool:
        """True only for values that could have come from real hardware."""
        return self is MetricProvenance.MEASURED

    @property
    def caveat(self) -> str:
        return {
            MetricProvenance.MEASURED: "",
            MetricProvenance.SIMULATED: "Produced by a software simulation, not hardware.",
            MetricProvenance.ESTIMATED: "Derived from a model or heuristic, not a direct reading.",
            MetricProvenance.MOCK: "Produced by a stand-in runtime; not a real workload.",
            MetricProvenance.UNKNOWN: "Origin not recorded by the suite that produced it.",
        }[self]


class MetricSource(StrEnum):
    """Where the measurement was taken."""

    DEVICE = "device"
    HOST = "host"
    SIMULATOR = "simulator"
    STATIC_ANALYSIS = "static-analysis"
    DATASET = "dataset"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            MetricSource.DEVICE: "on target hardware",
            MetricSource.HOST: "on the host machine",
            MetricSource.SIMULATOR: "in the simulator",
            MetricSource.STATIC_ANALYSIS: "by static analysis",
            MetricSource.DATASET: "from a recorded dataset",
            MetricSource.UNKNOWN: "",
        }[self]


@dataclass(frozen=True)
class MetricInfo:
    """Everything needed to render and reason about one metric."""

    name: str
    unit: str = ""
    direction: int = 0  # +1 higher-is-better, -1 lower-is-better, 0 informational
    provenance: MetricProvenance = MetricProvenance.UNKNOWN
    source: MetricSource = MetricSource.UNKNOWN
    description: str = ""
    inferred: bool = False

    @property
    def direction_label(self) -> str:
        return {1: "higher is better", -1: "lower is better", 0: "informational"}[self.direction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "direction": self.direction,
            "provenance": str(self.provenance),
            "source": str(self.source),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, name: str, payload: dict[str, Any]) -> MetricInfo:
        try:
            provenance = MetricProvenance(str(payload.get("provenance", "unknown")))
        except ValueError:
            provenance = MetricProvenance.UNKNOWN
        try:
            source = MetricSource(str(payload.get("source", "unknown")))
        except ValueError:
            source = MetricSource.UNKNOWN
        try:
            direction = int(payload.get("direction", 0))
        except (TypeError, ValueError):
            direction = 0
        return cls(
            name=name,
            unit=str(payload.get("unit", "")),
            direction=direction,
            provenance=provenance,
            source=source,
            description=str(payload.get("description", "")),
            inferred=False,
        )


# Suffix/substring -> unit. Ordered: the first match wins, so longer and
# more specific keys come first.
_UNIT_RULES: tuple[tuple[str, str], ...] = (
    ("_ms", "ms"),
    ("_us", "µs"),
    ("_mj", "mJ"),
    ("_mw", "mW"),
    ("_hz", "Hz"),
    ("_kb", "KB"),
    ("_bytes", "bytes"),
    ("_deg_per_min", "°/min"),
    ("_deg", "°"),
    ("_pct", "%"),
    ("_s", "s"),
    ("rate", "ratio"),
    ("fps", "fps"),
    ("throughput_ips", "inferences/s"),
    ("macs", "MACs"),
    ("samples", "count"),
    ("misses", "count"),
    ("overruns", "count"),
    ("attempts", "count"),
    ("count", "count"),
)

_DESCRIPTIONS: dict[str, str] = {
    "mean_ms": "Average inference latency. Drives sustained throughput.",
    "p50_ms": "Median inference latency — the typical case.",
    "p95_ms": "95th-percentile latency; one request in twenty is slower.",
    "p99_ms": "Tail latency. Real-time deadlines are missed here first.",
    "max_ms": "Slowest observed inference — the worst case a deadline must absorb.",
    "startup_ms": "Cold model load through first inference; dominates wake-from-sleep duty cycles.",
    "fps": "Inferences per second derived from mean latency.",
    "throughput_ips": "Inferences per second derived from mean latency.",
    "confidence_stability": (
        "Max per-element output spread across repeated runs on one fixed input. "
        "Non-zero means the model is not numerically reproducible."
    ),
    "rom_kb": "Static code + read-only data footprint in flash.",
    "ram_static_kb": "Statically allocated RAM (.data + .bss) before the heap is touched.",
    "model_flash_kb": "Flash consumed by the model file itself.",
    "tensor_arena_est_kb": "Lower bound on TFLite tensor memory; a real arena is larger.",
    "estimated_macs": "Crude multiply-accumulate estimate, not a layer-accurate profile.",
    "roll_rmse_deg": "Roll error against ground truth across the replayed dataset.",
    "pitch_rmse_deg": "Pitch error against ground truth across the replayed dataset.",
    "faulted_rmse_deg": "Orientation error with the fault chain injected.",
    "clean_rmse_deg": "Orientation error on the unmodified stream — the reference for degradation.",
    "degradation_deg": "Extra orientation error caused by the injected faults.",
    "drop_rate": "Fraction of samples the fault chain discarded.",
    "deadline_misses": "Executions that exceeded the task deadline. Any non-zero value is a defect.",
    "budget_overruns": "Executions that exceeded the WCET budget but still met the deadline.",
    "wcet_observed_ms": "Longest observed execution time for the task.",
    "max_jitter_ms": "Worst release jitter observed for the task.",
    "mean_power_mw": "Average supply power over the measurement window.",
    "peak_power_mw": "Highest instantaneous power over the measurement window.",
    "energy_per_inference_mj": "Energy cost of one inference; sets battery life.",
}


def infer_unit(metric: str) -> str:
    """Unit implied by a metric name, or ``""`` when nothing matches."""
    lowered = metric.lower()
    for token, unit in _UNIT_RULES:
        if lowered.endswith(token) or token in lowered:
            return unit
    return ""


def infer_metric_info(metric: str) -> MetricInfo:
    """Deterministic metadata for a metric with no explicit declaration."""
    return MetricInfo(
        name=metric,
        unit=infer_unit(metric),
        direction=metric_direction(metric),
        provenance=MetricProvenance.UNKNOWN,
        source=MetricSource.UNKNOWN,
        description=_DESCRIPTIONS.get(metric, ""),
        inferred=True,
    )


def metric_meta(
    metrics: dict[str, Any],
    provenance: MetricProvenance,
    source: MetricSource,
    overrides: dict[str, tuple[MetricProvenance, MetricSource]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a ``SuiteResult.metric_meta`` payload for a metric dict.

    ``overrides`` marks individual metrics whose origin differs from the
    suite default — an estimated MAC count inside an otherwise measured
    benchmark, for instance.
    """
    overrides = overrides or {}
    out: dict[str, dict[str, Any]] = {}
    for name, value in metrics.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        item_prov, item_source = overrides.get(name, (provenance, source))
        inferred = infer_metric_info(name)
        out[name] = MetricInfo(
            name=name,
            unit=inferred.unit,
            direction=inferred.direction,
            provenance=item_prov,
            source=item_source,
            description=inferred.description,
        ).to_dict()
    return out


#: Target kinds that execute firmware in software. Metrics gathered
#: through them are simulation output, never hardware measurements —
#: QEMU included, since an emulator models timing rather than exhibiting it.
SIMULATED_TARGET_KINDS = frozenset({"sim", "qemu", "mock"})


def target_provenance(target_spec: dict[str, Any] | None) -> tuple[MetricProvenance, MetricSource]:
    """Classify metrics obtained through a target by the target's nature."""
    kind = str((target_spec or {}).get("kind", "")).strip().lower()
    if not kind:
        return MetricProvenance.UNKNOWN, MetricSource.UNKNOWN
    if kind in SIMULATED_TARGET_KINDS:
        return MetricProvenance.SIMULATED, MetricSource.SIMULATOR
    return MetricProvenance.MEASURED, MetricSource.DEVICE


def dataset_provenance(path: str | Path) -> tuple[MetricProvenance, MetricSource]:
    """Classify metrics computed over a replay dataset.

    A dataset whose sidecar records generator parameters is synthetic, so
    scores derived from it are simulation results however real the maths
    is; a recorded capture yields measured values.
    """
    if not path:
        return MetricProvenance.UNKNOWN, MetricSource.UNKNOWN
    try:
        from eaiv.datasets import read_metadata

        meta = read_metadata(path)
    except Exception:  # noqa: BLE001 - a missing/broken sidecar is not fatal
        return MetricProvenance.UNKNOWN, MetricSource.DATASET
    if meta is not None and meta.generator:
        return MetricProvenance.SIMULATED, MetricSource.DATASET
    return MetricProvenance.MEASURED, MetricSource.DATASET


def format_value(value: Any, info: MetricInfo | None = None) -> str:
    """Consistent metric rendering: fixed precision plus unit."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        magnitude = abs(float(value))
        if isinstance(value, int) or float(value).is_integer():
            text = f"{int(value):,}"
        elif magnitude >= 100:
            text = f"{value:,.1f}"
        elif magnitude >= 1:
            text = f"{value:,.3f}"
        elif magnitude > 0:
            text = f"{value:.5g}"
        else:
            text = "0"
        unit = info.unit if info else ""
        return f"{text} {unit}".strip()
    return str(value)


__all__ = [
    "MetricInfo",
    "MetricProvenance",
    "MetricSource",
    "format_value",
    "infer_metric_info",
    "infer_unit",
    "metric_meta",
]
