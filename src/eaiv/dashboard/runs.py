"""Run-aware data layer shared by every dashboard page.

Two kinds of artifact coexist on disk: recorded runs (``reports/runs/<id>/``,
with a manifest, an event log, and a report) and bare report files from
older versions or from ``eaiv run`` (``reports/report_*.json``). Pages
should not care which is which, so both are surfaced here as
:class:`ReportSource` — a uniform handle with an id, a label, a
timestamp, a target, and a lazily-loaded normalized report.

No Streamlit import lives in this module: it is typed, unit-tested, and
reusable by any front end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eaiv.core.report_schema import load_report_file, normalize_report, overall_provenance
from eaiv.runs.models import RunManifest, RunStatus
from eaiv.runs.store import RunStore


@dataclass
class ReportSource:
    """One comparable artifact, whether or not it came from a recorded run."""

    id: str
    label: str
    timestamp: str
    target: str
    path: Path
    kind: str = "run"  # run | legacy | baseline
    manifest: RunManifest | None = None
    _report: dict[str, Any] | None = field(default=None, repr=False)

    def report(self) -> dict[str, Any] | None:
        """The normalized report payload, loaded on first use."""
        if self._report is None:
            try:
                self._report = load_report_file(self.path)
            except (OSError, ValueError):
                return None
        return self._report

    @property
    def passed(self) -> bool | None:
        report = self.report()
        return None if report is None else bool(report.get("all_passed"))

    @property
    def provenance(self) -> str:
        if self.manifest is not None and self.manifest.provenance != "unknown":
            return self.manifest.provenance
        report = self.report()
        return overall_provenance(report) if report else "unknown"


def run_report_path(store: RunStore, run_id: str) -> Path:
    return store.run_dir(run_id) / "report.json"


def load_run_report(store: RunStore, run_id: str) -> dict[str, Any] | None:
    """The normalized report for a recorded run, or None if it has none."""
    path = run_report_path(store, run_id)
    if not path.exists():
        return None
    try:
        return load_report_file(path)
    except (OSError, ValueError):
        return None


def run_sources(store: RunStore, limit: int | None = None) -> list[ReportSource]:
    """Recorded runs that produced a report, newest first."""
    out: list[ReportSource] = []
    for manifest in store.list(limit=limit):
        path = run_report_path(store, manifest.run_id)
        if not path.exists():
            continue
        out.append(
            ReportSource(
                id=manifest.run_id,
                label=f"{manifest.display_name} · {manifest.created_at[:19]}",
                timestamp=manifest.created_at,
                target=manifest.target_label,
                path=path,
                kind="run",
                manifest=manifest,
            )
        )
    return out


def legacy_sources(report_dir: str | Path) -> list[ReportSource]:
    """Bare ``report_*.json`` files, newest first.

    These are what ``eaiv run`` and every pre-run-model version wrote.
    They stay first-class citizens of the dashboard.
    """
    directory = Path(report_dir)
    if not directory.exists():
        return []
    out: list[ReportSource] = []
    for path in sorted(directory.glob("report_*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or "suites" not in payload:
            continue
        report = normalize_report(payload)
        report["source_file"] = str(path)
        target = (report.get("meta") or {}).get("target") or {}
        timestamp = str(report.get("timestamp", ""))
        out.append(
            ReportSource(
                id=path.stem,
                label=f"{path.name} · {timestamp[:19]}",
                timestamp=timestamp,
                target=str(target.get("name") or target.get("kind") or "?"),
                path=path,
                kind="legacy",
                _report=report,
            )
        )
    return out


def all_sources(store: RunStore, report_dir: str | Path) -> list[ReportSource]:
    """Recorded runs plus legacy reports, newest first, de-duplicated.

    A recorded run also writes a legacy ``report_<timestamp>.json`` into
    the report directory. Those duplicates are dropped in favour of the
    richer run entry, matched on the report timestamp.
    """
    runs = run_sources(store)
    seen_timestamps = set()
    for source in runs:
        report = source.report()
        if report:
            seen_timestamps.add(str(report.get("timestamp", "")))
    merged = list(runs)
    for source in legacy_sources(report_dir):
        if source.timestamp and source.timestamp in seen_timestamps:
            continue
        merged.append(source)
    merged.sort(key=lambda s: s.timestamp, reverse=True)
    return merged


@dataclass
class ActivityPoint:
    """One entry in the recent-run timeline."""

    run_id: str
    name: str
    timestamp: str
    status: str
    passed_suites: int
    total_suites: int
    target: str
    duration_s: float
    provenance: str


def recent_activity(store: RunStore, limit: int = 20) -> list[ActivityPoint]:
    """Newest runs as timeline points, oldest first for plotting."""
    points = [
        ActivityPoint(
            run_id=m.run_id,
            name=m.display_name,
            timestamp=m.created_at,
            status=str(m.status),
            passed_suites=m.summary.passed_suites,
            total_suites=m.summary.total_suites,
            target=m.target_label,
            duration_s=m.duration_s,
            provenance=m.provenance,
        )
        for m in store.list(limit=limit)
    ]
    points.reverse()
    return points


def last_successful(store: RunStore) -> RunManifest | None:
    return store.latest_successful()


def active_runs(store: RunStore) -> list[RunManifest]:
    """Runs currently executing (after reconciling abandoned ones)."""
    return [m for m in store.list() if m.status in (RunStatus.RUNNING, RunStatus.PENDING)]


def stage_timeline(manifest: RunManifest) -> list[dict[str, Any]]:
    """Stage rows for the live-run view, including stages not reached yet."""
    from eaiv.core.pipeline import STAGES

    recorded = {s.name: s for s in manifest.stages}
    rows: list[dict[str, Any]] = []
    for name in STAGES:
        stage = recorded.get(name)
        rows.append(
            {
                "stage": name,
                "status": str(stage.status) if stage else "pending",
                "duration_s": stage.duration_s if stage else 0.0,
                "detail": stage.detail if stage else "",
                "failure": stage.failure.message if stage and stage.failure else "",
            }
        )
    for name, stage in recorded.items():
        if name not in STAGES:
            rows.append(
                {
                    "stage": name,
                    "status": str(stage.status),
                    "duration_s": stage.duration_s,
                    "detail": stage.detail,
                    "failure": stage.failure.message if stage.failure else "",
                }
            )
    return rows


__all__ = [
    "ActivityPoint",
    "ReportSource",
    "active_runs",
    "all_sources",
    "last_successful",
    "legacy_sources",
    "load_run_report",
    "recent_activity",
    "run_report_path",
    "run_sources",
    "stage_timeline",
]
