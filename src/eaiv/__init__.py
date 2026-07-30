"""eaiv — Embedded AI Validation Platform.

A modular platform for validating, benchmarking, profiling, and testing
embedded AI systems running on resource-constrained hardware.

Core Modules:
- plugins: Plugin system for extensible architecture
- firmware: Firmware flashing and testing
- tinyml: TinyML benchmarking
- sensor_fusion: Sensor fusion algorithms and experiments
- rt_perf: Real-time performance profiling
- targets: Hardware target backends (QEMU, serial, J-Link)

Quick Start:
    from eaiv import Orchestrator, load_config
    cfg = load_config("configs/default.yaml")
    orch = Orchestrator(cfg)
    results = orch.run("all")
"""

from __future__ import annotations

__version__ = "0.3.0"

# Core exports
from eaiv.config import Config, load_config
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.results import AggregateResult, SuiteResult

# Plugin system exports
from eaiv.plugins import (
    PluginMetadata,
    PluginRegistry,
    get_registry,
    load_entry_point_plugins,
    register_plugin,
)
from eaiv.plugins.benchmarks import (
    Benchmark,
    BenchmarkConfig,
    BenchmarkResult,
    LatencyMetrics,
    ModelMetadata,
)
from eaiv.plugins.sensors import (
    IMUData,
    IMUSensor,
    Sensor,
    SensorReading,
    VirtualSensor,
)
from eaiv.plugins.targets import Target, TargetInfo

__all__ = [  # noqa: RUF022 - grouped by subsystem, which reads better than sorted
    # Version
    "__version__",
    # Core
    "Config",
    "load_config",
    "Orchestrator",
    "AggregateResult",
    "SuiteResult",
    # Plugins
    "PluginRegistry",
    "PluginMetadata",
    "register_plugin",
    "get_registry",
    "load_entry_point_plugins",
    # Targets
    "Target",
    "TargetInfo",
    # Sensors
    "Sensor",
    "IMUSensor",
    "VirtualSensor",
    "IMUData",
    "SensorReading",
    # Benchmarks
    "Benchmark",
    "BenchmarkResult",
    "BenchmarkConfig",
    "ModelMetadata",
    "LatencyMetrics",
]
