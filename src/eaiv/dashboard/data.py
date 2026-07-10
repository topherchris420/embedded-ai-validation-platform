"""Load and shape report artifacts for visualization.

Reports are the JSON files written by ``eaiv.core.reporter.Reporter``
(``report_<timestamp>.json``); ``latest.json`` is a duplicate pointer and
is skipped when scanning history.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_reports(report_dir: str | Path) -> list[dict]:
    """Load all timestamped reports, newest first. Malformed files are skipped."""
    reports: list[dict] = []
    directory = Path(report_dir)
    if not directory.exists():
        return reports
    for f in sorted(directory.glob("report_*.json")):
        try:
            payload = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and "suites" in payload:
            payload["source_file"] = str(f)
            reports.append(payload)
    reports.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
    return reports


def suite_status(report: dict) -> list[tuple[str, bool, str]]:
    """(suite, passed, notes) rows for one report."""
    return [
        (s.get("name", "?"), bool(s.get("passed")), str(s.get("notes", "")))
        for s in report.get("suites", [])
    ]


def numeric_metrics(report: dict, suite: str) -> dict[str, float]:
    """Numeric (non-bool) metrics of one suite in one report."""
    for s in report.get("suites", []):
        if s.get("name") == suite:
            return {
                k: float(v)
                for k, v in s.get("metrics", {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
    return {}


def metric_history(reports: list[dict], suite: str, metric: str) -> list[tuple[str, float]]:
    """(timestamp, value) series across reports, oldest first."""
    series: list[tuple[str, float]] = []
    for report in reversed(reports):  # oldest first for plotting
        metrics = numeric_metrics(report, suite)
        if metric in metrics:
            series.append((str(report.get("timestamp", "")), metrics[metric]))
    return series


def report_target(report: dict) -> str:
    """Board identity a report was produced on ("?" for legacy reports)."""
    target = report.get("meta", {}).get("target", {})
    name = target.get("name") or target.get("kind") or "?"
    return str(name)


def metric_by_target(reports: list[dict], suite: str, metric: str) -> dict[str, float]:
    """Latest value of one metric per target — the cross-hardware view.

    Reports are newest-first; the first hit per target wins.
    """
    out: dict[str, float] = {}
    for report in reports:
        target = report_target(report)
        if target in out:
            continue
        metrics = numeric_metrics(report, suite)
        if metric in metrics:
            out[target] = metrics[metric]
    return out


_PERCENTILE_KEYS = ("min_ms", "p50_ms", "mean_ms", "p95_ms", "p99_ms", "max_ms")


def latency_percentiles(metrics: dict[str, float]) -> dict[str, float]:
    """Ordered latency-distribution points present in a metric dict."""
    return {k: metrics[k] for k in _PERCENTILE_KEYS if k in metrics}
