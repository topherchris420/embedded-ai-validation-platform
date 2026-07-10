"""Example 2: benchmark TinyML inference with power and stability metrics.

Uses the mock runtime if the model file is absent, so it runs anywhere;
point `model` at a real .tflite/.onnx file for actual numbers.

Run: python examples/benchmark_mobilenet.py
"""

from __future__ import annotations

import json

from eaiv.tinyml.benchmark import TinyMLBenchmark

if __name__ == "__main__":
    spec = {
        "model": "models/mobilenet_v1_0.25_128_int8.tflite",
        "iterations": 50,
        "warmup": 5,
        # Any power_monitor plugin; 'sim' needs no instrumentation.
        "power": {"kind": "sim", "active_mw": 180.0, "seed": 0},
    }
    result = TinyMLBenchmark(spec, target=None).run()
    print(json.dumps(result.metrics, indent=2))
    print("PASS" if result.passed else "FAIL")
