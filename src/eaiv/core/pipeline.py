"""End-to-end hardware validation pipeline.

Composes the existing building blocks into the canonical workflow —

    build firmware -> flash + validate -> collect telemetry
        -> compare against baseline -> (optionally) promote baseline

— with one result object recording every stage. The ``Target`` plugin is
the hardware runner: the same pipeline drives serial devices, J-Link,
QEMU, or the simulator purely through config. Flashing happens inside the
firmware suite (each attempt re-flashes), so it is not a separate stage.

    pipeline = ValidationPipeline(load_config("configs/sim.yaml"))
    result = pipeline.run(baseline="release-0.3", telemetry_s=2.0)
    sys.exit(0 if result.passed else 1)

Pass ``run_store=`` (or a ready-made ``session=``) and the same call
becomes observable and resumable: every stage emits typed events, the
manifest is written atomically as the run progresses, and the run can be
cancelled from another process. Callers that pass neither get exactly the
behaviour they had before.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable

from eaiv.config import Config
from eaiv.core.baseline import BaselineStore
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.regression import RegressionReport, compare_reports, load_report
from eaiv.core.report_schema import REPORT_SCHEMA_VERSION, overall_provenance
from eaiv.core.results import AggregateResult
from eaiv.runs.cancel import CancellationToken, RunCancelled
from eaiv.runs.events import EventLevel, EventSink
from eaiv.runs.models import (
    ArtifactKind,
    RunFailure,
    RunManifest,
    RunStatus,
    RunSummary,
    StageStatus,
    git_info,
    host_info,
    new_run_id,
    sanitize_component,
)
from eaiv.runs.session import RunSession
from eaiv.runs.store import RunStore, atomic_write_text

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

STAGES = ("build", "validate", "telemetry", "compare", "save_baseline")

#: Hard ceiling on a firmware build so a hung toolchain cannot wedge CI.
DEFAULT_BUILD_TIMEOUT_S = 900.0

#: PlatformIO environment names are used as command arguments; keep them
#: to the character set PlatformIO itself allows.
_SAFE_ENV_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


@dataclass
class StageResult:
    name: str
    status: str  # ok | failed | skipped | cancelled
    duration_s: float = 0.0
    detail: str = ""
    failure: RunFailure | None = None


@dataclass
class PipelineResult:
    stages: list[StageResult] = field(default_factory=list)
    results: AggregateResult | None = None
    regression: RegressionReport | None = None
    #: Populated when the pipeline ran with a run store or session.
    manifest: RunManifest | None = None
    cancelled: bool = False

    @property
    def passed(self) -> bool:
        stages_ok = all(s.status != FAILED for s in self.stages)
        suites_ok = self.results is None or self.results.all_passed()
        regression_ok = self.regression is None or self.regression.passed
        return stages_ok and suites_ok and regression_ok and not self.cancelled

    @property
    def status(self) -> RunStatus:
        if self.cancelled:
            return RunStatus.CANCELLED
        return RunStatus.PASSED if self.passed else RunStatus.FAILED

    def stage(self, name: str) -> StageResult | None:
        return next((s for s in self.stages if s.name == name), None)


class ValidationPipeline:
    """Build → validate → telemetry → compare → report, as one run."""

    def __init__(
        self,
        cfg: Config,
        report_dir: str = "reports",
        baseline_store: BaselineStore | None = None,
        firmware_dir: str | Path = "firmware",
        run_store: RunStore | None = None,
        events: EventSink | None = None,
        session: RunSession | None = None,
        cancel: CancellationToken | None = None,
        config_path: str = "",
    ) -> None:
        self.cfg = cfg
        self.report_dir = Path(report_dir)
        self.store = baseline_store if baseline_store is not None else BaselineStore()
        self.firmware_dir = Path(firmware_dir)
        self.run_store = run_store
        self.events = events
        self.session = session
        self.cancel = cancel
        self.config_path = config_path

    # -- run ---------------------------------------------------------------

    def run(
        self,
        suite: str = "all",
        build_env: str | None = None,
        baseline: str | None = None,
        save_baseline: str | None = None,
        telemetry_s: float = 0.0,
        max_regression_pct: float = 10.0,
        run_name: str = "",
        trigger: str = "cli",
    ) -> PipelineResult:
        result = PipelineResult()
        session = self.session or self._build_session(
            suite=suite,
            baseline=baseline,
            save_baseline=save_baseline,
            max_regression_pct=max_regression_pct,
            run_name=run_name,
            trigger=trigger,
        )
        result.manifest = session.manifest
        session.start()
        self._write_resolved_config(session)

        try:
            self._stage(result, session, "build", lambda: self._build(session, build_env))
            self._stage(result, session, "validate", lambda: self._validate(result, session, suite))
            self._stage(
                result, session, "telemetry", lambda: self._telemetry(session, telemetry_s)
            )
            self._stage(
                result,
                session,
                "compare",
                lambda: self._compare(result, session, baseline, max_regression_pct),
            )
            self._stage(
                result,
                session,
                "save_baseline",
                lambda: self._save_baseline(result, session, save_baseline),
            )
        except RunCancelled as exc:
            result.cancelled = True
            session.manifest.cancel_reason = exc.reason
            for name in STAGES:
                if result.stage(name) is None:
                    result.stages.append(StageResult(name, str(StageStatus.CANCELLED), 0.0, ""))

        self._finalize(result, session)
        return result

    # -- session -----------------------------------------------------------

    def _build_session(
        self,
        suite: str,
        baseline: str | None,
        save_baseline: str | None,
        max_regression_pct: float,
        run_name: str,
        trigger: str,
    ) -> RunSession:
        target_kind = str((self.cfg.get("target", {}) or {}).get("kind", "none"))
        name = run_name or f"{target_kind}/{suite}"
        manifest = RunManifest(
            run_id=new_run_id(sanitize_component(run_name or f"{target_kind}-{suite}")),
            name=name,
            suite_selection=suite,
            target={"kind": target_kind},
            config_path=self.config_path,
            resolved_config=self.cfg.raw,
            baseline=baseline or "",
            save_baseline=save_baseline or "",
            max_regression_pct=max_regression_pct,
            report_schema_version=REPORT_SCHEMA_VERSION,
            git=git_info(),
            host=host_info(),
            trigger=trigger,
        )
        return RunSession(manifest, store=self.run_store, sink=self.events, cancel=self.cancel)

    def _write_resolved_config(self, session: RunSession) -> None:
        directory = session.run_dir
        if directory is None:
            return
        import yaml

        path = directory / "resolved-config.yaml"
        try:
            atomic_write_text(path, yaml.safe_dump(self.cfg.raw, sort_keys=False))
        except (OSError, yaml.YAMLError) as exc:
            session.log(f"could not write resolved config: {exc}", level=EventLevel.WARNING)
            return
        session.artifact(
            "resolved-config.yaml",
            path,
            ArtifactKind.CONFIG,
            "Configuration after inheritance, exactly as this run used it",
        )

    # -- stages ------------------------------------------------------------

    def _stage(
        self,
        result: PipelineResult,
        session: RunSession,
        name: str,
        fn: Callable[[], str | None],
    ) -> None:
        """Run one stage, recording status, timing, and failure detail.

        Cancellation is checked between stages and propagates out of the
        pipeline; every other exception is captured so later stages (and
        reporting) still happen, exactly as before.
        """
        session.check_cancelled()
        t0 = time.perf_counter()
        with session.stage(name) as record:
            try:
                detail = fn()
            except RunCancelled:
                record.status = StageStatus.CANCELLED
                record.detail = "cancelled"
                result.stages.append(
                    StageResult(name, str(StageStatus.CANCELLED), _elapsed(t0), "cancelled")
                )
                raise
            except Exception as exc:  # noqa: BLE001 - a stage failure must not abort reporting
                failure = RunFailure.from_exception(exc, stage=name, hint=_hint_for(exc, name))
                record.status = StageStatus.FAILED
                record.detail = str(exc)
                record.failure = failure
                session.log(f"{name} failed: {exc}", stage=name, level=EventLevel.ERROR)
                result.stages.append(StageResult(name, FAILED, _elapsed(t0), str(exc), failure))
                return
            record.status = StageStatus.SKIPPED if detail is None else StageStatus.OK
            record.detail = detail or ""
            result.stages.append(
                StageResult(
                    name,
                    SKIPPED if detail is None else OK,
                    _elapsed(t0),
                    detail or "",
                )
            )

    def _build(self, session: RunSession, build_env: str | None) -> str | None:
        if build_env is None:
            return None
        if not set(build_env) <= _SAFE_ENV_CHARS:
            raise ValueError(
                f"Invalid PlatformIO environment name {build_env!r}: "
                "expected letters, digits, '_', '-' or '.'"
            )
        if not self.firmware_dir.is_dir():
            raise FileNotFoundError(f"Firmware directory not found: {self.firmware_dir}")
        session.progress("build", f"pio run -e {build_env}", env=build_env)
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, validated env name, no shell
                ["pio", "run", "-e", build_env],
                cwd=self.firmware_dir,
                capture_output=True,
                text=True,
                timeout=DEFAULT_BUILD_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"pio run -e {build_env} exceeded {DEFAULT_BUILD_TIMEOUT_S:.0f}s and was killed"
            ) from exc
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "PlatformIO ('pio') is not on PATH. Install it with 'pip install platformio', "
                "or drop --build-env to validate a pre-built binary."
            ) from exc
        if proc.returncode != 0:
            tail = (proc.stdout or "")[-2000:] or (proc.stderr or "")[-2000:]
            raise RuntimeError(f"pio run -e {build_env} failed:\n{tail}")
        return f"built {build_env}"

    def _validate(self, result: PipelineResult, session: RunSession, suite: str) -> str:
        orch = Orchestrator(
            self.cfg,
            report_dir=str(self.report_dir),
            session=session,
            mirror_dir=str(session.run_dir) if session.run_dir else None,
        )
        result.results = orch.run(suite)
        passed = sum(1 for s in result.results if s.passed)
        total = len(result.results.suites)
        if not result.results.all_passed():
            failing = [s.name for s in result.results if not s.passed]
            raise RuntimeError(f"{total - passed} of {total} suites failed: {', '.join(failing)}")
        return f"{passed}/{total} suites passed"

    def _telemetry(self, session: RunSession, telemetry_s: float) -> str | None:
        if telemetry_s <= 0:
            return None
        from eaiv.targets import build_target
        from eaiv.telemetry import LiveTelemetryProvider, TelemetryCollector

        session.check_cancelled()
        collector = TelemetryCollector()
        with build_target(self.cfg["target"]) as target:
            binary = self.cfg["target"].get("binary")
            if binary:
                target.flash(binary)
            session.progress("telemetry", f"capturing {telemetry_s:g}s of telemetry")
            collector.ingest(LiveTelemetryProvider(target, telemetry_s, poll_status=True))
        session.check_cancelled()
        path = collector.to_csv(self.report_dir / "telemetry.csv")
        if session.run_dir is not None:
            run_copy = session.run_dir / "telemetry.csv"
            shutil.copyfile(path, run_copy)
            session.artifact(
                "telemetry.csv", run_copy, ArtifactKind.TELEMETRY, "Captured device telemetry"
            )
        stats = collector.summary()
        return f"{stats.samples} samples @ {stats.rate_hz} Hz -> {path}"

    def _compare(
        self,
        result: PipelineResult,
        session: RunSession,
        baseline: str | None,
        max_regression_pct: float,
    ) -> str | None:
        if baseline is None:
            return None
        base = self.store.load(baseline)
        current = load_report(self.report_dir / "latest.json")
        result.regression = compare_reports(base, current, max_regression_pct=max_regression_pct)
        counts = result.regression.counts()
        session.progress(
            "compare",
            f"{counts['regressed']} regressed, {counts['improved']} improved vs {baseline!r}",
            **counts,
        )
        if not result.regression.passed:
            worst = result.regression.regressions[0]
            raise RuntimeError(
                f"{len(result.regression.regressions)} regression(s) vs {baseline!r}, "
                f"worst: {worst.suite}.{worst.metric} {worst.baseline:g} -> {worst.current:g}"
            )
        return f"no regressions vs {baseline!r} ({len(result.regression.deltas)} metrics)"

    def _save_baseline(
        self, result: PipelineResult, session: RunSession, name: str | None
    ) -> str | None:
        if name is None:
            return None
        if not result.passed:
            raise RuntimeError("refusing to promote a failing run to a baseline")
        path = self.store.save(load_report(self.report_dir / "latest.json"), name)
        session.artifact(f"baseline:{name}", path, ArtifactKind.BASELINE, "Promoted baseline")
        return f"promoted to {path}"

    # -- completion --------------------------------------------------------

    def _finalize(self, result: PipelineResult, session: RunSession) -> None:
        """Record the summary and close the run out with a final status."""
        manifest = session.manifest
        suites = list(result.results or [])
        counts = result.regression.counts() if result.regression else {}
        worst = None
        if result.regression and result.regression.regressions:
            top = max(result.regression.regressions, key=lambda d: abs(d.change_pct))
            worst = {
                "suite": top.suite,
                "metric": top.metric,
                "baseline": top.baseline,
                "current": top.current,
                "change_pct": top.change_pct,
            }
        manifest.summary = RunSummary(
            total_suites=len(suites),
            passed_suites=sum(1 for s in suites if s.passed),
            failed_suite_names=[s.name for s in suites if not s.passed],
            metrics_recorded=sum(len(s.metrics) for s in suites),
            regressions=counts.get("regressed", 0),
            improvements=counts.get("improved", 0),
            worst_regression=worst,
            all_passed=bool(result.results and result.results.all_passed()),
        )
        manifest.suites = [s.name for s in suites]
        report_path = self.report_dir / "latest.json"
        if report_path.exists():
            try:
                manifest.provenance = overall_provenance(load_report(report_path))
            except (OSError, ValueError):
                manifest.provenance = "unknown"

        failure = next((s.failure for s in result.stages if s.failure is not None), None)
        session.finish(result.status, failure)


def _elapsed(t0: float) -> float:
    return round(time.perf_counter() - t0, 3)


def _hint_for(exc: BaseException, stage: str) -> str:
    """Actionable next step for the most common stage failures."""
    if isinstance(exc, FileNotFoundError):
        return "Check the paths in your configuration: `eaiv config validate <config>`."
    if isinstance(exc, TimeoutError):
        return "Increase the stage timeout or check that the target is responding."
    if stage == "compare":
        return "Inspect the regression on the Compare page, or raise --max-regression-pct."
    if stage == "save_baseline":
        return "Baselines are only promoted from fully passing runs; fix the failures first."
    if stage == "validate":
        return "Open the failing suite on the Results page for evidence and next actions."
    return ""


__all__ = [
    "FAILED",
    "OK",
    "SKIPPED",
    "STAGES",
    "PipelineResult",
    "StageResult",
    "ValidationPipeline",
]
