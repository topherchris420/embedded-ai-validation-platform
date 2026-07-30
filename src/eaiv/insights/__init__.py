"""Deterministic diagnosis of validation runs.

The engine reads the numbers a run recorded — suite verdicts, metrics,
configured thresholds, regression deltas, stage failures — and returns
prioritized :class:`ValidationInsight` objects saying what failed, by how
much, why it matters, and what to do next. Nothing is invented: an
insight that cannot point at the evidence behind it does not exist.

    from eaiv.insights import generate_insights, decide

    insights = generate_insights(report, regression, manifest)
    decision = decide(report, insights)
"""

from __future__ import annotations

from eaiv.insights.engine import (
    HEADROOM_WARNING_FRACTION,
    IMPROVEMENT_REPORT_PCT,
    blocking_insights,
    generate_insights,
    top_insight,
)
from eaiv.insights.models import (
    CATEGORY_RANK,
    Confidence,
    Evidence,
    InsightCategory,
    RecommendedAction,
    Severity,
    ValidationInsight,
    sort_insights,
)
from eaiv.insights.verdict import ReleaseDecision, Verdict, decide

__all__ = [
    "CATEGORY_RANK",
    "HEADROOM_WARNING_FRACTION",
    "IMPROVEMENT_REPORT_PCT",
    "Confidence",
    "Evidence",
    "InsightCategory",
    "RecommendedAction",
    "ReleaseDecision",
    "Severity",
    "ValidationInsight",
    "Verdict",
    "blocking_insights",
    "decide",
    "generate_insights",
    "sort_insights",
    "top_insight",
]
