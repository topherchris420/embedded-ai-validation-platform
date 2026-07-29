"""Typed domain model for a validation run.

A report file records *what a run measured*. A :class:`RunManifest`
records *the run itself*: who asked for it, against which target and
configuration, which stages executed, how long they took, what artifacts
they produced, and how it ended. That distinction is what lets the
platform show an in-flight run, a cancelled run, or a run that crashed
before it could write a report at all.

Everything here is plain data with ``to_dict``/``from_dict``: manifests
round-trip through JSON, tolerate fields written by other versions, and
never import a UI toolkit.
"""

from __future__ import annotations

import os
import platform
import re
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from eaiv.runs.events import utcnow

#: Bumped when the manifest layout changes incompatibly.
MANIFEST_SCHEMA_VERSION = 1

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RunStatus(StrEnum):
    """Lifecycle of a validation run."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        return self not in (RunStatus.PENDING, RunStatus.RUNNING)

    @property
    def is_success(self) -> bool:
        return self is RunStatus.PASSED

    @property
    def label(self) -> str:
        return {
            RunStatus.PENDING: "Queued",
            RunStatus.RUNNING: "Running",
            RunStatus.PASSED: "Passed",
            RunStatus.FAILED: "Failed",
            RunStatus.CANCELLED: "Cancelled",
            RunStatus.INTERRUPTED: "Interrupted",
            RunStatus.ERROR: "Error",
        }[self]


class StageStatus(StrEnum):
    """Outcome of a single pipeline stage.

    ``ok``/``failed``/``skipped`` keep the exact strings the pre-existing
    ``StageResult.status`` used, so CLI output and callers comparing
    against literals continue to work unchanged.
    """

    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    REPORT = "report"
    TELEMETRY = "telemetry"
    CONFIG = "config"
    LOG = "log"
    BASELINE = "baseline"
    OTHER = "other"


def _as_str(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


@dataclass
class RunArtifact:
    """A file a run produced, addressed relative to the run directory."""

    name: str
    path: str
    kind: ArtifactKind = ArtifactKind.OTHER
    size_bytes: int = 0
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "kind": str(self.kind),
            "size_bytes": self.size_bytes,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunArtifact:
        try:
            kind = ArtifactKind(_as_str(payload.get("kind"), "other"))
        except ValueError:
            kind = ArtifactKind.OTHER
        return cls(
            name=_as_str(payload.get("name")),
            path=_as_str(payload.get("path")),
            kind=kind,
            size_bytes=_as_int(payload.get("size_bytes")),
            description=_as_str(payload.get("description")),
        )


@dataclass
class RunFailure:
    """Structured diagnostics for a stage or run failure.

    The original exception type and traceback are preserved: a failed run
    should say *what* broke, not just "pipeline failed".
    """

    stage: str = ""
    type: str = ""
    message: str = ""
    traceback: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "type": self.type,
            "message": self.message,
            "traceback": self.traceback,
            "hint": self.hint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunFailure:
        return cls(
            stage=_as_str(payload.get("stage")),
            type=_as_str(payload.get("type")),
            message=_as_str(payload.get("message")),
            traceback=_as_str(payload.get("traceback")),
            hint=_as_str(payload.get("hint")),
        )

    @classmethod
    def from_exception(cls, exc: BaseException, stage: str = "", hint: str = "") -> RunFailure:
        import traceback as tb

        return cls(
            stage=stage,
            type=type(exc).__name__,
            message=str(exc),
            traceback="".join(tb.format_exception(type(exc), exc, exc.__traceback__))[-8000:],
            hint=hint,
        )


@dataclass
class StageRecord:
    """One pipeline stage: status, timing, and failure detail."""

    name: str
    status: StageStatus = StageStatus.PENDING
    started_at: str = ""
    completed_at: str = ""
    duration_s: float = 0.0
    detail: str = ""
    failure: RunFailure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": str(self.status),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": self.duration_s,
            "detail": self.detail,
            "failure": self.failure.to_dict() if self.failure else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StageRecord:
        try:
            status = StageStatus(_as_str(payload.get("status"), "pending"))
        except ValueError:
            status = StageStatus.PENDING
        failure = payload.get("failure")
        return cls(
            name=_as_str(payload.get("name")),
            status=status,
            started_at=_as_str(payload.get("started_at")),
            completed_at=_as_str(payload.get("completed_at")),
            duration_s=_as_float(payload.get("duration_s")),
            detail=_as_str(payload.get("detail")),
            failure=RunFailure.from_dict(failure) if isinstance(failure, dict) else None,
        )


@dataclass
class RunSummary:
    """Headline numbers a dashboard tile or CLI line can render directly."""

    total_suites: int = 0
    passed_suites: int = 0
    failed_suite_names: list[str] = field(default_factory=list)
    metrics_recorded: int = 0
    regressions: int = 0
    improvements: int = 0
    worst_regression: dict[str, Any] | None = None
    all_passed: bool = False

    @property
    def pass_rate(self) -> float:
        return self.passed_suites / self.total_suites if self.total_suites else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_suites": self.total_suites,
            "passed_suites": self.passed_suites,
            "failed_suite_names": list(self.failed_suite_names),
            "metrics_recorded": self.metrics_recorded,
            "regressions": self.regressions,
            "improvements": self.improvements,
            "worst_regression": self.worst_regression,
            "all_passed": self.all_passed,
            "pass_rate": round(self.pass_rate, 4),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunSummary:
        names = payload.get("failed_suite_names")
        worst = payload.get("worst_regression")
        return cls(
            total_suites=_as_int(payload.get("total_suites")),
            passed_suites=_as_int(payload.get("passed_suites")),
            failed_suite_names=[str(n) for n in names] if isinstance(names, list) else [],
            metrics_recorded=_as_int(payload.get("metrics_recorded")),
            regressions=_as_int(payload.get("regressions")),
            improvements=_as_int(payload.get("improvements")),
            worst_regression=worst if isinstance(worst, dict) else None,
            all_passed=bool(payload.get("all_passed")),
        )


def git_info(cwd: str | Path | None = None) -> dict[str, Any]:
    """Best-effort git revision of the working tree, or ``{}``.

    Never raises and never uses a shell: a missing ``git``, a tarball
    checkout, or a timeout simply yields no git metadata.
    """
    root = Path(cwd) if cwd is not None else Path.cwd()

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", *args],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    commit = _git("rev-parse", "HEAD")
    if commit is None:
        return {}
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        "short_commit": commit[:12],
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "",
        "dirty": bool(status),
    }


def host_info() -> dict[str, Any]:
    """Platform identity needed to interpret host-side measurements."""
    try:
        hostname = socket.gethostname()
    except OSError:  # pragma: no cover - defensive
        hostname = ""
    return {
        "hostname": hostname,
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
    }


def eaiv_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("eaiv")
    except PackageNotFoundError:  # pragma: no cover - source checkout without install
        from eaiv import __version__

        return __version__


def new_run_id(prefix: str = "") -> str:
    """Sortable, filesystem-safe, collision-resistant run identifier."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    clean = sanitize_component(prefix)
    return f"{stamp}-{clean}-{suffix}" if clean else f"{stamp}-{suffix}"


