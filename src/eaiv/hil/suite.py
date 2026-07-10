"""Orchestrator-facing HIL experiment: fusion robustness under faults.

Replays a dataset twice through the configured fusion algorithm — once
clean, once through the fault chain — and reports the accuracy
degradation plus stream statistics. Config example:

    hil:
      source: datasets/imu/imu_run1.csv
      algorithm: madgwick
      params: {beta: 0.2}
      faults:
        - {kind: noise, std: 0.05}
        - {kind: packet_loss, probability: 0.02, seed: 1}
        - {kind: jitter, std_s: 0.002}
      max_faulted_rmse_deg: 15.0
"""

from __future__ import annotations

import math
from typing import Iterable

from eaiv.core.results import SuiteResult
from eaiv.hil.faults import build_fault
from eaiv.hil.replay import replay_csv
from eaiv.hil.simulator import Sample, Simulator
from eaiv.sensor_fusion.fusion import build_filter


class HILExperiment:
    def __init__(self, spec: dict) -> None:
        self.spec = spec

    def run(self) -> SuiteResult:
        source_path = self.spec.get("source", "datasets/imu/imu_run1.csv")
        algorithm = self.spec.get("algorithm", "madgwick")
        params = self.spec.get("params", {})
        fault_specs = self.spec.get("faults", [])
        max_rmse = float(self.spec.get("max_faulted_rmse_deg", 15.0))

        try:
            clean = list(replay_csv(source_path))
        except FileNotFoundError:
            return SuiteResult(
                name="hil", passed=False, metrics={}, notes=f"dataset not found: {source_path!r}"
            )
        if not clean:
            return SuiteResult(
                name="hil", passed=False, metrics={}, notes=f"empty dataset: {source_path!r}"
            )

        faults = [build_fault(f) for f in fault_specs]
        sim = Simulator(iter(clean), faults)
        faulted = sim.run()

        metrics: dict = {
            "algorithm": algorithm,
            "samples_in": len(clean),
            "samples_out": faulted.emitted,
            "samples_dropped": faulted.dropped,
            "drop_rate": round(faulted.drop_rate, 4),
            "faults": [f.get("kind") for f in fault_specs],
        }

        clean_rmse = self._score(algorithm, params, clean)
        faulted_rmse = self._score(algorithm, params, faulted.samples)
        passed = faulted.emitted > 0
        if clean_rmse is not None and faulted_rmse is not None:
            metrics["clean_rmse_deg"] = round(clean_rmse, 4)
            metrics["faulted_rmse_deg"] = round(faulted_rmse, 4)
            metrics["degradation_deg"] = round(faulted_rmse - clean_rmse, 4)
            passed = passed and faulted_rmse < max_rmse

        return SuiteResult(
            name="hil",
            passed=passed,
            metrics=metrics,
            notes=f"{len(faults)} fault(s) injected into {source_path}",
        )

    @staticmethod
    def _score(algorithm: str, params: dict, samples: Iterable[Sample]) -> float | None:
        """Combined roll+pitch RMSE against reference columns, if present."""
        f = build_filter(algorithm, **params)
        errors: list[float] = []
        prev_t: float | None = None
        for t_s, values in samples:
            dt = 0.01 if prev_t is None else max(1e-6, t_s - prev_t)
            prev_t = t_s
            o = f.update(
                dt,
                (values["gx"], values["gy"], values["gz"]),
                (values["ax"], values["ay"], values["az"]),
            )
            if "roll_ref_deg" in values:
                errors.append(o.roll_deg - values["roll_ref_deg"])
                errors.append(o.pitch_deg - values["pitch_ref_deg"])
        if not errors:
            return None
        return math.sqrt(sum(e * e for e in errors) / len(errors))
