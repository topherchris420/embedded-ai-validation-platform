"""On-device (or on-host, via QEMU/serial passthrough) TinyML benchmarking."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from eaiv.core.results import SuiteResult
from eaiv.targets.base import Target
from eaiv.tinyml.metrics import LatencyStats, estimate_macs
from eaiv.tinyml.model_loader import ModelMeta, load_model


class TinyMLBenchmark:
    def __init__(self, spec: dict, target: Target) -> None:
        self.spec = spec
        self.target = target

    def run(self) -> SuiteResult:
        model_path = self.spec.get("model", "")
        iterations = int(self.spec.get("iterations", 50))
        warmup = int(self.spec.get("warmup", 5))

        try:
            meta, runtime = load_model(model_path)
        except Exception as e:  # noqa: BLE001
            return SuiteResult(
                name="tinyml", passed=False, metrics={}, notes=f"model load failed: {e}"
            )

        x = self._load_input(meta.input_shape)

        stats = LatencyStats()
        for i in range(warmup + iterations):
            t0 = time.perf_counter()
            self._invoke(runtime, meta, x)
            dt = time.perf_counter() - t0
            if i >= warmup:
                stats.add(dt)

        macs = estimate_macs(meta.input_shape, meta.output_shape)
        summary = stats.summary()
        summary.update(
            {
                "backend": meta.backend,
                "model_size_bytes": meta.size_bytes,
                "estimated_macs": macs,
            }
        )

        # A benchmark "passes" as long as it produced timing data at all;
        # regressions against a baseline belong in a separate comparison
        # step (e.g. diffing report JSON across CI runs).
        passed = stats.count == iterations
        return SuiteResult(
            name="tinyml",
            passed=passed,
            metrics=summary,
            notes=f"{meta.backend} model, {iterations} timed iterations",
        )

    @staticmethod
    def _load_input(shape: tuple) -> np.ndarray:
        clean_shape = tuple(d if d and d > 0 else 1 for d in shape)
        rng = np.random.default_rng(seed=0)
        return rng.standard_normal(clean_shape).astype("float32")

    @staticmethod
    def _invoke(runtime: Any, meta: ModelMeta, x: np.ndarray) -> None:
        if meta.backend == "tflite":
            input_details = runtime.get_input_details()[0]
            runtime.set_tensor(input_details["index"], x.astype(input_details["dtype"]))
            runtime.invoke()
        elif meta.backend == "onnx":
            input_name = runtime.get_inputs()[0].name
            runtime.run(None, {input_name: x})
        else:  # mock
            runtime.invoke(x)
