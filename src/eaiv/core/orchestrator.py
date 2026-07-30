"""Top-level orchestrator that runs suites and aggregates results.

Built-in suites are wired explicitly (they share the target lifecycle);
external suites register as ``suite`` plugins and are listed in the
config's ``extra_suites`` mapping — no core changes needed:

    extra_suites:
      my_suite: {threshold: 3.0}

    @register_plugin("my_suite", "suite", "My validation suite")
    class MySuite:
        def __init__(self, spec: dict) -> None: ...
        def run(self) -> SuiteResult: ...

Execution is observable: pass a :class:`~eaiv.runs.session.RunSession`
and every suite start, metric, and verdict is emitted as a typed event
and recorded against the run manifest. Callers that pass nothing keep the
original synchronous behaviour exactly.
"""

from __future__ import annotations

from typing import Any, Protocol

from eaiv.benchmarks.memory import MemoryBenchmark
from eaiv.config import Config
from eaiv.core.report_schema import REPORT_SCHEMA_VERSION, file_identity
from eaiv.core.reporter import PublishedReport, Reporter
from eaiv.core.results import AggregateResult, SuiteResult
from eaiv.firmware.tester import FirmwareTester
from eaiv.hil.suite import HILExperiment
from eaiv.plugins import get_registry
from eaiv.plugins.targets import Target
from eaiv.rt_perf.profiler import RTProfiler
from eaiv.runs.models import ArtifactKind, eaiv_version, git_info, host_info
from eaiv.runs.session import RunSession
from eaiv.sensor_fusion.experiments import FusionExperiment
from eaiv.targets import build_target
from eaiv.tinyml.benchmark import TinyMLBenchmark

__all__ = ["BUILTIN_SUITES", "AggregateResult", "Orchestrator", "SuiteResult"]

BUILTIN_SUITES = ("firmware", "tinyml", "fusion", "hil", "memory", "rt")

#: Which config section drives each built-in suite, for the UI and for
#: config validation. ``rt`` reports itself as ``rt_perf``.
SUITE_CONFIG_SECTION = {
    "firmware": "firmware",
    "tinyml": "tinyml",
    "fusion": "sensor_fusion",
    "hil": "hil",
    "memory": "memory",
    "rt": "rt_perf",
}

#: Suites that need a live target connection.
TARGET_SUITES = ("firmware", "tinyml", "rt")


class SuiteRunner(Protocol):
    """Structural interface for pluggable suites."""

    def run(self) -> SuiteResult: ...


