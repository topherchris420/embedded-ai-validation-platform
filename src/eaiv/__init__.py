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
from eaiv.config import load_config, Config  # noqa: E402
from eaiv.core.orchestrator import Orchestrator  # noqa: E402
from eaiv.core.results import AggregateResult, SuiteResult  # noqa: E402

# Plugin system exports
from eaiv.plugins import (  # noqa: E402
    PluginRegistry,
    PluginMetadata,
    register_plugin,
    get_registry,
    load_entry_point_plugins,
)
from eaiv.plugins.targets import Target, TargetInfo  # noqa: E402
from eaiv.plugins.sensors import (  # noqa: E402
    Sensor,
    IMUSensor,
    VirtualSensor,
    IMUData,
    SensorReading,
)
from eaiv.plugins.benchmarks import (  # noqa: E402
    Benchmark,
    BenchmarkResult,
    BenchmarkConfig,
    ModelMetadata,
    LatencyMetrics,
)

__all__ = [
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
