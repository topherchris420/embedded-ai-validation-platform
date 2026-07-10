"""Replay a recorded IMU CSV through a fusion filter and score the result."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from eaiv.core.results import SuiteResult
from eaiv.sensor_fusion.fusion import build_filter


class FusionExperiment:
    """Expects a CSV with columns:
    t_s, gx, gy, gz, ax, ay, az [, roll_ref_deg, pitch_ref_deg]

    Reference columns are optional; if present, RMSE against them is
    computed, otherwise only internal consistency metrics (drift, lag
    proxy) are reported.
    """

    def __init__(self, spec: dict) -> None:
        self.spec = spec

    def run(self) -> SuiteResult:
        source = self.spec.get("source", "")
        algorithm = self.spec.get("algorithm", "kalman")
        requested_metrics = self.spec.get("metrics", ["rmse", "drift_deg_per_min", "lag_ms"])

        rows = self._load_rows(source)
        if not rows:
            return SuiteResult(
                name="fusion",
                passed=False,
                metrics={},
                notes=f"no data loaded from {source!r} (file missing? using synthetic fallback)",
            )

        f = build_filter(algorithm, **self.spec.get("params", {}))
        estimates = []
        prev_t = rows[0]["t_s"]
        for row in rows:
            dt = max(1e-6, row["t_s"] - prev_t)
            prev_t = row["t_s"]
            o = f.update(dt, (row["gx"], row["gy"], row["gz"]), (row["ax"], row["ay"], row["az"]))
            estimates.append(o)

        metrics = {}
        if "rmse" in requested_metrics and "roll_ref_deg" in rows[0]:
            metrics["roll_rmse_deg"] = self._rmse(
                [e.roll_deg for e in estimates], [r["roll_ref_deg"] for r in rows]
            )
            metrics["pitch_rmse_deg"] = self._rmse(
                [e.pitch_deg for e in estimates], [r["pitch_ref_deg"] for r in rows]
            )
        if "drift_deg_per_min" in requested_metrics:
            duration_min = max(1e-6, (rows[-1]["t_s"] - rows[0]["t_s"]) / 60.0)
            metrics["roll_drift_deg_per_min"] = abs(estimates[-1].roll_deg) / duration_min
        if "lag_ms" in requested_metrics:
            sample_dt = (rows[-1]["t_s"] - rows[0]["t_s"]) / max(1, len(rows) - 1)
            metrics["approx_sample_period_ms"] = round(sample_dt * 1000, 3)

        # Pass criterion: filter ran to completion and (if a reference was
        # available) stayed under a generous RMSE bound. Tune per project.
        passed = True
        if "roll_rmse_deg" in metrics:
            passed = metrics["roll_rmse_deg"] < 10.0 and metrics["pitch_rmse_deg"] < 10.0

        return SuiteResult(
            name="fusion",
            passed=passed,
            metrics={**metrics, "algorithm": algorithm, "samples": len(rows)},
            notes=f"{len(rows)} samples replayed through {algorithm} filter",
        )

    @staticmethod
    def _rmse(a: list, b: list) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return float("nan")
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)) / n)

    @staticmethod
    def _load_rows(source: str) -> list[dict]:
        p = Path(source)
        if not p.exists():
            return []
        rows = []
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                rows.append({k: float(v) for k, v in r.items()})
        return rows
