"""Example 3: HIL fault testing — how much abuse can the fusion stack take?

Replays a recorded dataset through increasingly hostile fault chains and
reports the accuracy degradation at each level. No hardware required.

Run: python examples/hil_fault_testing.py
"""

from __future__ import annotations

from eaiv.hil.suite import HILExperiment

DATASET = "datasets/imu/imu_run1.csv"

FAULT_LEVELS: dict[str, list[dict]] = {
    "clean": [],
    "noisy": [
        {"kind": "noise", "std": 0.05, "fields": ["gx", "gy", "gz"], "seed": 1},
    ],
    "hostile": [
        {"kind": "noise", "std": 0.1, "fields": ["gx", "gy", "gz"], "seed": 1},
        {"kind": "packet_loss", "probability": 0.05, "seed": 2},
        {"kind": "jitter", "std_s": 0.003, "seed": 3},
        {"kind": "outage", "start_s": 5.0, "duration_s": 0.5},
    ],
}

if __name__ == "__main__":
    for level, faults in FAULT_LEVELS.items():
        result = HILExperiment(
            {
                "source": DATASET,
                "algorithm": "ekf",
                "faults": faults,
                "max_faulted_rmse_deg": 20.0,
            }
        ).run()
        m = result.metrics
        rmse = m.get("faulted_rmse_deg", m.get("clean_rmse_deg", float("nan")))
        print(
            f"{level:<8} faults={len(faults)}  dropped={m['samples_dropped']:>4} "
            f"({m['drop_rate']:.1%})  rmse={rmse:.3f} deg  "
            f"{'PASS' if result.passed else 'FAIL'}"
        )
