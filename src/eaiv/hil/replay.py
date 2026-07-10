"""Sample-stream sources for the HIL simulator.

A stream is an iterator of ``(t_s, values)`` where ``values`` maps field
names to floats. Streams come from recorded CSV logs or from the seeded
synthetic generator, so every HIL run is reproducible.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from eaiv.datasets import generate_imu_trajectory, read_imu_csv

Sample = tuple[float, dict[str, float]]


def replay_csv(path: str | Path) -> Iterator[Sample]:
    """Stream a recorded log; every column except ``t_s`` becomes a field."""
    for row in read_imu_csv(path):
        t = row.pop("t_s")
        yield t, row


def synthetic_imu_stream(
    duration_s: float = 10.0,
    rate_hz: float = 100.0,
    profile: str = "gentle",
    seed: int = 0,
    **generator_kwargs: float,
) -> Iterator[Sample]:
    """Stream a synthetic IMU trajectory (see ``eaiv.datasets``)."""
    for sample in generate_imu_trajectory(
        duration_s=duration_s, rate_hz=rate_hz, profile=profile, seed=seed, **generator_kwargs
    ):
        values = asdict(sample)
        t = values.pop("t_s")
        yield t, values
