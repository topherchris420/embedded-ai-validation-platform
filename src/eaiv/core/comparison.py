"""Compare two validation runs as a release decision, not a diff.

:mod:`eaiv.core.regression` answers "did any metric move in its bad
direction past the gate?". This module answers the question an engineer
actually asks before shipping: *are these two runs even comparable*, what
changed, what appeared, what disappeared, and what should I do about it.

Compatibility matters more than it looks. Two runs on different boards,
different datasets, or different model files produce numbers that differ
for reasons that have nothing to do with the change under review, so
those differences are surfaced as explicit warnings instead of being
silently averaged into a verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from eaiv.core.metrics import MetricInfo, format_value
from eaiv.core.regression import MetricDelta, compare_reports
from eaiv.core.report_schema import metric_info, normalize_report, overall_provenance


class CompatibilityLevel(StrEnum):
    """How much weight the comparison can bear."""

    COMPARABLE = "comparable"
    CAVEATED = "caveated"
    INCOMPARABLE = "incomparable"

    @property
    def label(self) -> str:
        return {
            CompatibilityLevel.COMPARABLE: "Directly comparable",
            CompatibilityLevel.CAVEATED: "Comparable with caveats",
            CompatibilityLevel.INCOMPARABLE: "Not directly comparable",
        }[self]


@dataclass(frozen=True)
class CompatibilityIssue:
    field: str
    baseline: str
    current: str
    explanation: str
    blocking: bool = False


@dataclass
class Compatibility:
    level: CompatibilityLevel
    issues: list[CompatibilityIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.level is not CompatibilityLevel.INCOMPARABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": str(self.level),
            "issues": [
                {
                    "field": i.field,
                    "baseline": i.baseline,
                    "current": i.current,
                    "explanation": i.explanation,
                    "blocking": i.blocking,
                }
                for i in self.issues
            ],
        }


def _target_identity(report: dict[str, Any]) -> str:
    target = (report.get("meta") or {}).get("target") or {}
    return str(target.get("name") or target.get("kind") or "unknown")


def _input_hash(report: dict[str, Any], key: str) -> str:
    inputs = (report.get("meta") or {}).get("inputs") or {}
    entry = inputs.get(key) or {}
    return str(entry.get("sha256") or "")


def _input_name(report: dict[str, Any], key: str) -> str:
    inputs = (report.get("meta") or {}).get("inputs") or {}
    entry = inputs.get(key) or {}
    return str(entry.get("name") or entry.get("path") or "")


def check_compatibility(baseline: dict[str, Any], current: dict[str, Any]) -> Compatibility:
    """Decide whether two reports can be compared, and say why not."""
    issues: list[CompatibilityIssue] = []

    base_target = _target_identity(baseline)
    curr_target = _target_identity(current)
    if base_target != curr_target:
        issues.append(
            CompatibilityIssue(
                "Target",
                base_target,
                curr_target,
                "Different hardware produces different timing, memory, and power figures. "
                "Metric deltas across boards measure the board, not the change.",
                blocking=True,
            )
        )

    base_prov = overall_provenance(baseline)
    curr_prov = overall_provenance(current)
    if base_prov != curr_prov and "unknown" not in (base_prov, curr_prov):
        issues.append(
            CompatibilityIssue(
                "Measurement provenance",
                base_prov,
                curr_prov,
                "One run is simulated and the other is not; a difference between them is not "
                "evidence about the code.",
                blocking=True,
            )
        )

    for key, label in (("model", "Model"), ("dataset", "Dataset"), ("firmware", "Firmware")):
        base_hash, curr_hash = _input_hash(baseline, key), _input_hash(current, key)
        if base_hash and curr_hash and base_hash != curr_hash:
            issues.append(
                CompatibilityIssue(
                    label,
                    f"{_input_name(baseline, key)} ({base_hash[:12]})",
                    f"{_input_name(current, key)} ({curr_hash[:12]})",
                    f"The {label.lower()} changed between the runs, so metric changes may come "
                    "from the input rather than the code.",
                )
            )

    base_suites = {s.get("name") for s in baseline.get("suites") or []}
    curr_suites = {s.get("name") for s in current.get("suites") or []}
    if base_suites != curr_suites:
        only_base = sorted(str(s) for s in base_suites - curr_suites)
        only_curr = sorted(str(s) for s in curr_suites - base_suites)
        issues.append(
            CompatibilityIssue(
                "Suite coverage",
                ", ".join(only_base) or "—",
                ", ".join(only_curr) or "—",
                "The two runs did not execute the same suites; only shared suites are compared.",
            )
        )

    base_version = str((baseline.get("meta") or {}).get("eaiv_version", ""))
    curr_version = str((current.get("meta") or {}).get("eaiv_version", ""))
    if base_version and curr_version and base_version != curr_version:
        issues.append(
            CompatibilityIssue(
                "eaiv version",
                base_version,
                curr_version,
                "Metric definitions can change between platform versions.",
            )
        )

    if any(i.blocking for i in issues):
        level = CompatibilityLevel.INCOMPARABLE
    elif issues:
        level = CompatibilityLevel.CAVEATED
    else:
        level = CompatibilityLevel.COMPARABLE
    return Compatibility(level, issues)


@dataclass(frozen=True)
class MetricChange:
    """One metric's movement, with everything needed to render it."""

    suite: str
    metric: str
    baseline: float | None
    current: float | None
    change_pct: float | None
    direction: int
    regressed: bool
    info: MetricInfo
    status: str  # improved | regressed | unchanged | informational | added | removed

    @property
    def absolute_change(self) -> float | None:
        if self.baseline is None or self.current is None:
            return None
        return self.current - self.baseline

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "absolute_change": self.absolute_change,
            "change_pct": self.change_pct,
            "direction": self.direction,
            "status": self.status,
            "unit": self.info.unit,
            "provenance": str(self.info.provenance),
        }


