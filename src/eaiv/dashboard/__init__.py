"""Data layer for EAIV Mission Control.

Kept inside the package (and free of streamlit/pandas imports) so it is
typed, unit-tested, and reusable by any front end — the bundled Streamlit
app under ``eaiv.dashboard.ui`` is just one consumer.

Modules:
    data     — report loading and metric shaping (legacy-compatible)
    runs     — recorded runs and legacy reports as uniform sources
    signals  — telemetry timing/statistics analysis
    safety   — path and upload guards for browser-supplied input
"""

from __future__ import annotations

from eaiv.dashboard.data import (
    latency_percentiles,
    load_reports,
    metric_by_target,
    metric_history,
    numeric_metrics,
    report_target,
    suite_status,
)
from eaiv.dashboard.runs import (
    ActivityPoint,
    ReportSource,
    active_runs,
    all_sources,
    last_successful,
    legacy_sources,
    load_run_report,
    recent_activity,
    run_sources,
    stage_timeline,
)
from eaiv.dashboard.safety import PathPolicy, UnsafePathError, resolve_within
from eaiv.dashboard.signals import (
    OrientationError,
    SamplingReport,
    SignalStats,
    analyze_sampling,
    analyze_signal,
    group_signals,
    orientation_error,
    reference_pairs,
)


def load_report_source(path: str) -> dict:
    """Load and normalize a single report file (any schema version)."""
    from eaiv.core.report_schema import load_report_file

    return load_report_file(path)


__all__ = [
    "ActivityPoint",
    "OrientationError",
    "PathPolicy",
    "ReportSource",
    "SamplingReport",
    "SignalStats",
    "UnsafePathError",
    "active_runs",
    "all_sources",
    "analyze_sampling",
    "analyze_signal",
    "group_signals",
    "last_successful",
    "latency_percentiles",
    "legacy_sources",
    "load_report_source",
    "load_reports",
    "load_run_report",
    "metric_by_target",
    "metric_history",
    "numeric_metrics",
    "orientation_error",
    "recent_activity",
    "reference_pairs",
    "report_target",
    "resolve_within",
    "run_sources",
    "stage_timeline",
    "suite_status",
]
