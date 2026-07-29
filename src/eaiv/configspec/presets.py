"""Mission presets: ready-to-run validation intents.

A preset is a starting point, not a straitjacket — it fills the mission
builder with a configuration that already makes sense for a stated goal
("does this firmware still boot?", "is this model fast enough to ship?"),
which the engineer then edits. Presets that need no hardware are marked
as such, so the platform can always offer at least one mission that runs
on a laptop with nothing plugged in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from eaiv.config import deep_merge
from eaiv.configspec.schema import default_config, set_nested


@dataclass(frozen=True)
class MissionPreset:
    """A named validation intent with a starting configuration."""

    id: str
    title: str
    summary: str
    suite: str = "all"
    target_kind: str = "sim"
    telemetry_s: float = 0.0
    max_regression_pct: float = 10.0
    requires_hardware: bool = False
    #: Deep-merged over the schema defaults for ``target_kind``.
    overlay: dict[str, Any] = field(default_factory=dict)
    #: What this mission actually tells you, in the engineer's words.
    answers: tuple[str, ...] = ()

    def build(self, target_kind: str | None = None) -> dict[str, Any]:
        """Full configuration mapping for this preset."""
        kind = target_kind or self.target_kind
        base = default_config(kind)
        merged = deep_merge(base, self.overlay)
        set_nested(merged, "target.kind", kind)
        return merged


_IMU_DATASET = "datasets/imu/imu_run1.csv"

PRESETS: tuple[MissionPreset, ...] = (
    MissionPreset(
        id="sim-smoke",
        title="Simulator smoke test",
        summary="Boot the simulated device and confirm the firmware protocol still works.",
        suite="firmware",
        target_kind="sim",
        answers=("Does the firmware still boot and report a verdict?",),
        overlay={
            "target": {"sim": {"telemetry_lines": 25}},
            "firmware": {"timeout_s": 2.0, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
        },
    ),
    MissionPreset(
        id="sim-release-gate",
        title="Full simulated release gate",
        summary=(
            "Every suite against the simulated device, with telemetry capture and a "
            "regression gate — the hardware-free equivalent of the CI merge gate."
        ),
        suite="all",
        target_kind="sim",
        telemetry_s=2.0,
        answers=(
            "Would this change pass CI?",
            "Did anything regress against the baseline?",
        ),
        overlay={
            "target": {"sim": {"telemetry_lines": 200}},
            "firmware": {"timeout_s": 2.0, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
            "tinyml": {"runtime": "mock", "iterations": 40, "warmup": 5},
            "sensor_fusion": {"source": _IMU_DATASET, "algorithm": "ekf"},
            "hil": {
                "source": _IMU_DATASET,
                "algorithm": "madgwick",
                "params": {"beta": 0.2},
                "faults": [
                    {"kind": "noise", "std": 0.05},
                    {"kind": "packet_loss", "probability": 0.02, "seed": 1},
                ],
            },
            "rt_perf": {
                "task_set": [
                    {
                        "name": "control_loop",
                        "period_ms": 5,
                        "deadline_ms": 5,
                        "wcet_budget_ms": 4,
                    },
                    {
                        "name": "inference",
                        "period_ms": 100,
                        "deadline_ms": 100,
                        "wcet_budget_ms": 80,
                    },
                ],
                "duration_s": 2.0,
            },
        },
    ),
    MissionPreset(
        id="firmware-only",
        title="Firmware-only validation",
        summary="Flash a board over serial and watch the boot output for a verdict.",
        suite="firmware",
        target_kind="serial",
        requires_hardware=True,
        answers=("Does this build boot on real hardware?",),
        overlay={
            "target": {"serial": {"port": "/dev/ttyACM0", "baud": 115200}},
            "firmware": {"timeout_s": 30.0, "retries": 2},
        },
    ),
    MissionPreset(
        id="tinyml-benchmark",
        title="TinyML performance benchmark",
        summary=(
            "Latency distribution, throughput, startup cost, and output stability for one "
            "model, measured on the host runtime."
        ),
        suite="tinyml",
        target_kind="sim",
        answers=(
            "How fast is this model, and how heavy is its tail?",
            "Is its output numerically reproducible?",
        ),
        overlay={"tinyml": {"iterations": 200, "warmup": 20, "runtime": "mock"}},
    ),
    MissionPreset(
        id="fusion-accuracy",
        title="Sensor-fusion accuracy study",
        summary="Score a fusion filter against ground-truth orientation on a replay dataset.",
        suite="fusion",
        target_kind="sim",
        answers=(
            "How much orientation error does this filter accumulate?",
            "Does a different algorithm do better on the same data?",
        ),
        overlay={
            "sensor_fusion": {
                "source": _IMU_DATASET,
                "algorithm": "ekf",
                "max_rmse_deg": 10.0,
            }
        },
    ),
    MissionPreset(
        id="hil-robustness",
        title="HIL robustness test",
        summary="Inject noise, packet loss, jitter, and outages, and measure the damage.",
        suite="hil",
        target_kind="sim",
        answers=(
            "How much accuracy is lost under degraded sensors?",
            "Does the filter stay inside its error budget when data goes missing?",
        ),
        overlay={
            "hil": {
                "source": _IMU_DATASET,
                "algorithm": "madgwick",
                "params": {"beta": 0.2},
                "faults": [
                    {"kind": "noise", "std": 0.05},
                    {"kind": "packet_loss", "probability": 0.05, "seed": 1},
                    {"kind": "jitter", "std_s": 0.002},
                    {"kind": "outage", "start_s": 4.0, "duration_s": 0.5},
                ],
                "max_faulted_rmse_deg": 15.0,
            }
        },
    ),
    MissionPreset(
        id="rt-deadlines",
        title="Real-time deadline validation",
        summary="Profile periodic tasks for WCET, release jitter, and deadline misses.",
        suite="rt",
        target_kind="sim",
        answers=(
            "Did any task miss its deadline?",
            "How much WCET headroom is left before it will?",
        ),
        overlay={
            "rt_perf": {
                "task_set": [
                    {"name": "control_loop", "period_ms": 5, "deadline_ms": 5, "wcet_budget_ms": 4},
                    {
                        "name": "inference",
                        "period_ms": 100,
                        "deadline_ms": 100,
                        "wcet_budget_ms": 80,
                    },
                ],
                "duration_s": 5.0,
            }
        },
    ),
    MissionPreset(
        id="custom",
        title="Custom mission",
        summary="Start from schema defaults and configure everything yourself.",
        suite="all",
        target_kind="sim",
        answers=("Whatever you configure it to answer.",),
    ),
)

PRESETS_BY_ID: dict[str, MissionPreset] = {p.id: p for p in PRESETS}

DEFAULT_PRESET_ID = "sim-release-gate"


def get_preset(preset_id: str) -> MissionPreset:
    try:
        return PRESETS_BY_ID[preset_id]
    except KeyError:
        raise KeyError(
            f"Unknown preset {preset_id!r}. Available: {', '.join(PRESETS_BY_ID)}"
        ) from None


def hardware_free_presets() -> list[MissionPreset]:
    return [p for p in PRESETS if not p.requires_hardware]


# -- saved missions --------------------------------------------------------


@dataclass(frozen=True)
class MissionInfo:
    """Summary row for a saved mission file."""

    name: str
    path: Path
    title: str
    suite: str
    target_kind: str
    baseline: str
    preset: str
    saved_at: str


class MissionStore:
    """Saved missions: a config file plus the intent that produced it.

    A mission is an ordinary eaiv config — ``eaiv run --config`` accepts
    it directly — with an extra ``mission:`` block recording the suite
    selection, baseline, and preset so the dashboard can reopen it exactly
    as it was saved.
    """

    def __init__(self, root: str | Path = "missions") -> None:
        self.root = Path(root)

    def path(self, name: str) -> Path:
        from eaiv.runs.models import sanitize_component

        clean = sanitize_component(name)
        if not clean:
            raise ValueError(f"Invalid mission name: {name!r}")
        return self.root / f"{clean}.yaml"

    def save(
        self,
        name: str,
        config: dict[str, Any],
        suite: str = "all",
        baseline: str = "",
        telemetry_s: float = 0.0,
        max_regression_pct: float = 10.0,
        preset: str = "",
        title: str = "",
    ) -> Path:
        payload = {k: v for k, v in config.items() if k != "mission"}
        payload["mission"] = {
            "name": name,
            "title": title or name,
            "preset": preset,
            "suite": suite,
            "baseline": baseline,
            "telemetry_s": telemetry_s,
            "max_regression_pct": max_regression_pct,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return path

    def load(self, name: str) -> dict[str, Any]:
        path = self.path(name)
        if not path.exists():
            raise FileNotFoundError(f"No mission {name!r} in {self.root}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Mission {path} is not a mapping")
        return data

    def list(self) -> list[MissionInfo]:
        if not self.root.exists():
            return []
        infos: list[MissionInfo] = []
        for path in sorted(self.root.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict):
                continue
            mission = data.get("mission") or {}
            infos.append(
                MissionInfo(
                    name=str(mission.get("name", path.stem)),
                    path=path,
                    title=str(mission.get("title", path.stem)),
                    suite=str(mission.get("suite", "all")),
                    target_kind=str((data.get("target") or {}).get("kind", "?")),
                    baseline=str(mission.get("baseline", "")),
                    preset=str(mission.get("preset", "")),
                    saved_at=str(mission.get("saved_at", "")),
                )
            )
        infos.sort(key=lambda m: m.saved_at, reverse=True)
        return infos

    def delete(self, name: str) -> None:
        self.path(name).unlink(missing_ok=True)

    def using_baseline(self, baseline: str) -> list[MissionInfo]:
        """Saved missions gating against a given baseline."""
        return [m for m in self.list() if m.baseline == baseline]


__all__ = [
    "DEFAULT_PRESET_ID",
    "PRESETS",
    "PRESETS_BY_ID",
    "MissionInfo",
    "MissionPreset",
    "MissionStore",
    "get_preset",
    "hardware_free_presets",
]
