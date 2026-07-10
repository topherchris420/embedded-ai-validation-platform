"""Top-level orchestrator that runs suites and aggregates results."""

from __future__ import annotations

from eaiv.config import Config
from eaiv.core.reporter import Reporter
from eaiv.core.results import AggregateResult, SuiteResult
from eaiv.firmware.tester import FirmwareTester
from eaiv.hil.suite import HILExperiment
from eaiv.rt_perf.profiler import RTProfiler
from eaiv.sensor_fusion.experiments import FusionExperiment
from eaiv.targets import build_target
from eaiv.tinyml.benchmark import TinyMLBenchmark

__all__ = ["Orchestrator", "SuiteResult", "AggregateResult"]


class Orchestrator:
    """Builds a target once, then runs the requested suites against it.

    Suites that don't need a live target (e.g. sensor_fusion replaying a
    recorded CSV) simply ignore the target argument.
    """

    def __init__(self, cfg: Config, report_dir: str = "reports") -> None:
        self.cfg = cfg
        self.reporter = Reporter(report_dir)

    def run(self, suite: str) -> AggregateResult:
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
        if suite in ("rt", "all"):
            assert target is not None
            results.add(RTProfiler(self.cfg["rt_perf"], target).run())

        self.reporter.publish(results)
        return results

    @staticmethod
    def _needs_target(suite: str) -> bool:
        return suite in ("firmware", "tinyml", "rt", "all")
