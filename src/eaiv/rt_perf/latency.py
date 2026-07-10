"""Latency/jitter statistics for periodic task execution traces."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class TaskTrace:
    name: str
    period_ms: float
    deadline_ms: float
    wcet_budget_ms: float
    execution_times_ms: list[float] = field(default_factory=list)
    release_jitter_ms: list[float] = field(default_factory=list)

    def deadline_misses(self) -> int:
        return sum(1 for e in self.execution_times_ms if e > self.deadline_ms)

    def budget_overruns(self) -> int:
        return sum(1 for e in self.execution_times_ms if e > self.wcet_budget_ms)

    def summary(self) -> dict:
        et = self.execution_times_ms
        jit = self.release_jitter_ms
        return {
            "samples": len(et),
            "mean_exec_ms": round(statistics.fmean(et), 4) if et else 0.0,
            "wcet_observed_ms": round(max(et), 4) if et else 0.0,
            "wcet_budget_ms": self.wcet_budget_ms,
            "deadline_ms": self.deadline_ms,
            "deadline_misses": self.deadline_misses(),
            "budget_overruns": self.budget_overruns(),
            "mean_jitter_ms": round(statistics.fmean(jit), 4) if jit else 0.0,
            "max_jitter_ms": round(max(jit), 4) if jit else 0.0,
        }
