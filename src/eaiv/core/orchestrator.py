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
"""

from __future__ import annotations

from typing import Protocol

from eaiv.benchmarks.memory import MemoryBenchmark
from eaiv.config import Config
from eaiv.core.reporter import Reporter
from eaiv.core.results import AggregateResult, SuiteResult
from eaiv.firmware.tester import FirmwareTester
from eaiv.hil.suite import HILExperiment
from eaiv.plugins import get_registry
from eaiv.plugins.targets import Target
from eaiv.rt_perf.profiler import RTProfiler
from eaiv.sensor_fusion.experiments import FusionExperiment
from eaiv.targets import build_target
from eaiv.tinyml.benchmark import TinyMLBenchmark

__all__ = ["Orchestrator", "SuiteResult", "AggregateResult", "BUILTIN_SUITES"]

BUILTIN_SUITES = ("firmware", "tinyml", "fusion", "hil", "memory", "rt")


class SuiteRunner(Protocol):
    """Structural interface for pluggable suites."""

    def run(self) -> SuiteResult: ...


class Orchestrator:
    """Builds a target once, then runs the requested suites against it.

    Suites that don't need a live target (e.g. sensor_fusion replaying a
    recorded CSV) simply ignore the target argument.
    """

    def __init__(self, cfg: Config, report_dir: str = "reports") -> None:
        self.cfg = cfg
        self.reporter = Reporter(report_dir)

    def run(self, suite: str) -> AggregateResult:
        extra: dict = self.cfg.get("extra_suites", {}) or {}
        known = set(BUILTIN_SUITES) | set(extra) | {"all"}
        if suite not in known:
            raise ValueError(f"Unknown suite: {suite!r}. Available: {sorted(known)}")

        results = AggregateResult()
        target = build_target(self.cfg["target"]) if self._needs_target(suite) else None

        if suite in ("firmware", "all"):
            assert target is not None
            results.add(FirmwareTester(self.cfg["firmware"], target).run())
        if suite in ("tinyml", "all"):
            assert target is not None
            results.add(TinyMLBenchmark(self.cfg["tinyml"], target).run())
        if suite in ("fusion", "all"):
            results.add(FusionExperiment(self.cfg["sensor_fusion"]).run())
        if suite in ("hil", "all"):
            results.add(HILExperiment(self.cfg.get("hil", {})).run())
        if suite in ("memory", "all"):
            results.add(MemoryBenchmark(self.cfg.get("memory", {})).run())
        if suite in ("rt", "all"):
            assert target is not None
            results.add(RTProfiler(self.cfg["rt_perf"], target).run())

        registry = get_registry()
        for name, spec in extra.items():
            if suite not in (name, "all"):
                continue
            runner = registry.create("suite", name, spec or {})
            result = runner.run()  # type: ignore[attr-defined]
            if not isinstance(result, SuiteResult):
                raise TypeError(f"Suite plugin {name!r} returned {type(result)!r}")
            results.add(result)

        self.reporter.publish(results, metadata=self._metadata(target))
        return results

    def _metadata(self, target: Target | None) -> dict:
        """Report metadata that makes results comparable across boards."""
        from importlib.metadata import PackageNotFoundError, version

        try:
            eaiv_version = version("eaiv")
        except PackageNotFoundError:
            eaiv_version = "unknown"

        target_meta: dict = {"kind": self.cfg.get("target", {}).get("kind", "none")}
        if target is not None:
            info = target.info()
            target_meta.update({"name": info.name, "arch": info.arch, "clock_hz": info.clock_hz})
        return {"eaiv_version": eaiv_version, "target": target_meta}

    @staticmethod
    def _needs_target(suite: str) -> bool:
        return suite in ("firmware", "tinyml", "rt", "all")