class Orchestrator:
    """Builds a target once, then runs the requested suites against it.

    Suites that don't need a live target (e.g. sensor_fusion replaying a
    recorded CSV) simply ignore the target argument.
    """

    def __init__(
        self,
        cfg: Config,
        report_dir: str = "reports",
        session: RunSession | None = None,
        mirror_dir: str | None = None,
        quiet: bool = False,
    ) -> None:
        self.cfg = cfg
        self.report_dir = report_dir
        self.reporter = Reporter(report_dir)
        self.session = session
        self.mirror_dir = mirror_dir
        self.quiet = quiet

    def known_suites(self) -> set[str]:
        extra: dict = self.cfg.get("extra_suites", {}) or {}
        return set(BUILTIN_SUITES) | set(extra) | {"all"}

    def selected_suites(self, suite: str) -> list[str]:
        """Expand a suite selection into the concrete suites that will run."""
        extra: dict = self.cfg.get("extra_suites", {}) or {}
        if suite != "all":
            return [suite]
        return [*BUILTIN_SUITES, *extra]

    def run(self, suite: str) -> AggregateResult:
        known = self.known_suites()
        if suite not in known:
            raise ValueError(f"Unknown suite: {suite!r}. Available: {sorted(known)}")

        results = AggregateResult()
        target = build_target(self.cfg["target"]) if self._needs_target(suite) else None
        try:
            if target is not None and self.session is not None:
                info = target.info()
                self.session.target_connected(
                    {
                        "kind": self.cfg.get("target", {}).get("kind", "none"),
                        "name": info.name,
                        "arch": info.arch,
                        "clock_hz": info.clock_hz,
                        "flash_size_kb": info.flash_size_kb,
                        "ram_size_kb": info.ram_size_kb,
                    }
                )

            builders: dict[str, Any] = {
                "firmware": lambda: FirmwareTester(self.cfg["firmware"], _require(target)).run(),
                "tinyml": lambda: TinyMLBenchmark(self.cfg["tinyml"], _require(target)).run(),
                "fusion": lambda: FusionExperiment(self.cfg["sensor_fusion"]).run(),
                "hil": lambda: HILExperiment(self.cfg.get("hil", {})).run(),
                "memory": lambda: MemoryBenchmark(self.cfg.get("memory", {})).run(),
                "rt": lambda: RTProfiler(self.cfg["rt_perf"], _require(target)).run(),
            }
            for name, builder in builders.items():
                if suite in (name, "all"):
                    self._run_suite(results, name, builder)

            registry = get_registry()
            extra: dict = self.cfg.get("extra_suites", {}) or {}
            for name, spec in extra.items():
                if suite not in (name, "all"):
                    continue

                def _make(name: str = name, spec: Any = spec) -> SuiteResult:
                    runner = registry.create("suite", name, spec or {})
                    result = runner.run()  # type: ignore[attr-defined]
                    if not isinstance(result, SuiteResult):
                        raise TypeError(f"Suite plugin {name!r} returned {type(result)!r}")
                    return result

                self._run_suite(results, name, _make)
        finally:
            if target is not None:
                target.close()

        self.publish(results, target)
        return results

    def publish(self, results: AggregateResult, target: Target | None = None) -> PublishedReport:
        """Write report artifacts and register them with the run session."""
        run_meta: dict[str, Any] = {}
        if self.session is not None:
            run_meta = {
                "run_id": self.session.manifest.run_id,
                "name": self.session.manifest.name,
                "trigger": self.session.manifest.trigger,
            }
        published = self.reporter.publish(
            results,
            metadata=self._metadata(target),
            run=run_meta,
            mirror_dir=self.mirror_dir,
            quiet=self.quiet,
        )
        if self.session is not None:
            for key, kind, label in (
                ("run_json", ArtifactKind.REPORT, "report.json"),
                ("run_md", ArtifactKind.REPORT, "report.md"),
                ("run_csv", ArtifactKind.REPORT, "report.csv"),
                ("run_html", ArtifactKind.REPORT, "report.html"),
            ):
                path = published.paths.get(key)
                if path is not None:
                    self.session.artifact(label, path, kind)
        return published

    # -- internals ---------------------------------------------------------

    def _run_suite(self, results: AggregateResult, name: str, factory: Any) -> None:
        """Run one suite, emitting progress and recording its verdict."""
        if self.session is not None:
            self.session.check_cancelled()
            self.session.progress("validate", f"running suite {name}", suite=name)
        result = factory()
        results.add(result)
        if self.session is not None:
            self.session.suite_result(result.name, result.passed, result.metrics, result.notes)
            for metric, value in result.metrics.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    declared = (result.metric_meta or {}).get(metric, {})
                    self.session.metric(result.name, metric, value, declared.get("unit", ""))

    def _metadata(self, target: Target | None) -> dict:
        """Report metadata that makes a run reproducible and comparable."""
        target_meta: dict[str, Any] = {"kind": self.cfg.get("target", {}).get("kind", "none")}
        if target is not None:
            info = target.info()
            target_meta.update(
                {
                    "name": info.name,
                    "arch": info.arch,
                    "clock_hz": info.clock_hz,
                    "flash_size_kb": info.flash_size_kb,
                    "ram_size_kb": info.ram_size_kb,
                }
            )
        registry = get_registry()
        meta: dict[str, Any] = {
            "eaiv_version": eaiv_version(),
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "target": target_meta,
            "host": host_info(),
            "git": git_info(),
            "config": self.cfg.raw,
            "thresholds": self.thresholds(),
            "inputs": self._inputs(),
            "plugins": {f"{p.plugin_type}:{p.name}": p.version for p in registry.list_plugins()},
            "baseline": "",
        }
        if self.session is not None:
            meta["baseline"] = self.session.manifest.baseline
        return meta

    def _inputs(self) -> dict[str, Any]:
        """Identity (and hash) of the model, dataset, and firmware used."""
        inputs: dict[str, Any] = {}
        model = self.cfg.get("tinyml", {}).get("model")
        if model:
            inputs["model"] = file_identity(model)
        firmware = self.cfg.get("target", {}).get("binary")
        if firmware:
            inputs["firmware"] = file_identity(firmware)
        dataset = self.cfg.get("sensor_fusion", {}).get("source")
        if dataset:
            inputs["dataset"] = file_identity(dataset)
        hil_dataset = self.cfg.get("hil", {}).get("source")
        if hil_dataset and hil_dataset != dataset:
            inputs["hil_dataset"] = file_identity(hil_dataset)
        return inputs

    def thresholds(self) -> dict[str, Any]:
        """Every configured gate, flattened for the report and the UI."""
        out: dict[str, Any] = {}
        memory = self.cfg.get("memory", {}) or {}
        for key in ("max_rom_kb", "max_ram_kb"):
            if memory.get(key) is not None:
                out[f"memory.{key}"] = memory[key]
        hil = self.cfg.get("hil", {}) or {}
        if hil.get("max_faulted_rmse_deg") is not None:
            out["hil.max_faulted_rmse_deg"] = hil["max_faulted_rmse_deg"]
        fusion = self.cfg.get("sensor_fusion", {}) or {}
        out["sensor_fusion.max_rmse_deg"] = fusion.get("max_rmse_deg", 10.0)
        for task in (self.cfg.get("rt_perf", {}) or {}).get("task_set", []) or []:
            if not isinstance(task, dict) or "name" not in task:
                continue
            for key in ("deadline_ms", "wcet_budget_ms", "period_ms"):
                if task.get(key) is not None:
                    out[f"rt_perf.{task['name']}.{key}"] = task[key]
        return out

    @staticmethod
    def _needs_target(suite: str) -> bool:
        return suite in (*TARGET_SUITES, "all")


def _require(target: Target | None) -> Target:
    if target is None:  # pragma: no cover - guarded by _needs_target
        raise RuntimeError("This suite requires a target but none was built")
    return target
