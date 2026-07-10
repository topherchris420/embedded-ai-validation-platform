"""TinyML metrics: latency distribution, throughput, RAM/ROM, MACs."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class LatencyStats:
    samples: list[float] = field(default_factory=list)  # seconds

    def add(self, seconds: float) -> None:
        self.samples.append(seconds)

    @property
    def count(self) -> int:
        return len(self.samples)

    def mean_ms(self) -> float:
        return statistics.fmean(self.samples) * 1000 if self.samples else 0.0

    def median_ms(self) -> float:
        return statistics.median(self.samples) * 1000 if self.samples else 0.0

    def stdev_ms(self) -> float:
        return (statistics.pstdev(self.samples) * 1000) if len(self.samples) > 1 else 0.0

    def percentile_ms(self, pct: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        k = min(len(ordered) - 1, max(0, int(round(pct / 100 * (len(ordered) - 1)))))
        return ordered[k] * 1000

    def min_ms(self) -> float:
        return min(self.samples) * 1000 if self.samples else 0.0

    def max_ms(self) -> float:
        return max(self.samples) * 1000 if self.samples else 0.0

    def throughput_ips(self) -> float:
        """Inferences per second, from mean latency."""
        mean_s = statistics.fmean(self.samples) if self.samples else 0.0
        return (1.0 / mean_s) if mean_s > 0 else 0.0

    def summary(self) -> dict:
        return {
            "count": self.count,
            "mean_ms": round(self.mean_ms(), 3),
            "median_ms": round(self.median_ms(), 3),
            "stdev_ms": round(self.stdev_ms(), 3),
            "p90_ms": round(self.percentile_ms(90), 3),
            "p99_ms": round(self.percentile_ms(99), 3),
            "min_ms": round(self.min_ms(), 3),
            "max_ms": round(self.max_ms(), 3),
            "throughput_ips": round(self.throughput_ips(), 2),
        }


def estimate_macs(input_shape: tuple, output_shape: tuple) -> int:
    """Very rough MAC estimate for reporting purposes when a proper
    per-layer profiler isn't wired up for the given runtime. Treats the
    model as a single dense layer between flattened input/output — a
    deliberately crude lower bound, not a substitute for a real profiler."""
    import math

    in_elems = math.prod(d for d in input_shape if d and d > 0) or 1
    out_elems = math.prod(d for d in output_shape if d and d > 0) or 1
    return int(in_elems * out_elems)
