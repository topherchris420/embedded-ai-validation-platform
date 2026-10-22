"""The release decision: can this build ship?

One function, one answer, and the reasons behind it. The rules are
deliberately conservative — a run that could not certify what it claims
to certify (simulation only, skipped coverage, interrupted execution)
never returns a clean "ship".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from eaiv.core.evidence import report_issues
from eaiv.core.metrics import MetricProvenance, MetricSource
from eaiv.core.report_schema import metric_info, overall_provenance
from eaiv.insights.models import Severity, ValidationInsight


class Verdict(StrEnum):
    SHIP = "ship"
    SHIP_WITH_RISK = "ship-with-risk"
    DO_NOT_SHIP = "do-not-ship"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            Verdict.SHIP: "Ready to ship",
            Verdict.SHIP_WITH_RISK: "Further validation required",
            Verdict.DO_NOT_SHIP: "Not ready to ship",
            Verdict.UNKNOWN: "No validation data",
        }[self]

    @property
    def short(self) -> str:
        return {
            Verdict.SHIP: "READY",
            Verdict.SHIP_WITH_RISK: "AT RISK",
            Verdict.DO_NOT_SHIP: "BLOCKED",
            Verdict.UNKNOWN: "UNKNOWN",
        }[self]


@dataclass
class ReleaseDecision:
    """A verdict plus the evidence trail that produced it."""

    verdict: Verdict
    headline: str
    reasons: list[str] = field(default_factory=list)
    blockers: list[ValidationInsight] = field(default_factory=list)
    risks: list[ValidationInsight] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict),
            "headline": self.headline,
            "reasons": list(self.reasons),
            "blockers": [i.id for i in self.blockers],
            "risks": [i.id for i in self.risks],
        }


def decide(
    report: dict[str, Any] | None,
    insights: list[ValidationInsight] | None = None,
) -> ReleaseDecision:
    """Judge a run from its report and its insights."""
    if report is None or not report.get("suites"):
        return ReleaseDecision(
            Verdict.UNKNOWN,
            "No validation results to judge.",
            ["Run a validation mission to get a release verdict."],
        )

    integrity = report_issues(report)
    if any(i.code not in {"suite-failed", "report-failed"} for i in integrity):
        return ReleaseDecision(
            Verdict.DO_NOT_SHIP,
            "Validation evidence is incomplete or invalid",
            [i.message for i in integrity],
        )
    if insights is None:
        from eaiv.insights.engine import generate_insights

        insights = generate_insights(report)
    blockers = [i for i in insights if i.severity in (Severity.CRITICAL, Severity.HIGH)]
    risks = [i for i in insights if i.severity is Severity.MEDIUM]

    failed = [s.get("name", "?") for s in report.get("suites", []) if not s.get("passed")]
    provenance = overall_provenance(report)
    reasons: list[str] = []

    if blockers:
        reasons.append(f"{len(blockers)} blocking issue(s): {blockers[0].title}")
        if failed:
            reasons.append(f"Failing suites: {', '.join(failed)}")
        return ReleaseDecision(Verdict.DO_NOT_SHIP, blockers[0].title, reasons, blockers, risks)

    if integrity:
        return ReleaseDecision(
            Verdict.DO_NOT_SHIP,
            "Validation evidence is incomplete or invalid",
            [i.message for i in integrity],
        )

    if failed:
        reasons.append(f"Failing suites: {', '.join(failed)}")
        return ReleaseDecision(
            Verdict.DO_NOT_SHIP,
            f"{len(failed)} suite(s) failed",
            reasons,
            blockers,
            risks,
        )

    if provenance in ("simulated", "mixed", "unknown"):
        reasons.append(
            "All suites passed, but the measurements are "
            + (
                "simulated — nothing here was recorded on physical hardware."
                if provenance == "simulated"
                else "not all hardware readings."
            )
        )
        if risks:
            reasons.append(f"{len(risks)} open risk(s): {risks[0].title}")
        return ReleaseDecision(
            Verdict.SHIP_WITH_RISK,
            (
                "Passed in simulation — hardware validation still required"
                if provenance == "simulated"
                else "Incomplete device evidence — hardware validation still required"
            ),
            reasons,
            blockers,
            risks,
        )

    non_device = [
        f"{suite['name']}.{name}"
        for suite in report.get("suites", [])
        for name, value in suite.get("metrics", {}).items()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (
            metric_info(report, suite["name"], name).source is not MetricSource.DEVICE
            or metric_info(report, suite["name"], name).provenance is not MetricProvenance.MEASURED
        )
    ]
    skipped = [s["name"] for s in report.get("suites", []) if s.get("metrics", {}).get("skipped")]
    if non_device or skipped:
        if non_device:
            reasons.append(
                "Host, dataset, or unspecified measurements do not validate execution on the target device: "
                + ", ".join(non_device)
            )
        if skipped:
            reasons.append("Skipped suites: " + ", ".join(skipped))
        return ReleaseDecision(
            Verdict.SHIP_WITH_RISK,
            "Target-device validation still required",
            reasons,
            blockers,
            risks,
        )

    if risks:
        reasons.append(f"{len(risks)} open risk(s): {risks[0].title}")
        return ReleaseDecision(Verdict.SHIP_WITH_RISK, risks[0].title, reasons, blockers, risks)

    reasons.append(
        "The executed suites passed on measured target-device data with no open risks. This verdict covers only the recorded workload and thresholds."
    )
    return ReleaseDecision(Verdict.SHIP, "All gates green", reasons, blockers, risks)


__all__ = ["ReleaseDecision", "Verdict", "decide"]