def sanitize_component(value: str, max_len: int = 40) -> str:
    """Reduce free text to ``[A-Za-z0-9_-]`` for use inside a path segment."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return cleaned[:max_len].lower()


def is_valid_run_id(run_id: str) -> bool:
    """Run IDs address a directory, so they must not escape the store."""
    return bool(_RUN_ID_RE.match(run_id)) and ".." not in run_id


@dataclass
class RunManifest:
    """Everything known about one validation run."""

    run_id: str
    name: str = ""
    status: RunStatus = RunStatus.PENDING
    created_at: str = field(default_factory=utcnow)
    started_at: str = ""
    completed_at: str = ""
    duration_s: float = 0.0

    suite_selection: str = "all"
    suites: list[str] = field(default_factory=list)
    target: dict[str, Any] = field(default_factory=dict)

    config_path: str = ""
    resolved_config: dict[str, Any] = field(default_factory=dict)

    baseline: str = ""
    save_baseline: str = ""
    max_regression_pct: float = 10.0

    eaiv_version: str = field(default_factory=eaiv_version)
    report_schema_version: int = 0
    manifest_schema_version: int = MANIFEST_SCHEMA_VERSION

    git: dict[str, Any] = field(default_factory=dict)
    host: dict[str, Any] = field(default_factory=dict)

    stages: list[StageRecord] = field(default_factory=list)
    artifacts: list[RunArtifact] = field(default_factory=list)
    summary: RunSummary = field(default_factory=RunSummary)
    failure: RunFailure | None = None
    cancel_reason: str = ""

    provenance: str = "unknown"
    labels: list[str] = field(default_factory=list)
    trigger: str = "cli"
    pid: int = field(default_factory=os.getpid)
    heartbeat: str = field(default_factory=utcnow)

    # -- convenience -------------------------------------------------------

    @property
    def display_name(self) -> str:
        return self.name or self.run_id

    @property
    def target_label(self) -> str:
        return _as_str(self.target.get("name") or self.target.get("kind"), "unknown")

    def stage(self, name: str) -> StageRecord | None:
        for record in self.stages:
            if record.name == name:
                return record
        return None

    def upsert_stage(self, record: StageRecord) -> None:
        for index, existing in enumerate(self.stages):
            if existing.name == record.name:
                self.stages[index] = record
                return
        self.stages.append(record)

    def add_artifact(self, artifact: RunArtifact) -> None:
        self.artifacts = [a for a in self.artifacts if a.path != artifact.path]
        self.artifacts.append(artifact)

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_schema_version": self.manifest_schema_version,
            "run_id": self.run_id,
            "name": self.name,
            "status": str(self.status),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": self.duration_s,
            "suite_selection": self.suite_selection,
            "suites": list(self.suites),
            "target": self.target,
            "config_path": self.config_path,
            "resolved_config": self.resolved_config,
            "baseline": self.baseline,
            "save_baseline": self.save_baseline,
            "max_regression_pct": self.max_regression_pct,
            "eaiv_version": self.eaiv_version,
            "report_schema_version": self.report_schema_version,
            "git": self.git,
            "host": self.host,
            "stages": [s.to_dict() for s in self.stages],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "summary": self.summary.to_dict(),
            "failure": self.failure.to_dict() if self.failure else None,
            "cancel_reason": self.cancel_reason,
            "provenance": self.provenance,
            "labels": list(self.labels),
            "trigger": self.trigger,
            "pid": self.pid,
            "heartbeat": self.heartbeat,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunManifest:
        """Parse a manifest, defaulting anything missing or malformed."""
        try:
            status = RunStatus(_as_str(payload.get("status"), "pending"))
        except ValueError:
            status = RunStatus.PENDING
        stages = payload.get("stages")
        artifacts = payload.get("artifacts")
        failure = payload.get("failure")
        suites = payload.get("suites")
        labels = payload.get("labels")
        return cls(
            run_id=_as_str(payload.get("run_id")),
            name=_as_str(payload.get("name")),
            status=status,
            created_at=_as_str(payload.get("created_at")),
            started_at=_as_str(payload.get("started_at")),
            completed_at=_as_str(payload.get("completed_at")),
            duration_s=_as_float(payload.get("duration_s")),
            suite_selection=_as_str(payload.get("suite_selection"), "all"),
            suites=[str(s) for s in suites] if isinstance(suites, list) else [],
            target=_as_dict(payload.get("target")),
            config_path=_as_str(payload.get("config_path")),
            resolved_config=_as_dict(payload.get("resolved_config")),
            baseline=_as_str(payload.get("baseline")),
            save_baseline=_as_str(payload.get("save_baseline")),
            max_regression_pct=_as_float(payload.get("max_regression_pct"), 10.0),
            eaiv_version=_as_str(payload.get("eaiv_version"), "unknown"),
            report_schema_version=_as_int(payload.get("report_schema_version")),
            manifest_schema_version=_as_int(
                payload.get("manifest_schema_version"), MANIFEST_SCHEMA_VERSION
            ),
            git=_as_dict(payload.get("git")),
            host=_as_dict(payload.get("host")),
            stages=(
                [StageRecord.from_dict(s) for s in stages if isinstance(s, dict)]
                if isinstance(stages, list)
                else []
            ),
            artifacts=(
                [RunArtifact.from_dict(a) for a in artifacts if isinstance(a, dict)]
                if isinstance(artifacts, list)
                else []
            ),
            summary=RunSummary.from_dict(_as_dict(payload.get("summary"))),
            failure=RunFailure.from_dict(failure) if isinstance(failure, dict) else None,
            cancel_reason=_as_str(payload.get("cancel_reason")),
            provenance=_as_str(payload.get("provenance"), "unknown"),
            labels=[str(x) for x in labels] if isinstance(labels, list) else [],
            trigger=_as_str(payload.get("trigger"), "cli"),
            pid=_as_int(payload.get("pid")),
            heartbeat=_as_str(payload.get("heartbeat")),
        )


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ArtifactKind",
    "RunArtifact",
    "RunFailure",
    "RunManifest",
    "RunStatus",
    "RunSummary",
    "StageRecord",
    "StageStatus",
    "eaiv_version",
    "git_info",
    "host_info",
    "is_valid_run_id",
    "new_run_id",
    "sanitize_component",
]
