"""Benchmark plugin base classes and registry.

Benchmarks measure performance metrics for AI workloads on embedded devices.
This module provides the plugin interface for benchmark implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from eaiv.plugins import register_plugin

if TYPE_CHECKING:
    from eaiv.plugins import PluginMetadata


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    name: str
    passed: bool
    metrics: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "metrics": self.metrics,
            "notes": self.notes,
        }


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""

    model_path: str = ""
    iterations: int = 50
    warmup: int = 5
    input_shape: tuple = (1, 224, 224, 3)
    output_shape: tuple = (1, 1000)
    batch_size: int = 1


@dataclass
class LatencyMetrics:
    """Latency measurement results."""

    mean_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    std_ms: float
    count: int


@dataclass
class MemoryMetrics:
    """Memory usage measurement results."""

    ram_peak_kb: int = 0
    ram_static_kb: int = 0
    ram_runtime_kb: int = 0
    flash_rom_kb: int = 0
    flash_model_kb: int = 0


@dataclass
class ModelMetadata:
    """Metadata about a loaded model."""

    name: str
    backend: str  # "tflite", "onnx", "mock"
    input_shape: tuple
    output_shape: tuple
    size_bytes: int
    estimated_macs: int = 0
    layers: int = 0


class Benchmark(ABC):
    """Abstract benchmark interface.

    Benchmarks measure performance metrics for AI/ML workloads. Implementations
    must provide:
    - load_model(): Load a model for benchmarking
    - run(): Execute benchmark and return results
    - get_metrics(): Get specific metric types

    The benchmark operates on a target device (real or emulated).
    """

    def __init__(self, config: BenchmarkConfig, target=None) -> None:
        self.config = config
        self.target = target
        self._model = None

    @abstractmethod
    def load_model(self, path: str) -> ModelMetadata:
        """Load a model from path.

        Args:
            path: Path to model file (.tflite, .onnx, etc.)

        Returns:
            ModelMetadata with model information

        Raises:
            ModelLoadError: If model cannot be loaded
        """
        ...

    @abstractmethod
    def run(self) -> BenchmarkResult:
        """Run the benchmark.

        Returns:
            BenchmarkResult with metrics
        """
        ...

    def unload_model(self) -> None:
        """Unload the current model and free resources."""
        self._model = None

    @staticmethod
    def calculate_latency_stats(timings: list[float]) -> LatencyMetrics:
        """Calculate latency statistics from timing data.

        Args:
            timings: List of timing measurements in seconds

        Returns:
            LatencyMetrics with statistics
        """
        if not timings:
            return LatencyMetrics(
                mean_ms=0, min_ms=0, max_ms=0, p50_ms=0, p95_ms=0, p99_ms=0, std_ms=0, count=0
            )

        import numpy as np

        timings_ms = np.array(timings) * 1000  # Convert to ms

        return LatencyMetrics(
            mean_ms=float(np.mean(timings_ms)),
            min_ms=float(np.min(timings_ms)),
            max_ms=float(np.max(timings_ms)),
            p50_ms=float(np.percentile(timings_ms, 50)),
            p95_ms=float(np.percentile(timings_ms, 95)),
            p99_ms=float(np.percentile(timings_ms, 99)),
            std_ms=float(np.std(timings_ms)),
            count=len(timings_ms),
        )


class BenchmarkSuite(ABC):
    """A collection of related benchmarks.

    Allows grouping benchmarks that share setup/teardown logic.
    """

    def __init__(self, config: dict, target=None) -> None:
        self.config = config
        self.target = target
        self._benchmarks: list[Benchmark] = []

    @abstractmethod
    def setup(self) -> None:
        """Set up the benchmark suite."""
        ...

    @abstractmethod
    def teardown(self) -> None:
        """Tear down the benchmark suite."""
        ...

    @abstractmethod
    def list_benchmarks(self) -> list[str]:
        """List available benchmark names."""
        ...

    def run_benchmark(self, name: str) -> BenchmarkResult:
        """Run a specific benchmark by name."""
        raise NotImplementedError(f"Benchmark not found: {name}")

    def run_all(self) -> list[BenchmarkResult]:
        """Run all benchmarks in the suite."""
        results = []
        for name in self.list_benchmarks():
            results.append(self.run_benchmark(name))
        return results


class BenchmarkPluginMixin:
    """Mixin to provide plugin metadata for benchmarks."""

    PLUGIN_METADATA: PluginMetadata = None  # type: ignore[assignment]


__all__ = [
    "Benchmark",
    "BenchmarkSuite",
    "BenchmarkResult",
    "BenchmarkConfig",
    "ModelMetadata",
    "LatencyMetrics",
    "MemoryMetrics",
    "BenchmarkPluginMixin",
    "register_plugin",
]
