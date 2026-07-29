"""On-disk storage for validation runs.

Layout (``reports/`` by default)::

    reports/
      runs/
        <run-id>/
          manifest.json        run identity, stages, artifacts, outcome
          events.jsonl         append-only event log
          report.json          report artifacts (also mirrored to reports/)
          report.md
          report.csv
          report.html
          telemetry.csv
          resolved-config.yaml
          logs/run.log
      latest.json              legacy pointer, still written
      report_<timestamp>.json  legacy per-run report, still written

Manifests are written atomically (temp file + ``os.replace``) so a
process killed mid-write leaves the previous manifest intact rather than
a truncated file. A run whose process died is *reconciled* to
``interrupted`` on the next read — a completed run must never look active
and an abandoned one must never look alive.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eaiv.runs.cancel import CANCEL_FILENAME, clear_cancel, request_cancel
from eaiv.runs.events import PipelineEvent, read_events, utcnow
from eaiv.runs.models import (
    RunManifest,
    RunStatus,
    is_valid_run_id,
)

log = logging.getLogger("eaiv.runs")

MANIFEST_NAME = "manifest.json"
EVENTS_NAME = "events.jsonl"

#: A ``running`` manifest whose heartbeat is older than this — and whose
#: process is gone — is treated as interrupted.
DEFAULT_STALE_AFTER_S = 90.0


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    """Write ``text`` to ``path`` atomically within the same directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def atomic_write_json(path: str | Path, payload: Any, indent: int = 2) -> Path:
    return atomic_write_text(path, json.dumps(payload, indent=indent, default=str))


