"""Regression detection between two validation report JSON artifacts.

The reporter writes ``reports/latest.json`` on every run; CI keeps the
last known-good file as a baseline and gates merges with::

    eaiv compare baseline.json reports/latest.json --max-regression-pct 10

A metric "regresses" when it moves in its bad direction by more than the
threshold percentage. Direction is inferred from the metric name (latency,
error, memory and drop metrics are lower-is-better; throughput metrics are
higher-is-better); unrecognized metrics are reported but never gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_LOWER_IS_BETTER_HINTS = (
    "_ms",
    "_s",
    "rmse",
    "drift",
    "latency",
    "jitter",
    "_bytes",
    "_kb",
    "ram",
    "flash",
    "rom",
    "macs",
    "drop_rate",
    "dropped",
    "degradation",
    "power",
    "_mw",
    "misses",
)
_HIGHER_IS_BETTER_HINTS = ("fps", "throughput", "samples_out", "accuracy", "score")


def metric_direction(name: str) -> int:
    """+1 if higher is better, -1 if lower is better, 0 if unknown."""
    lowered = name.lower()
    if any(h in lowered for h in _HIGHER_IS_BETTER_HINTS):
        return 1
    if any(h in lowered for h in _LOWER_IS_BETTER_HINTS):
        return -1
    return 0


@dataclass
class MetricDelta:
    suite: str
    metric: str
    baseline: float
    current: float
    change_pct: float
    direction: int  # +1 higher-is-better, -1 lower-is-better, 0 informational
    regressed: bool


@dataclass
class RegressionReport:
    deltas: list[MetricDelta] = field(default_factory=list)

    @property
    def regressions(self) -> list[MetricDelta]:
        return [d for d in self.deltas if d.regressed]

    @property
    def passed(self) -> bool:
        return not self.regressions

    def counts(self, epsilon_pct: float = 1.0) -> dict[str, int]:
        """Answer "is this release better or worse?": per-metric verdicts.

        improved: moved in the good direction by more than epsilon;
        regressed: beyond the gate threshold (as flagged at compare time);
        unchanged: within epsilon or below the gate; informational:
        direction unknown, never gates.
        """
        out = {"improved": 0, "regressed": 0, "unchanged": 0, "informational": 0}
        for d in self.deltas:
            if d.direction == 0:
                out["informational"] += 1
            elif d.regressed:
                out["regressed"] += 1
            elif (d.direction > 0 and d.change_pct > epsilon_pct) or (
                d.direction < 0 and d.change_pct < -epsilon_pct
            ):
                out["improved"] += 1
            else:
                out["unchanged"] += 1
        return out


#: Metric provenances whose values describe a stand-in rather than the
#: system under test. Comparing them across runs measures the stand-in, so
#: they are reported but never allowed to gate a release.
NON_GATING_PROVENANCE = frozenset({"mock"})


def _declared_provenance(suite_payload: dict, metric: str) -> str:
    """Provenance a suite declared for one metric, or ``""``."""
    declared = suite_payload.get("metric_meta")
    if not isinstance(declared, dict):
        return ""
    entry = declared.get(metric)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("provenance", ""))


def compare_reports(
    baseline: dict,
    current: dict,
    max_regression_pct: float = 10.0,
    gate_non_measured: bool = False,
) -> RegressionReport:
    """Compare every shared numeric metric between two report payloads.

    Metrics a suite labelled ``mock`` are downgraded to informational: a
    stand-in runtime's timings vary by orders of magnitude between runs and
    say nothing about the code under review, so gating on them produces
    noise instead of signal. Pass ``gate_non_measured=True`` to compare
    them anyway. Metrics without declared provenance — every legacy report
    — are unaffected and still gate as before.
    """
    base_suites = {s["name"]: s.get("metrics", {}) for s in baseline.get("suites", [])}
    curr_suites = {s["name"]: s.get("metrics", {}) for s in current.get("suites", [])}
    curr_payloads = {s["name"]: s for s in current.get("suites", []) if isinstance(s, dict)}

    report = RegressionReport()
    for suite_name in sorted(set(base_suites) & set(curr_suites)):
        base_metrics = base_suites[suite_name]
        curr_metrics = curr_suites[suite_name]
        suite_payload = curr_payloads.get(suite_name, {})
        for metric in sorted(set(base_metrics) & set(curr_metrics)):
            b, c = base_metrics[metric], curr_metrics[metric]
            if isinstance(b, bool) or isinstance(c, bool):
                continue
            if not isinstance(b, (int, float)) or not isinstance(c, (int, float)):
                continue
            change_pct = ((c - b) / abs(b) * 100.0) if b != 0 else (0.0 if c == 0 else float("inf"))
            direction = metric_direction(metric)
            if not gate_non_measured and (
                _declared_provenance(suite_payload, metric) in NON_GATING_PROVENANCE
            ):
                direction = 0
            if direction > 0:
                regressed = change_pct < -max_regression_pct
            elif direction < 0:
                regressed = change_pct > max_regression_pct
            else:
                regressed = False
            report.deltas.append(
                MetricDelta(
                    suite=suite_name,
                    metric=metric,
                    baseline=float(b),
                    current=float(c),
                    change_pct=round(change_pct, 3),
                    direction=direction,
                    regressed=regressed,
                )
            )
    return report


def load_report(path: str | Path) -> dict:
    """Load a report JSON written by ``eaiv.core.reporter.Reporter``."""
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Report file is not a JSON object: {path}")
    return payload
