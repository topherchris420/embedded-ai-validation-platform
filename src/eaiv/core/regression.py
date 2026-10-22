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
import math
from dataclasses import dataclass, field
from pathlib import Path

from eaiv.core.evidence import GateIssue, finite_number, report_issues, suite_map

_LOWER_IS_BETTER_HINTS = (
    "_ms",
    "_us",
    "_mj",
    "overruns",
    "confidence_stability",
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
    issues: list[GateIssue] = field(default_factory=list)

    @property
    def regressions(self) -> list[MetricDelta]:
        return [d for d in self.deltas if d.regressed]

    @property
    def passed(self) -> bool:
        return not self.regressions and not self.issues

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
    """Compare evidence without treating absent or invalid data as success.

    Declared direction overrides name inference. Mock values on either side
    remain informational unless explicitly requested. A zero baseline uses
    signed infinity internally; export layers render that as an undefined
    percentage rather than emitting non-standard JSON.
    """
    if not finite_number(max_regression_pct) or max_regression_pct < 0:
        raise ValueError("max_regression_pct must be a finite, non-negative number")
    report = RegressionReport()
    for label, payload in (("Baseline", baseline), ("Current", current)):
        report.issues.extend(
            GateIssue(i.code, f"{label}: {i.message}", i.suite, i.metric)
            for i in report_issues(payload)
        )
    # Keep well-formed failures comparable so the user still sees their deltas.
    if any(
        i.code not in {"suite-failed", "report-failed", "incomplete-run", "invalid-number"}
        for i in report.issues
    ):
        return report
    base_suites, curr_suites = suite_map(baseline), suite_map(current)
    base_target = (baseline.get("meta") or {}).get("target") or {}
    curr_target = (current.get("meta") or {}).get("target") or {}
    for key in ("name", "kind", "arch", "clock_hz"):
        if base_target.get(key) and base_target[key] != curr_target.get(key):
            report.issues.append(
                GateIssue(
                    "target-mismatch",
                    f"Target {key} changed: {base_target[key]} -> {curr_target.get(key)}.",
                )
            )
    for name in sorted(base_suites.keys() - curr_suites.keys()):
        report.issues.append(
            GateIssue(
                "missing-suite", f"Baseline suite {name!r} is missing from the candidate.", name
            )
        )
    for suite_name in sorted(base_suites.keys() & curr_suites.keys()):
        base_payload, curr_payload = base_suites[suite_name], curr_suites[suite_name]
        base_metrics, curr_metrics = base_payload.get("metrics", {}), curr_payload.get(
            "metrics", {}
        )
        if curr_metrics.get("skipped") and not base_metrics.get("skipped"):
            report.issues.append(
                GateIssue(
                    "skipped-suite",
                    f"Previously executed suite {suite_name!r} is now skipped.",
                    suite_name,
                )
            )
        for metric, value in sorted(base_metrics.items()):
            if not finite_number(value):
                continue
            if metric not in curr_metrics or not finite_number(curr_metrics[metric]):
                report.issues.append(
                    GateIssue(
                        "missing-metric",
                        f"{suite_name}.{metric} has no finite numeric candidate value.",
                        suite_name,
                        metric,
                    )
                )
        for metric in sorted(base_metrics.keys() & curr_metrics.keys()):
            b, c = base_metrics[metric], curr_metrics[metric]
            if not finite_number(b) or not finite_number(c):
                continue
            base_meta = base_payload.get("metric_meta", {}).get(metric, {})
            curr_meta = curr_payload.get("metric_meta", {}).get(metric, {})
            # Missing metadata in a legacy report remains readable. Explicit
            # definitions must agree, including a declared informational direction.
            mismatch = False
            for key in ("unit", "direction", "provenance", "source"):
                if key in base_meta and base_meta[key] != curr_meta.get(key):
                    report.issues.append(
                        GateIssue(
                            "metric-definition-changed",
                            f"{suite_name}.{metric} {key} changed: {base_meta[key]!r} -> {curr_meta.get(key)!r}.",
                            suite_name,
                            metric,
                        )
                    )
                    mismatch = True
            change_pct = (
                ((c - b) / abs(b) * 100.0)
                if b != 0
                else (0.0 if c == 0 else math.copysign(math.inf, c))
            )
            direction = curr_meta.get(
                "direction", base_meta.get("direction", metric_direction(metric))
            )
            if mismatch or (
                not gate_non_measured
                and any(
                    _declared_provenance(payload, metric) in NON_GATING_PROVENANCE
                    for payload in (base_payload, curr_payload)
                )
            ):
                direction = 0
            regressed = (direction > 0 and change_pct < -max_regression_pct) or (
                direction < 0 and change_pct > max_regression_pct
            )
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
    if not report.deltas:
        report.issues.append(
            GateIssue(
                "no-shared-metrics",
                "No shared finite numeric metrics; there is no comparison evidence.",
            )
        )
    return report


def load_report(path: str | Path) -> dict:
    """Load a report JSON written by ``eaiv.core.reporter.Reporter``."""
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Report file is not a JSON object: {path}")
    return payload
