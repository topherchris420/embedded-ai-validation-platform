"""Data layer for the telemetry/benchmark dashboard.

Kept inside the package (and free of streamlit/pandas imports) so it is
typed, unit-tested, and reusable by any front end — the bundled Streamlit
app is just one consumer.
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

__all__ = [
    "load_reports",
    "metric_history",
    "numeric_metrics",
    "latency_percentiles",
    "suite_status",
    "report_target",
    "metric_by_target",
]
