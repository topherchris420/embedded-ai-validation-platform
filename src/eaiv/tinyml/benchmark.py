"""On-device (or on-host, via QEMU/serial passthrough) TinyML benchmarking."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from typing import TYPE_CHECKING

from eaiv.core.results import SuiteResult
from eaiv.targets.base import Target

if TYPE_CHECKING:
    from eaiv.power import PowerMonitor
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

        # Startup: cold model load through first inference (time-to-first-
        # inference), measured before the timed loop touches the runtime.
        t_start = time.perf_counter()
        try:
            meta, runtime = load_model(model_path)
            x = self._load_input(meta.input_shape)
            self._invoke(runtime, meta, x)
        except Exception as e:  # noqa: BLE001
            return SuiteResult(
                name="tinyml", passed=False, metrics={}, notes=f"model load failed: {e}"
            )
        startup_ms = (time.perf_counter() - t_start) * 1000.0

        monitor = self._build_monitor()
        if monitor is not None:
            monitor.start()

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
                "startup_ms": round(startup_ms, 3),
            }
        )

        stability = self._confidence_stability(runtime, meta, x)
        if stability is not None:
            summary["confidence_stability"] = stability
        arena_kb = self._tensor_arena_estimate_kb(runtime, meta)
        if arena_kb is not None:
            summary["tensor_arena_est_kb"] = arena_kb

        if monitor is not None:
            trace = monitor.stop()
            total_inferences = warmup + iterations
            summary.update(
                {
                    "mean_power_mw": round(trace.mean_mw, 3),
                    "peak_power_mw": round(trace.peak_mw, 3),
                    "energy_per_inference_mj": round(trace.energy_mj / total_inferences, 6),
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

    def _build_monitor(self) -> "PowerMonitor | None":
        """Power monitoring is opt-in: ``tinyml.power: {kind: sim, ...}``."""
        power_spec = self.spec.get("power")
        if not power_spec:
            return None
        from eaiv.power import build_power_monitor

        return build_power_monitor(power_spec)

    @staticmethod
    def _load_input(shape: tuple) -> np.ndarray:
        clean_shape = tuple(d if d and d > 0 else 1 for d in shape)
        rng = np.random.default_rng(seed=0)
        return rng.standard_normal(clean_shape).astype("float32")

    @staticmethod
    def _confidence_stability(
        runtime: Any, meta: ModelMeta, x: np.ndarray, runs: int = 10
    ) -> float | None:
        """Max per-element std of the output vector over repeated runs on
        one fixed input. 0.0 means bit-stable outputs; growth indicates
        numeric noise (uninitialized memory, racy accelerators, dropout
        left enabled). Runs outside the timed loop so latency stats are
        unaffected."""
        outputs: list[np.ndarray] = []
        for _ in range(runs):
            out = TinyMLBenchmark._invoke_and_read(runtime, meta, x)
            if out is None:
                return None
            outputs.append(np.asarray(out, dtype="float64").ravel())
        if len({o.shape for o in outputs}) != 1:
            return None
        return round(float(np.stack(outputs).std(axis=0).max()), 9)

    @staticmethod
    def _invoke_and_read(runtime: Any, meta: ModelMeta, x: np.ndarray) -> Any:
        """Invoke once and return the first output tensor (or None)."""
        if meta.backend == "tflite":
            input_details = runtime.get_input_details()[0]
            runtime.set_tensor(input_details["index"], x.astype(input_details["dtype"]))
            runtime.invoke()
            return runtime.get_tensor(runtime.get_output_details()[0]["index"])
        if meta.backend == "onnx":
            input_name = runtime.get_inputs()[0].name
            return runtime.run(None, {input_name: x})[0]
        return runtime.invoke(x)  # mock

    @staticmethod
    def _tensor_arena_estimate_kb(runtime: Any, meta: ModelMeta) -> float | None:
        """Lower-bound estimate of TFLite tensor memory: sum of all tensor
        buffer sizes. A real TFLM arena also holds scratch buffers and
        alignment padding, so treat this as a floor, not the arena size."""
        if meta.backend != "tflite":
            return None
        try:
            total = 0
            for detail in runtime.get_tensor_details():
                shape = [int(d) for d in detail.get("shape", []) if int(d) > 0]
                itemsize = np.dtype(detail["dtype"]).itemsize
                total += int(np.prod(shape)) * itemsize if shape else itemsize
            return round(total / 1024.0, 2)
        except Exception:  # noqa: BLE001 - estimate only, never fail the run
            return None

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