def _process_alive(pid: int) -> bool:
    """True when a PID exists on this host (best effort, cross-platform)."""
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        return True  # no cheap portable probe; fall back to the heartbeat
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _age_seconds(timestamp: str) -> float:
    if not timestamp:
        return float("inf")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return float("inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


class RunStore:
    """Reads and writes run directories under ``<root>/runs``."""

    def __init__(self, root: str | Path = "reports") -> None:
        self.root = Path(root)
        self.runs_root = self.root / "runs"

    # -- addressing --------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        """Directory for a run.

        Raises ``ValueError`` for identifiers that could escape the store;
        run IDs reach this method from URLs and form fields.
        """
        if not is_valid_run_id(run_id):
            raise ValueError(f"Invalid run id: {run_id!r}")
        return self.runs_root / run_id

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / MANIFEST_NAME

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / EVENTS_NAME

    def artifact_path(self, run_id: str, relative: str) -> Path:
        """Resolve an artifact path, refusing anything outside the run dir."""
        base = self.run_dir(run_id).resolve()
        candidate = (base / relative).resolve()
        if candidate != base and base not in candidate.parents:
            raise ValueError(f"Artifact path escapes run directory: {relative!r}")
        return candidate

    # -- lifecycle ---------------------------------------------------------

    def create(self, manifest: RunManifest) -> Path:
        """Create the run directory and persist the initial manifest."""
        directory = self.run_dir(manifest.run_id)
        (directory / "logs").mkdir(parents=True, exist_ok=True)
        clear_cancel(directory)
        self.save(manifest)
        return directory

    def save(self, manifest: RunManifest) -> Path:
        """Persist a manifest atomically, refreshing its heartbeat."""
        manifest.heartbeat = utcnow()
        return atomic_write_json(self.manifest_path(manifest.run_id), manifest.to_dict())

    def load(self, run_id: str, reconcile: bool = True) -> RunManifest:
        path = self.manifest_path(run_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Manifest is not a JSON object: {path}")
        manifest = RunManifest.from_dict(payload)
        if reconcile:
            manifest = self._reconcile(manifest)
        return manifest

    def exists(self, run_id: str) -> bool:
        try:
            return self.manifest_path(run_id).exists()
        except ValueError:
            return False

    def list(self, limit: int | None = None, reconcile: bool = True) -> list[RunManifest]:
        """All runs, newest first. Unreadable manifests are skipped."""
        if not self.runs_root.exists():
            return []
        manifests: list[RunManifest] = []
        for directory in sorted(self.runs_root.iterdir(), reverse=True):
            if not directory.is_dir() or not (directory / MANIFEST_NAME).exists():
                continue
            try:
                manifests.append(self.load(directory.name, reconcile=reconcile))
            except (OSError, ValueError, json.JSONDecodeError):
                log.warning("skipping unreadable run manifest in %s", directory)
                continue
        manifests.sort(key=lambda m: (m.created_at, m.run_id), reverse=True)
        return manifests[:limit] if limit else manifests

    def latest(self) -> RunManifest | None:
        runs = self.list(limit=1)
        return runs[0] if runs else None

    def latest_successful(self) -> RunManifest | None:
        for manifest in self.list():
            if manifest.status is RunStatus.PASSED:
                return manifest
        return None

    def delete(self, run_id: str) -> None:
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    # -- events ------------------------------------------------------------

    def events(self, run_id: str, after_seq: int = 0) -> list[PipelineEvent]:
        return read_events(self.events_path(run_id), after_seq=after_seq)

    # -- cancellation ------------------------------------------------------

    def request_cancel(self, run_id: str, reason: str = "cancelled by user") -> Path:
        return request_cancel(self.run_dir(run_id), reason)

    def cancel_requested(self, run_id: str) -> bool:
        return (self.run_dir(run_id) / CANCEL_FILENAME).exists()

    # -- recovery ----------------------------------------------------------

    @staticmethod
    def _is_abandoned(manifest: RunManifest, stale_after_s: float) -> bool:
        """Decide whether a ``running`` manifest belongs to a dead process.

        A fresh heartbeat always means "alive" — the pipeline refreshes it
        on every event, so even a long stage keeps it current. Past that,
        a live PID buys the run more time (a stopped debugger, a paused
        container), but only up to a hard ceiling, because PIDs get
        recycled and a recycled PID must not keep a dead run "active"
        forever.
        """
        age = _age_seconds(manifest.heartbeat)
        if age < stale_after_s:
            return False
        if age > stale_after_s * 12 and not manifest.status == RunStatus.PENDING:
            return True
        return not _process_alive(manifest.pid)

    def _reconcile(
        self, manifest: RunManifest, stale_after_s: float = DEFAULT_STALE_AFTER_S
    ) -> RunManifest:
        """Downgrade an abandoned ``running`` manifest to ``interrupted``."""
        if manifest.status not in (RunStatus.RUNNING, RunStatus.PENDING):
            return manifest
        if not self._is_abandoned(manifest, stale_after_s):
            return manifest

        from eaiv.runs.models import RunFailure, StageStatus

        manifest.status = RunStatus.INTERRUPTED
        manifest.completed_at = manifest.completed_at or utcnow()
        if manifest.failure is None:
            manifest.failure = RunFailure(
                stage=next(
                    (s.name for s in manifest.stages if s.status is StageStatus.RUNNING),
                    "",
                ),
                type="RunInterrupted",
                message=(
                    "The process running this validation exited before the run finished "
                    "(host restart, terminal closed, or the process was killed)."
                ),
                hint="Re-run the mission; partial artifacts from this run are kept for inspection.",
            )
        for stage in manifest.stages:
            if stage.status is StageStatus.RUNNING:
                stage.status = StageStatus.FAILED
                stage.detail = stage.detail or "interrupted"
        try:
            atomic_write_json(self.manifest_path(manifest.run_id), manifest.to_dict())
        except OSError:  # pragma: no cover - read-only filesystem
            log.warning("could not persist reconciled manifest for %s", manifest.run_id)
        return manifest

    def reconcile_all(self, stale_after_s: float = DEFAULT_STALE_AFTER_S) -> list[str]:
        """Mark every abandoned run as interrupted; return the affected IDs."""
        changed: list[str] = []
        for manifest in self.list(reconcile=False):
            if manifest.status not in (RunStatus.RUNNING, RunStatus.PENDING):
                continue
            reconciled = self._reconcile(manifest, stale_after_s=stale_after_s)
            if reconciled.status is RunStatus.INTERRUPTED:
                changed.append(reconciled.run_id)
        return changed


__all__ = [
    "DEFAULT_STALE_AFTER_S",
    "EVENTS_NAME",
    "MANIFEST_NAME",
    "RunStore",
    "atomic_write_json",
    "atomic_write_text",
]
