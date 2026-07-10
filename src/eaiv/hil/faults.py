"""Composable fault models injected into HIL sample streams.

A fault receives one sample ``(t_s, values)`` and returns a (possibly
modified) sample, or ``None`` to drop it. Faults are deterministic for a
given seed so HIL runs are reproducible. Each model is registered as a
``fault`` plugin; ``build_fault`` resolves config dicts through the
registry, so external packages can contribute new fault types.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Callable

from eaiv.plugins import get_registry, register_plugin

Sample = tuple[float, dict[str, float]]


class Fault(ABC):
    """One link in a fault-injection chain."""

    @abstractmethod
    def apply(self, t_s: float, values: dict[str, float]) -> Sample | None:
        """Transform a sample; return None to drop it entirely."""
        ...


class GaussianNoise(Fault):
    """Additive white noise on selected fields (default: all numeric fields)."""

    def __init__(self, std: float = 0.01, fields: list[str] | None = None, seed: int = 0) -> None:
        self.std = std
        self.fields = fields
        self._rng = random.Random(seed)

    def apply(self, t_s: float, values: dict[str, float]) -> Sample:
        fields = self.fields if self.fields is not None else list(values)
        noisy = dict(values)
        for f in fields:
            if f in noisy:
                noisy[f] = noisy[f] + self._rng.gauss(0.0, self.std)
        return t_s, noisy


class PacketLoss(Fault):
    """Independently drop each sample with a fixed probability."""

    def __init__(self, probability: float = 0.05, seed: int = 0) -> None:
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {probability}")
        self.probability = probability
        self._rng = random.Random(seed)

    def apply(self, t_s: float, values: dict[str, float]) -> Sample | None:
        if self._rng.random() < self.probability:
            return None
        return t_s, values


class TimingJitter(Fault):
    """Perturb sample timestamps with zero-mean Gaussian jitter.

    Timestamps are kept strictly monotonic so downstream ``dt``
    computations stay positive.
    """

    def __init__(self, std_s: float = 0.001, seed: int = 0) -> None:
        self.std_s = std_s
        self._rng = random.Random(seed)
        self._last_t = float("-inf")

    def apply(self, t_s: float, values: dict[str, float]) -> Sample:
        jittered = t_s + self._rng.gauss(0.0, self.std_s)
        jittered = max(jittered, self._last_t + 1e-6)
        self._last_t = jittered
        return jittered, values


class SensorOutage(Fault):
    """Drop every sample inside a [start_s, start_s + duration_s) window."""

    def __init__(self, start_s: float = 1.0, duration_s: float = 0.5) -> None:
        self.start_s = start_s
        self.duration_s = duration_s

    def apply(self, t_s: float, values: dict[str, float]) -> Sample | None:
        if self.start_s <= t_s < self.start_s + self.duration_s:
            return None
        return t_s, values


def _register_builtin_faults() -> None:
    builtin: dict[str, tuple[type[Fault], str]] = {
        "noise": (GaussianNoise, "Additive Gaussian sensor noise"),
        "packet_loss": (PacketLoss, "Random independent sample loss"),
        "jitter": (TimingJitter, "Gaussian timing jitter (monotonic)"),
        "outage": (SensorOutage, "Sensor silent for a time window"),
    }

    def make_factory(cls: type[Fault]) -> Callable[[dict], Fault]:
        def factory(cfg: dict) -> Fault:
            return cls(**cfg)

        return factory

    registry = get_registry()
    for name, (cls, description) in builtin.items():
        if registry.get("fault", name) is None:
            register_plugin(name, "fault", description, version="1.0.0")(make_factory(cls))


_register_builtin_faults()


def build_fault(spec: dict) -> Fault:
    """Build a fault from a config dict: ``{"kind": "noise", "std": 0.05}``."""
    spec = dict(spec)
    kind = spec.pop("kind", None)
    if kind is None:
        raise ValueError(f"Fault spec missing 'kind': {spec}")
    fault = get_registry().create("fault", kind, spec)
    if not isinstance(fault, Fault):
        raise TypeError(f"Plugin 'fault:{kind}' did not produce a Fault: {type(fault)!r}")
    return fault
