"""A complete, honest, hardware-free validation experience.

``eaiv demo`` produces three real runs against the simulated target: a
clean run promoted to a baseline, a second run gated against it, and a
third run whose sensor stream is degraded far enough that the fusion
filter genuinely leaves its error envelope. Nothing is faked — the same
orchestrator, the same suites, the same report writer. The failure is a
real threshold crossing produced by real (seeded, reproducible) fault
injection, which is why the resulting diagnosis is worth reading.

Every metric is labelled ``simulated`` or ``mock`` in the report, so the
demo can never be mistaken for hardware evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eaiv.config import Config, deep_merge
from eaiv.configspec.presets import MissionStore, get_preset
from eaiv.core.baseline import BaselineStore
from eaiv.core.pipeline import PipelineResult, ValidationPipeline
from eaiv.runs.events import EventSink
from eaiv.runs.store import RunStore

DEMO_BASELINE_NAME = "demo-baseline"

#: Fault severity for the third run. Chosen because it reliably pushes
#: the Madgwick filter past the 15° envelope on the committed dataset —
#: a real threshold crossing, not a hard-coded "FAIL".
_DEMO_FAULT_NOISE_STD = 2.0


@dataclass
class DemoRun:
    run_id: str
    name: str
    passed: bool
    summary: str


@dataclass
class DemoResult:
    """What the demo produced, for the CLI and the dashboard to report."""

    runs: list[DemoRun] = field(default_factory=list)
    baseline: str = DEMO_BASELINE_NAME
    report_dir: str = "reports"
    mission_path: str = ""
    dataset: str = ""

    @property
    def ok(self) -> bool:
        """The demo worked when it produced the intended pass/pass/fail arc."""
        return len(self.runs) == 3 and [r.passed for r in self.runs] == [True, True, False]


def _demo_config(dataset: str) -> dict[str, Any]:
    """A simulator mission exercising every hardware-free suite."""
    base = get_preset("sim-release-gate").build("sim")
    return deep_merge(
        base,
        {
            "sensor_fusion": {"source": dataset, "algorithm": "ekf", "max_rmse_deg": 10.0},
            "hil": {
                "source": dataset,
                "algorithm": "madgwick",
                "params": {"beta": 0.2},
                "faults": [
                    {"kind": "noise", "std": 0.05, "seed": 1},
                    {"kind": "packet_loss", "probability": 0.02, "seed": 1},
                ],
                "max_faulted_rmse_deg": 15.0,
            },
            "tinyml": {"runtime": "mock", "iterations": 25, "warmup": 3},
            "rt_perf": {"duration_s": 1.0},
            "memory": {"require": False},
        },
    )


def _degraded_config(dataset: str) -> dict[str, Any]:
    """The same mission with a sensor stream degraded past the envelope."""
    return deep_merge(
        _demo_config(dataset),
        {
            "hil": {
                "faults": [
                    {"kind": "noise", "std": _DEMO_FAULT_NOISE_STD, "seed": 1},
                    {"kind": "packet_loss", "probability": 0.08, "seed": 1},
                    {"kind": "outage", "start_s": 4.0, "duration_s": 1.0},
                ],
            }
        },
    )


def default_dataset(root: str | Path = "datasets") -> str:
    """A committed replay dataset, or the empty string when none exists."""
    directory = Path(root)
    preferred = directory / "imu" / "imu_run1.csv"
    if preferred.exists():
        return str(preferred)
    candidates = sorted(directory.glob("**/*.csv")) if directory.exists() else []
    return str(candidates[0]) if candidates else ""


def ensure_demo_dataset(root: str | Path = "datasets") -> str:
    """Return a replay dataset path, generating one if the repo has none."""
    existing = default_dataset(root)
    if existing:
        return existing
    from eaiv.datasets import generate_imu_trajectory, imu_metadata, write_imu_csv, write_metadata

    target = Path(root) / "imu" / "demo_imu.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    samples = generate_imu_trajectory(duration_s=20.0, rate_hz=100.0, profile="gentle", seed=0)
    path = write_imu_csv(samples, target)
    write_metadata(
        imu_metadata(
            name=path.stem,
            description="Synthetic IMU log generated for the eaiv demo",
            sampling_rate_hz=100.0,
            generator={"profile": "gentle", "seed": 0, "duration_s": 20.0, "rate_hz": 100.0},
        ),
        path,
    )
    return str(path)


def _summarize(result: PipelineResult) -> str:
    if result.results is None:
        return "no suites executed"
    passed = sum(1 for s in result.results if s.passed)
    total = len(result.results.suites)
    failing = [s.name for s in result.results if not s.passed]
    if failing:
        return f"{passed}/{total} suites passed; failing: {', '.join(failing)}"
    return f"{passed}/{total} suites passed"


def run_demo(
    report_dir: str | Path = "reports",
    baseline_dir: str | Path = "baselines",
    dataset_dir: str | Path = "datasets",
    mission_dir: str | Path | None = "missions",
    events: EventSink | None = None,
    quiet: bool = True,
) -> DemoResult:
    """Execute the three-run demo and return what it produced."""
    dataset = ensure_demo_dataset(dataset_dir)
    store = RunStore(report_dir)
    baselines = BaselineStore(baseline_dir)
    result = DemoResult(report_dir=str(report_dir), dataset=dataset)

    scenarios = (
        ("Demo · reference run", _demo_config(dataset), DEMO_BASELINE_NAME, None),
        ("Demo · candidate build", _demo_config(dataset), None, DEMO_BASELINE_NAME),
        ("Demo · degraded sensors", _degraded_config(dataset), None, DEMO_BASELINE_NAME),
    )

    mission_path = ""
    if mission_dir is not None:
        missions = MissionStore(mission_dir)
        mission_path = str(
            missions.save(
                "demo-mission",
                _demo_config(dataset),
                suite="all",
                baseline=DEMO_BASELINE_NAME,
                preset="sim-release-gate",
                title="Simulated release gate (demo)",
            )
        )
    result.mission_path = mission_path

    for name, raw, save_baseline, baseline in scenarios:
        pipeline = ValidationPipeline(
            Config(raw),
            report_dir=str(report_dir),
            baseline_store=baselines,
            run_store=store,
            events=events,
            config_path=mission_path,
        )
        outcome = pipeline.run(
            suite="all",
            baseline=baseline,
            save_baseline=save_baseline,
            # A gate that would fail on mock-runtime timing jitter teaches
            # nothing; the demo's regression story is the fault injection.
            max_regression_pct=200.0,
            run_name=name,
            trigger="demo",
        )
        manifest = outcome.manifest
        result.runs.append(
            DemoRun(
                run_id=manifest.run_id if manifest else "",
                name=name,
                passed=outcome.passed,
                summary=_summarize(outcome),
            )
        )
    return result


__all__ = [
    "DEMO_BASELINE_NAME",
    "DemoResult",
    "DemoRun",
    "default_dataset",
    "ensure_demo_dataset",
    "run_demo",
]
