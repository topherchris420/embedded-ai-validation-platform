"""Standalone example: benchmark a MobileNet .tflite model without going
through the CLI or a hardware target.

Run: python examples/benchmark_mobilenet.py
"""

from __future__ import annotations

import json

from eaiv.tinyml.benchmark import TinyMLBenchmark

if __name__ == "__main__":
    spec = {
        "model": "models/mobilenet_v1_0.25_128_int8.tflite",
        "iterations": 30,
        "warmup": 5,
    }
    result = TinyMLBenchmark(spec, target=None).run()
    print(json.dumps(result.metrics, indent=2))
    print("PASS" if result.passed else "FAIL")
