"""Telemetry signal analysis behind the Telemetry Lab.

Plotting a CSV is easy; knowing whether the capture is trustworthy is the
part that matters. These functions answer the questions an engineer asks
of a sensor log before drawing conclusions from it: is the sample rate
what it claims to be, are samples missing, are there outliers, and — when
ground truth is present — how far off was the estimate.

Pure Python and stdlib maths only: no pandas, no Streamlit, fully
testable.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

#: Consecutive-sample interval this far above the median counts as a gap.
GAP_FACTOR = 1.8

#: Modified-Z-score threshold for flagging an outlier sample.
OUTLIER_Z = 3.5

#: Signal-name prefixes grouped together on one axis.
SIGNAL_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Gyroscope", "rad/s", ("gx", "gy", "gz")),
    ("Accelerometer", "g", ("ax", "ay", "az")),
    ("Magnetometer", "µT", ("mx", "my", "mz")),
    ("Orientation", "deg", ("roll", "pitch", "yaw")),
    ("Ground truth", "deg", ("roll_ref_deg", "pitch_ref_deg", "yaw_ref_deg")),
)


def group_signals(columns: Sequence[str]) -> dict[str, list[str]]:
    """Bucket column names into physically meaningful groups.

    Anything unrecognised lands in "Other" rather than being dropped —
    a plugin's custom telemetry field must still be plottable.
    """
    remaining = [c for c in columns if c != "t_s"]
    grouped: dict[str, list[str]] = {}
    for title, unit, names in SIGNAL_GROUPS:
        members = [c for c in remaining if c in names or c.startswith(tuple(names))]
        if members:
            grouped[f"{title} ({unit})"] = members
            remaining = [c for c in remaining if c not in members]
    if remaining:
        grouped["Other"] = remaining
    return grouped


@dataclass
class SamplingReport:
    """Timing health of a capture."""

    samples: int
    duration_s: float
    mean_rate_hz: float
    median_interval_s: float
    jitter_s: float
    gaps: list[tuple[float, float]] = field(default_factory=list)
    non_monotonic: int = 0
    declared_rate_hz: float | None = None

    @property
    def missing_estimate(self) -> int:
        """How many samples the gaps most likely swallowed."""
        if self.median_interval_s <= 0:
            return 0
        return sum(max(0, round(length / self.median_interval_s) - 1) for _, length in self.gaps)

    @property
    def rate_matches_declaration(self) -> bool | None:
        if self.declared_rate_hz is None or self.declared_rate_hz <= 0:
            return None
        return abs(self.mean_rate_hz - self.declared_rate_hz) / self.declared_rate_hz <= 0.05

    @property
    def issues(self) -> list[str]:
        out: list[str] = []
        if self.non_monotonic:
            out.append(f"{self.non_monotonic} timestamp(s) go backwards")
        if self.gaps:
            out.append(
                f"{len(self.gaps)} gap(s) in the timeline, ~{self.missing_estimate} sample(s) missing"
            )
        if self.rate_matches_declaration is False:
            out.append(
                f"observed {self.mean_rate_hz:.2f} Hz against a declared "
                f"{self.declared_rate_hz:.2f} Hz"
            )
        return out


def analyze_sampling(
    times: Sequence[float], declared_rate_hz: float | None = None
) -> SamplingReport:
    """Rate, jitter, gaps, and ordering problems in a timestamp column."""
    values = [float(t) for t in times]
    if len(values) < 2:
        return SamplingReport(
            samples=len(values),
            duration_s=0.0,
            mean_rate_hz=0.0,
            median_interval_s=0.0,
            jitter_s=0.0,
            declared_rate_hz=declared_rate_hz,
        )
    intervals = [b - a for a, b in pairwise(values)]
    positive = [d for d in intervals if d > 0]
    median = statistics.median(positive) if positive else 0.0
    duration = values[-1] - values[0]
    gaps = [
        (values[i], intervals[i])
        for i in range(len(intervals))
        if median > 0 and intervals[i] > median * GAP_FACTOR
    ]
    return SamplingReport(
        samples=len(values),
        duration_s=duration,
        mean_rate_hz=(len(values) - 1) / duration if duration > 0 else 0.0,
        median_interval_s=median,
        jitter_s=statistics.pstdev(positive) if len(positive) > 1 else 0.0,
        gaps=gaps,
        non_monotonic=sum(1 for d in intervals if d <= 0),
        declared_rate_hz=declared_rate_hz,
    )


@dataclass
class SignalStats:
    """Descriptive statistics plus outliers for one channel."""

    name: str
    count: int
    minimum: float
    maximum: float
    mean: float
    stdev: float
    median: float
    outlier_indices: list[int] = field(default_factory=list)

    @property
    def outliers(self) -> int:
        return len(self.outlier_indices)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.name,
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "std": self.stdev,
            "median": self.median,
            "outliers": self.outliers,
        }


def analyze_signal(name: str, values: Sequence[float]) -> SignalStats:
    """Statistics for one channel, with modified-Z-score outlier detection.

    The modified Z score uses the median and the median absolute
    deviation, so a handful of extreme samples cannot hide themselves by
    inflating the mean and standard deviation they are measured against.

    When the MAD is zero — a mostly-constant signal, which is exactly the
    case where a single spike matters most — the score falls back to the
    mean absolute deviation. Without that fallback a lone glitch in a
    stationary channel would go unreported.
    """
    numbers = [float(v) for v in values if v is not None and not _is_nan(v)]
    if not numbers:
        return SignalStats(name, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    median = statistics.median(numbers)
    deviations = [abs(v - median) for v in numbers]
    mad = statistics.median(deviations)
    outliers: list[int] = []
    if mad > 0:
        outliers = [
            index
            for index, value in enumerate(numbers)
            if abs(0.6745 * (value - median) / mad) > OUTLIER_Z
        ]
    else:
        mean_ad = statistics.fmean(deviations)
        if mean_ad > 0:
            outliers = [
                index
                for index, value in enumerate(numbers)
                if abs(0.7979 * (value - median) / mean_ad) > OUTLIER_Z
            ]
    return SignalStats(
        name=name,
        count=len(numbers),
        minimum=min(numbers),
        maximum=max(numbers),
        mean=statistics.fmean(numbers),
        stdev=statistics.pstdev(numbers) if len(numbers) > 1 else 0.0,
        median=median,
        outlier_indices=outliers,
    )


def _is_nan(value: Any) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


@dataclass
class OrientationError:
    """Estimated-versus-truth comparison for one orientation axis."""

    axis: str
    rmse_deg: float
    max_error_deg: float
    mean_error_deg: float
    drift_deg_per_min: float
    samples: int


def orientation_error(
    times: Sequence[float],
    estimated: Sequence[float],
    reference: Sequence[float],
    axis: str = "roll",
) -> OrientationError | None:
    """RMSE, bias, and drift of an estimate against ground truth.

    Drift is the least-squares slope of the error over time, expressed per
    minute — the quantity that tells you whether an estimate is merely
    noisy or is walking away.
    """
    n = min(len(times), len(estimated), len(reference))
    if n < 2:
        return None
    errors = [float(estimated[i]) - float(reference[i]) for i in range(n)]
    t = [float(times[i]) for i in range(n)]
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    mean_t = statistics.fmean(t)
    mean_e = statistics.fmean(errors)
    denominator = sum((x - mean_t) ** 2 for x in t)
    slope = (
        sum((t[i] - mean_t) * (errors[i] - mean_e) for i in range(n)) / denominator
        if denominator > 0
        else 0.0
    )
    return OrientationError(
        axis=axis,
        rmse_deg=rmse,
        max_error_deg=max(abs(e) for e in errors),
        mean_error_deg=mean_e,
        drift_deg_per_min=slope * 60.0,
        samples=n,
    )


def reference_pairs(columns: Sequence[str]) -> list[tuple[str, str, str]]:
    """(axis, estimated column, reference column) triples present in a capture."""
    out: list[tuple[str, str, str]] = []
    for axis in ("roll", "pitch", "yaw"):
        reference = f"{axis}_ref_deg"
        if reference not in columns:
            continue
        for candidate in (axis, f"{axis}_deg", f"{axis}_est_deg"):
            if candidate in columns:
                out.append((axis, candidate, reference))
                break
    return out


__all__ = [
    "GAP_FACTOR",
    "OUTLIER_Z",
    "SIGNAL_GROUPS",
    "OrientationError",
    "SamplingReport",
    "SignalStats",
    "analyze_sampling",
    "analyze_signal",
    "group_signals",
    "orientation_error",
    "reference_pairs",
]