@dataclass
class RunComparison:
    """The full release-decision view of two runs."""

    baseline_label: str
    current_label: str
    compatibility: Compatibility
    changes: list[MetricChange] = field(default_factory=list)
    max_regression_pct: float = 10.0

    @property
    def regressions(self) -> list[MetricChange]:
        return sorted(
            [c for c in self.changes if c.status == "regressed"],
            key=lambda c: -abs(c.change_pct or 0),
        )

    @property
    def improvements(self) -> list[MetricChange]:
        return sorted(
            [c for c in self.changes if c.status == "improved"],
            key=lambda c: -abs(c.change_pct or 0),
        )

    @property
    def added(self) -> list[MetricChange]:
        return [c for c in self.changes if c.status == "added"]

    @property
    def removed(self) -> list[MetricChange]:
        return [c for c in self.changes if c.status == "removed"]

    @property
    def shared(self) -> list[MetricChange]:
        return [c for c in self.changes if c.status not in ("added", "removed")]

    def by_suite(self) -> dict[str, list[MetricChange]]:
        grouped: dict[str, list[MetricChange]] = {}
        for change in self.changes:
            grouped.setdefault(change.suite, []).append(change)
        for items in grouped.values():
            items.sort(key=lambda c: (-abs(c.change_pct or 0), c.metric))
        return dict(sorted(grouped.items()))

    @property
    def counts(self) -> dict[str, int]:
        out = {
            "improved": 0,
            "regressed": 0,
            "unchanged": 0,
            "informational": 0,
            "added": 0,
            "removed": 0,
        }
        for change in self.changes:
            out[change.status] = out.get(change.status, 0) + 1
        return out

    @property
    def recommendation(self) -> str:
        if not self.compatibility.ok:
            return (
                "Do not draw conclusions from this pair — "
                f"{self.compatibility.issues[0].explanation}"
            )
        if self.regressions:
            worst = self.regressions[0]
            return (
                f"Hold the release: {worst.suite}.{worst.metric} regressed "
                f"{abs(worst.change_pct or 0):.1f}% beyond the {self.max_regression_pct:g}% gate."
            )
        if self.compatibility.level is CompatibilityLevel.CAVEATED:
            return (
                "No gated regressions, but the runs differ in setup — confirm the caveats "
                "above before treating this as a clean comparison."
            )
        if self.improvements:
            return (
                f"Safe to promote: {len(self.improvements)} metric(s) improved and nothing "
                "regressed beyond the gate."
            )
        return "No regressions beyond the gate; the runs are equivalent within tolerance."


def _status_for(delta: MetricDelta, epsilon_pct: float) -> str:
    if delta.regressed:
        return "regressed"
    if delta.direction == 0:
        return "informational"
    if delta.direction > 0 and delta.change_pct > epsilon_pct:
        return "improved"
    if delta.direction < 0 and delta.change_pct < -epsilon_pct:
        return "improved"
    return "unchanged"


