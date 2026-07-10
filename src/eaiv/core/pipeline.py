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
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from eaiv.config import Config
from eaiv.core.baseline import BaselineStore
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.regression import RegressionReport, compare_reports, load_report
from eaiv.core.results import AggregateResult

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class StageResult:
    name: str
    status: str  # ok | failed | skipped
    duration_s: float = 0.0
    detail: str = ""


@dataclass
class PipelineResult:
    stages: list[StageResult] = field(default_factory=list)
    results: AggregateResult | None = None
    regression: RegressionReport | None = None

    @property
    def passed(self) -> bool:
        stages_ok = all(s.status != FAILED for s in self.stages)
        suites_ok = self.results is None or self.results.all_passed()
        regression_ok = self.regression is None or self.regression.passed
        return stages_ok and suites_ok and regression_ok


class ValidationPipeline:
    """Build → validate → telemetry → compare → report, as one run."""

    def __init__(
        self,
        cfg: Config,
        report_dir: str = "reports",
        baseline_store: BaselineStore | None = None,
        firmware_dir: str | Path = "firmware",
    ) -> None:
        self.cfg = cfg
        self.report_dir = Path(report_dir)
        self.store = baseline_store if baseline_store is not None else BaselineStore()
        self.firmware_dir = Path(firmware_dir)

    def run(
        self,
        suite: str = "all",
        build_env: str | None = None,
        baseline: str | None = None,
        save_baseline: str | None = None,
        telemetry_s: float = 0.0,
        max_regression_pct: float = 10.0,
    ) -> PipelineResult:
        result = PipelineResult()

        self._stage(result, "build", lambda: self._build(build_env))
        self._stage(result, "validate", lambda: self._validate(result, suite))
        self._stage(result, "telemetry", lambda: self._telemetry(telemetry_s))
        self._stage(result, "compare", lambda: self._compare(result, baseline, max_regression_pct))
        self._stage(result, "save_baseline", lambda: self._save_baseline(result, save_baseline))
        return result

    # -- stages --------------------------------------------------------------

    def _stage(self, result: PipelineResult, name: str, fn) -> None:  # type: ignore[no-untyped-def]
        t0 = time.perf_counter()
        try:
            detail = fn()
        except Exception as e:  # noqa: BLE001 - a stage failure must not abort reporting
            result.stages.append(
                StageResult(name, FAILED, round(time.perf_counter() - t0, 3), str(e))
            )
            return
        status = SKIPPED if detail is None else OK
        result.stages.append(
            StageResult(name, status, round(time.perf_counter() - t0, 3), detail or "")
        )

    def _build(self, build_env: str | None) -> str | None:
        if build_env is None:
            return None
        proc = subprocess.run(
            ["pio", "run", "-e", build_env],
            cwd=self.firmware_dir,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pio run -e {build_env} failed:\n{proc.stdout[-2000:]}")
        return f"built {build_env}"

    def _validate(self, result: PipelineResult, suite: str) -> str:
        orch = Orchestrator(self.cfg, report_dir=str(self.report_dir))
        result.results = orch.run(suite)
        passed = sum(1 for s in result.results if s.passed)
        total = len(result.results.suites)
        if not result.results.all_passed():
            raise RuntimeError(f"{total - passed} of {total} suites failed")
        return f"{passed}/{total} suites passed"

    def _telemetry(self, telemetry_s: float) -> str | None:
        if telemetry_s <= 0:
            return None
        from eaiv.targets import build_target
        from eaiv.telemetry import LiveTelemetryProvider, TelemetryCollector

        collector = TelemetryCollector()
        with build_target(self.cfg["target"]) as target:
            binary = self.cfg["target"].get("binary")
            if binary:
                target.flash(binary)
            collector.ingest(LiveTelemetryProvider(target, telemetry_s, poll_status=True))
        path = collector.to_csv(self.report_dir / "telemetry.csv")
        stats = collector.summary()
        return f"{stats.samples} samples @ {stats.rate_hz} Hz -> {path}"

    def _compare(
        self, result: PipelineResult, baseline: str | None, max_regression_pct: float
    ) -> str | None:
        if baseline is None:
            return None
        base = self.store.load(baseline)
        current = load_report(self.report_dir / "latest.json")
        result.regression = compare_reports(base, current, max_regression_pct=max_regression_pct)
        if not result.regression.passed:
            worst = result.regression.regressions[0]
            raise RuntimeError(
                f"{len(result.regression.regressions)} regression(s) vs {baseline!r}, "
                f"worst: {worst.suite}.{worst.metric} {worst.baseline:g} -> {worst.current:g}"
            )
        return f"no regressions vs {baseline!r} ({len(result.regression.deltas)} metrics)"

    def _save_baseline(self, result: PipelineResult, name: str | None) -> str | None:
        if name is None:
            return None
        if not result.passed:
            raise RuntimeError("refusing to promote a failing run to a baseline")
        path = self.store.save(load_report(self.report_dir / "latest.json"), name)
        return f"promoted to {path}"
