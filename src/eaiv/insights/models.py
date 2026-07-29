"""Types for the insight layer.

An insight is a *claim about the run backed by the run's own numbers*.
Every field exists to keep that honest: ``evidence`` holds the values the
claim rests on, ``confidence`` says whether the claim is a direct reading
or an inference, and ``action`` carries the next step — ideally a command
the engineer can run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    INFO = "informational"

    @property
    def rank(self) -> int:
        return {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.INFO: 3,
        }[self]

    @property
    def label(self) -> str:
        return {
            Severity.CRITICAL: "Critical",
            Severity.HIGH: "High",
            Severity.MEDIUM: "Medium",
            Severity.INFO: "Info",
        }[self]

    @property
    def blocks_release(self) -> bool:
        return self in (Severity.CRITICAL, Severity.HIGH)


class InsightCategory(StrEnum):
    """What kind of problem this is — also its position in the queue."""

    EXECUTION = "execution"
    DEADLINE = "deadline"
    BUDGET = "budget"
    REGRESSION = "regression"
    ACCURACY = "accuracy"
    ROBUSTNESS = "robustness"
    HEADROOM = "headroom"
    IMPROVEMENT = "improvement"
    PROVENANCE = "provenance"
    COVERAGE = "coverage"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").capitalize()


#: Explicit priority order. A crash outranks a deadline miss, which
#: outranks a release-blocking regression, and so on. Making this a table
#: (rather than a sort key buried in a comparator) is what makes "why did
#: this insight come first?" answerable and testable.
CATEGORY_RANK: dict[InsightCategory, int] = {
    InsightCategory.EXECUTION: 0,
    InsightCategory.DEADLINE: 1,
    InsightCategory.BUDGET: 1,
    InsightCategory.REGRESSION: 2,
    InsightCategory.ACCURACY: 3,
    InsightCategory.ROBUSTNESS: 3,
    InsightCategory.HEADROOM: 4,
    InsightCategory.IMPROVEMENT: 5,
    InsightCategory.PROVENANCE: 6,
    InsightCategory.COVERAGE: 6,
}


class Confidence(StrEnum):
    """How directly the evidence supports the claim."""

    #: Straight from a recorded measurement or an explicit threshold.
    MEASURED = "measured"
    #: Computed from recorded values (a delta, a percentage, a headroom).
    DERIVED = "derived"
    #: A plausible cause suggested by the pattern, not proven by it.
    INFERRED = "inferred"

    @property
    def label(self) -> str:
        return {
            Confidence.MEASURED: "Direct measurement",
            Confidence.DERIVED: "Derived from measurements",
            Confidence.INFERRED: "Inferred — not directly measured",
        }[self]


@dataclass(frozen=True)
class Evidence:
    """One supporting fact, always a value the run actually recorded."""

    label: str
    value: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "value": self.value, "detail": self.detail}


@dataclass(frozen=True)
class RecommendedAction:
    """What to do next, and where to do it."""

    summary: str
    command: str = ""
    config_path: str = ""
    doc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "command": self.command,
            "config_path": self.config_path,
            "doc": self.doc,
        }


@dataclass(frozen=True)
class ValidationInsight:
    """A prioritized, evidence-backed statement about one validation run."""

    id: str
    severity: Severity
    category: InsightCategory
    title: str
    impact: str = ""
    evidence: tuple[Evidence, ...] = ()
    action: RecommendedAction | None = None
    suite: str = ""
    metrics: tuple[str, ...] = ()
    confidence: Confidence = Confidence.MEASURED
    #: Provenance of the metrics behind this insight ("simulated", ...).
    provenance: str = ""
    #: Ties within a category are broken by magnitude, largest first.
    magnitude: float = 0.0

    @property
    def sort_key(self) -> tuple[int, int, float, str]:
        return (
            CATEGORY_RANK.get(self.category, 9),
            self.severity.rank,
            -abs(self.magnitude),
            self.id,
        )

    @property
    def is_inferred(self) -> bool:
        return self.confidence is Confidence.INFERRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": str(self.severity),
            "category": str(self.category),
            "title": self.title,
            "impact": self.impact,
            "evidence": [e.to_dict() for e in self.evidence],
            "action": self.action.to_dict() if self.action else None,
            "suite": self.suite,
            "metrics": list(self.metrics),
            "confidence": str(self.confidence),
            "provenance": self.provenance,
            "magnitude": self.magnitude,
        }


def sort_insights(insights: list[ValidationInsight]) -> list[ValidationInsight]:
    """Order insights by the documented priority rules."""
    return sorted(insights, key=lambda i: i.sort_key)


__all__ = [
    "CATEGORY_RANK",
    "Confidence",
    "Evidence",
    "InsightCategory",
    "RecommendedAction",
    "Severity",
    "ValidationInsight",
    "sort_insights",
]
