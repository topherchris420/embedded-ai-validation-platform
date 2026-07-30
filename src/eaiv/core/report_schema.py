"""Versioned report payloads and normalization of older ones.

Reports written before this schema existed have no ``schema_version``,
no metric metadata, and no reproduction context. They are still valid
inputs: :func:`normalize_report` upgrades any payload to the current
in-memory shape without touching the file on disk, so a dashboard, a
comparison, or the insight engine can treat a two-year-old artifact and a
report written a second ago identically.

Nothing here mutates its argument, and nothing here invents data: fields
that a legacy report genuinely lacks come back empty and are labelled
``legacy`` so the UI can say so.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eaiv.core.metrics import MetricInfo, MetricProvenance, infer_metric_info

#: Current on-disk report schema.
#:  1 — original: timestamp, meta{eaiv_version,target}, suites[], all_passed
#:  2 — adds schema_version, run identity, reproduction context (config,
#:      dataset/model/firmware identity, host, git), metric metadata
#:      (unit/direction/provenance) and explicit thresholds.
REPORT_SCHEMA_VERSION = 2

LEGACY_SCHEMA_VERSION = 1


def report_schema_version(payload: dict[str, Any]) -> int:
    """Schema version of a payload; absent means the original format."""
    try:
        return int(payload.get("schema_version", LEGACY_SCHEMA_VERSION))
    except (TypeError, ValueError):
        return LEGACY_SCHEMA_VERSION


def is_report(payload: Any) -> bool:
    """Cheap structural check used when scanning directories."""
    return isinstance(payload, dict) and isinstance(payload.get("suites"), list)


def normalize_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` in the current schema shape.

    Unknown future versions are passed through with their fields intact —
    forward compatibility beats refusing to open the file.
    """
    if not is_report(payload):
        raise ValueError("Not a validation report: missing a 'suites' list")

    version = report_schema_version(payload)
    normalized: dict[str, Any] = dict(payload)
    normalized["schema_version"] = max(version, LEGACY_SCHEMA_VERSION)
    normalized["legacy"] = version < REPORT_SCHEMA_VERSION

    meta = dict(payload.get("meta") or {})
    meta.setdefault("eaiv_version", "unknown")
    meta.setdefault("target", {})
    meta.setdefault("host", {})
    meta.setdefault("git", {})
    meta.setdefault("config", {})
    meta.setdefault("thresholds", {})
    meta.setdefault("inputs", {})
    meta.setdefault("plugins", {})
    meta.setdefault("baseline", "")
    normalized["meta"] = meta

    suites: list[dict[str, Any]] = []
    for entry in payload.get("suites") or []:
        if not isinstance(entry, dict):
            continue
        suite = dict(entry)
        suite.setdefault("name", "?")
        suite["passed"] = bool(suite.get("passed"))
        metrics = suite.get("metrics")
        suite["metrics"] = dict(metrics) if isinstance(metrics, dict) else {}
        suite["notes"] = str(suite.get("notes", ""))
        meta_map = suite.get("metric_meta")
        suite["metric_meta"] = dict(meta_map) if isinstance(meta_map, dict) else {}
        suites.append(suite)
    normalized["suites"] = suites

    normalized.setdefault("timestamp", "")
    normalized["all_passed"] = bool(
        payload.get("all_passed", all(s["passed"] for s in suites) if suites else False)
    )
    run = payload.get("run")
    normalized["run"] = dict(run) if isinstance(run, dict) else {}
    return normalized


def suite_payload(report: dict[str, Any], suite: str) -> dict[str, Any] | None:
    for entry in report.get("suites") or []:
        if isinstance(entry, dict) and entry.get("name") == suite:
            return entry
    return None


def metric_info(report: dict[str, Any], suite: str, metric: str) -> MetricInfo:
    """Metadata for one metric: explicit if declared, inferred otherwise."""
    entry = suite_payload(report, suite) or {}
    declared = entry.get("metric_meta")
    if isinstance(declared, dict) and isinstance(declared.get(metric), dict):
        return MetricInfo.from_dict(metric, declared[metric])
    return infer_metric_info(metric)


def report_provenance(report: dict[str, Any]) -> dict[str, int]:
    """Count metrics by provenance across the whole report."""
    counts: dict[str, int] = {}
    for entry in report.get("suites") or []:
        if not isinstance(entry, dict):
            continue
        for metric, value in (entry.get("metrics") or {}).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            info = metric_info(report, str(entry.get("name", "?")), metric)
            counts[str(info.provenance)] = counts.get(str(info.provenance), 0) + 1
    return counts


def overall_provenance(report: dict[str, Any]) -> str:
    """One word for "were these numbers real?".

    ``measured`` only when every metric claims a physical/host measurement;
    ``simulated`` when none do; ``mixed`` in between; ``unknown`` when the
    report predates provenance tracking.
    """
    counts = report_provenance(report)
    if not counts:
        return "unknown"
    unknown = counts.get(str(MetricProvenance.UNKNOWN), 0)
    total = sum(counts.values())
    if unknown == total:
        return "unknown"
    measured = counts.get(str(MetricProvenance.MEASURED), 0)
    if measured == total:
        return "measured"
    if measured == 0:
        return "simulated"
    return "mixed"


def file_identity(path: str | Path, max_hash_bytes: int = 256 * 1024 * 1024) -> dict[str, Any]:
    """Name, size, and SHA-256 of an input file — or why it is missing.

    Hashing is skipped (and said to be skipped) for very large files so a
    multi-gigabyte dataset cannot stall a run.
    """
    file = Path(path)
    identity: dict[str, Any] = {"path": str(file), "name": file.name, "exists": file.exists()}
    if not file.exists() or not file.is_file():
        return identity
    size = file.stat().st_size
    identity["size_bytes"] = size
    if size > max_hash_bytes:
        identity["sha256"] = ""
        identity["hash_skipped"] = "file larger than the hashing limit"
        return identity
    digest = hashlib.sha256()
    try:
        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        identity["hash_skipped"] = f"unreadable: {exc}"
        return identity
    identity["sha256"] = digest.hexdigest()
    return identity


def load_report_file(path: str | Path) -> dict[str, Any]:
    """Load and normalize a report file with a precise error message."""
    file = Path(path)
    try:
        raw = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read report {file}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Report {file} is not valid JSON (line {exc.lineno}): {exc.msg}") from exc
    normalized = normalize_report(payload)
    normalized["source_file"] = str(file)
    return normalized


__all__ = [
    "LEGACY_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "file_identity",
    "is_report",
    "load_report_file",
    "metric_info",
    "normalize_report",
    "overall_provenance",
    "report_provenance",
    "report_schema_version",
    "suite_payload",
]
