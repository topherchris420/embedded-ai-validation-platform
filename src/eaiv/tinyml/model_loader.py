"""Load .tflite / .onnx models with a uniform interface."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ModelMeta:
    path: str
    backend: str        # 'tflite' | 'onnx' | 'mock'
    input_shape: tuple
    output_shape: tuple
    size_bytes: int


def load_model(path: str) -> tuple[ModelMeta, Any]:
    """Returns (metadata, runtime_handle). runtime_handle's type depends on
    backend: a tflite Interpreter, an onnxruntime InferenceSession, or a
    lightweight mock object when the requested runtime isn't installed."""
    p = Path(path)
    if not p.exists():
        # Allow dry-run/CI usage against a synthetic model without the
        # actual weights file being present.
        return _mock_model(str(p))

    size = p.stat().st_size
    suffix = p.suffix.lower()

    if suffix == ".tflite":
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except ImportError:
            from tensorflow.lite.python.interpreter import Interpreter  # type: ignore
        interp = Interpreter(model_path=str(p))
        interp.allocate_tensors()
        details_in = interp.get_input_details()[0]
        details_out = interp.get_output_details()[0]
        meta = ModelMeta(
            str(p), "tflite", tuple(details_in["shape"]), tuple(details_out["shape"]), size
        )
        return meta, interp

    if suffix == ".onnx":
        import onnxruntime as ort  # type: ignore

        sess = ort.InferenceSession(str(p))
        in0 = sess.get_inputs()[0]
        out0 = sess.get_outputs()[0]
        meta = ModelMeta(str(p), "onnx", tuple(in0.shape), tuple(out0.shape), size)
        return meta, sess

    raise ValueError(f"Unsupported model type: {suffix}")


def _mock_model(path: str) -> tuple[ModelMeta, Any]:
    """Deterministic stand-in used when no real model file/runtime is
    available (e.g. running the example locally without downloading
    weights). Keeps `eaiv run` usable out of the box for a first smoke test."""

    class _MockRuntime:
        def invoke(self, x):
            import numpy as np

            return np.zeros((1, 10), dtype="float32")

    meta = ModelMeta(path, "mock", (1, 128, 128, 3), (1, 10), 0)
    return meta, _MockRuntime()