def _numeric_metrics(report: dict[str, Any]) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for entry in report.get("suites") or []:
        if not isinstance(entry, dict):
            continue
        suite = str(entry.get("name", "?"))
        for metric, value in (entry.get("metrics") or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            out[(suite, str(metric))] = float(value)
    return out


def compare_runs(
    baseline: dict[str, Any],
    current: dict[str, Any],
    max_regression_pct: float = 10.0,
    epsilon_pct: float = 1.0,
    baseline_label: str = "baseline",
    current_label: str = "current",
) -> RunComparison:
    """Full comparison: compatibility, deltas, and metrics that appeared or vanished."""
    base = normalize_report(baseline)
    curr = normalize_report(current)
    compatibility = check_compatibility(base, curr)
    regression = compare_reports(base, curr, max_regression_pct=max_regression_pct)

    changes: list[MetricChange] = []
    for delta in regression.deltas:
        changes.append(
            MetricChange(
                suite=delta.suite,
                metric=delta.metric,
                baseline=delta.baseline,
                current=delta.current,
                change_pct=delta.change_pct,
                direction=delta.direction,
                regressed=delta.regressed,
                info=metric_info(curr, delta.suite, delta.metric),
                status=_status_for(delta, epsilon_pct),
            )
        )

    base_metrics = _numeric_metrics(base)
    curr_metrics = _numeric_metrics(curr)
    for key in sorted(set(curr_metrics) - set(base_metrics)):
        suite, metric = key
        info = metric_info(curr, suite, metric)
        changes.append(
            MetricChange(
                suite, metric, None, curr_metrics[key], None, info.direction, False, info, "added"
            )
        )
    for key in sorted(set(base_metrics) - set(curr_metrics)):
        suite, metric = key
        info = metric_info(base, suite, metric)
        changes.append(
            MetricChange(
                suite, metric, base_metrics[key], None, None, info.direction, False, info, "removed"
            )
        )

    return RunComparison(
        baseline_label=baseline_label,
        current_label=current_label,
        compatibility=compatibility,
        changes=changes,
        max_regression_pct=max_regression_pct,
    )


# -- exports ---------------------------------------------------------------


def to_markdown(comparison: RunComparison) -> str:
    """Render a comparison as a PR-ready Markdown document."""
    lines = [
        "# Validation comparison",
        "",
        f"Baseline: `{comparison.baseline_label}`  ",
        f"Current: `{comparison.current_label}`  ",
        f"Compatibility: **{comparison.compatibility.level.label}**",
        "",
        f"**Recommendation:** {comparison.recommendation}",
        "",
    ]
    if comparison.compatibility.issues:
        lines += [
            "## Compatibility notes",
            "",
            "| Field | Baseline | Current | Why it matters |",
            "|-------|----------|---------|----------------|",
        ]
        for issue in comparison.compatibility.issues:
            lines.append(
                f"| {issue.field} | {issue.baseline} | {issue.current} | {issue.explanation} |"
            )
        lines.append("")

    counts = comparison.counts
    lines += [
        "## Summary",
        "",
        f"- Regressed: {counts['regressed']}",
        f"- Improved: {counts['improved']}",
        f"- Unchanged: {counts['unchanged']}",
        f"- Informational: {counts['informational']}",
        f"- New metrics: {counts['added']}",
        f"- Missing metrics: {counts['removed']}",
        "",
    ]

    for suite, items in comparison.by_suite().items():
        lines += [
            f"## {suite}",
            "",
            "| Metric | Baseline | Current | Change | % | Verdict |",
            "|--------|----------|---------|--------|---|---------|",
        ]
        for change in items:
            base_text = (
                format_value(change.baseline, change.info) if change.baseline is not None else "—"
            )
            curr_text = (
                format_value(change.current, change.info) if change.current is not None else "—"
            )
            abs_text = (
                format_value(change.absolute_change, change.info)
                if change.absolute_change is not None
                else "—"
            )
            pct_text = f"{change.change_pct:+.2f}%" if change.change_pct is not None else "—"
            lines.append(
                f"| {change.metric} | {base_text} | {curr_text} | {abs_text} | "
                f"{pct_text} | {change.status} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def to_json(comparison: RunComparison) -> str:
    """Render a comparison as machine-readable JSON."""
    payload = {
        "baseline": comparison.baseline_label,
        "current": comparison.current_label,
        "max_regression_pct": comparison.max_regression_pct,
        "compatibility": comparison.compatibility.to_dict(),
        "recommendation": comparison.recommendation,
        "counts": comparison.counts,
        "changes": [c.to_dict() for c in comparison.changes],
    }
    return json.dumps(payload, indent=2)


__all__ = [
    "Compatibility",
    "CompatibilityIssue",
    "CompatibilityLevel",
    "MetricChange",
    "RunComparison",
    "check_compatibility",
    "compare_runs",
    "to_json",
    "to_markdown",
]
