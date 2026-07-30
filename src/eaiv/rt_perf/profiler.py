"""Worst-case execution time / jitter / deadline-miss profiler.

If the target exposes a command channel (`run_command`) that echoes
per-task timing lines (e.g. "TASK control_loop exec_us=812 jitter_us=40"),
this profiler parses that stream. When no target/command channel is
available (e.g. `rt` suite run standalone against a stub), it falls back
to a synthetic trace generator so the suite remains runnable for CI smoke
tests and local development without hardware attached.
"""

from __future__ import annotations

import logging
import random
import re

from eaiv.core.metrics import MetricProvenance, MetricSource, metric_meta, target_provenance
from eaiv.core.results import SuiteResult
from eaiv.rt_perf.latency import TaskTrace
from eaiv.targets.base import Target

log = logging.getLogger("eaiv.rt_perf")

_LINE_RE = re.compile(
    r"TASK\s+(?P<name>\S+)\s+exec_us=(?P<exec_us>\d+)\s+jitter_us=(?P<jitter_us>\d+)"
)


class RTProfiler:
    def __init__(self, spec: dict, target: Target) -> None:
        self.spec = spec
        self.target = target
        #: Set by :meth:`_collect`: True when no device trace was obtained
        #: and the synthetic generator produced the numbers instead.
        self.synthetic = False

    def run(self) -> SuiteResult:
        task_set = self.spec.get("task_set", [])
        duration_s = float(self.spec.get("duration_s", 60))

        traces = {
            t["name"]: TaskTrace(
                name=t["name"],
                period_ms=float(t["period_ms"]),
                deadline_ms=float(t["deadline_ms"]),
                wcet_budget_ms=float(t["wcet_budget_ms"]),
            )
            for t in task_set
        }

        if not traces:
            return SuiteResult(name="rt_perf", passed=False, metrics={}, notes="empty task_set")

        raw = self._collect(duration_s)
        for line in raw.splitlines():
            m = _LINE_RE.search(line)
            if not m:
                continue
            name = m.group("name")
            if name not in traces:
                continue
            traces[name].execution_times_ms.append(int(m.group("exec_us")) / 1000.0)
            traces[name].release_jitter_ms.append(int(m.group("jitter_us")) / 1000.0)

        metrics: dict = {name: t.summary() for name, t in traces.items()}
        # Nested per-task summaries stay exactly as they were for existing
        # consumers; flattened "<task>.<metric>" copies are added so the
        # regression gate, the insight engine, and metric charts — all of
        # which walk flat numeric metrics — can actually see deadline
        # misses and WCET.
        for name, trace in traces.items():
            for key, value in trace.summary().items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics[f"{name}.{key}"] = value
        passed = all(
            t.deadline_misses() == 0 and t.summary()["samples"] > 0 for t in traces.values()
        )

        if self.synthetic:
            provenance, source = MetricProvenance.SIMULATED, MetricSource.SIMULATOR
            origin_note = " from a synthetic trace (no device timing available)"
        else:
            provenance, source = target_provenance(getattr(self.target, "spec", {}) or {})
            origin_note = " from device task telemetry"

        return SuiteResult(
            name="rt_perf",
            passed=passed,
            metrics=metrics,
            notes=f"profiled {len(traces)} task(s) over {duration_s:.0f}s{origin_note}",
            metric_meta=metric_meta(metrics, provenance, source),
        )

    def _collect(self, duration_s: float) -> str:
        self.synthetic = False
        if self.target is not None:
            try:
                self.target.run_command("RT_PROFILE_START")
                output = self.target.read_serial(duration_s)
                self.target.run_command("RT_PROFILE_STOP")
                if output.strip():
                    return output
            except Exception:
                log.debug("device RT trace unavailable; using synthetic trace", exc_info=True)
        self.synthetic = True
        return self._synthetic_trace(duration_s)

    def _synthetic_trace(self, duration_s: float) -> str:
        """Generate a plausible-looking trace so the suite is runnable
        without hardware. Clearly not a substitute for real profiling —
        intended for CI smoke tests and local development only."""
        rng = random.Random(0)
        lines = []
        for name, period_ms, wcet_budget_ms in self._task_shape():
            n = max(1, int(duration_s * 1000 / period_ms))
            for _ in range(n):
                exec_us = int(rng.gauss(wcet_budget_ms * 0.6, wcet_budget_ms * 0.1) * 1000)
                jitter_us = int(abs(rng.gauss(0, period_ms * 0.02)) * 1000)
                lines.append(f"TASK {name} exec_us={max(0, exec_us)} jitter_us={max(0, jitter_us)}")
        return "\n".join(lines)

    def _task_shape(self) -> list[tuple[str, float, float]]:
        return [
            (t["name"], float(t["period_ms"]), float(t["wcet_budget_ms"]))
            for t in self.spec.get("task_set", [])
        ]
