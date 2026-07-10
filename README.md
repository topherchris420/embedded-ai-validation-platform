# Embedded AI Validation Platform

This brings the rigor of software testing and continuous integration to the physical world of edge AI. It enables engineers to stress-test, profile, and validate TinyML models across hardware constraints, sensor variability, and real-world conditions before they reach production devices.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Typed](https://img.shields.io/badge/mypy-strict-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![CI](https://github.com/topherchris420/embedded-ai-validation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/topherchris420/embedded-ai-validation-platform/actions/workflows/ci.yml)

Application areas: robotics, autonomous systems, industrial automation,
medical devices, IoT, and edge-AI research.

## Capabilities

| Subsystem | Function |
|-----------|----------|
| Firmware testing | Flash, boot, and pattern-match firmware over serial, J-Link, QEMU, or an in-process simulated device |
| TinyML benchmarking | Latency distribution (p50/p90/p95/p99), throughput, startup time, output stability, model size, MAC estimate for `.tflite`/`.onnx` (mock fallback for dry runs) |
| Memory analysis | Static ELF ROM/RAM footprint, model flash cost, TFLite tensor-memory floor, budget gates |
| Power measurement | Mean/peak draw and energy per inference through the `power_monitor` plugin interface (simulated monitor included; INA226/PPK2 planned) |
| Sensor fusion | Complementary, Mahony, Madgwick, 1-D Kalman, and 4-state EKF filters scored against ground-truth replay datasets (RMSE, drift) |
| Real-time profiling | WCET, jitter, and deadline-miss analysis from task telemetry |
| Hardware-in-the-loop | Deterministic fault injection (Gaussian noise, packet loss, timing jitter, sensor outages) over replayed or synthetic sensor streams |
| Telemetry | Typed serial protocol, per-board adapter plugins, capture to CSV and per-field statistics |
| Regression gating | Named baselines, direction-aware metric comparison, CI exit codes (`eaiv compare`, `eaiv pipeline`) |
| Dashboard | Streamlit analysis UI: latency distributions, metric history, cross-hardware comparison, baseline diff with release verdict |

## Repository layout

```
embedded-ai-validation-platform/
├── firmware/           # PlatformIO validation firmware (C++ HAL + app)
│   ├── include/eaiv/   # Board/IMU/filter abstraction headers
│   └── src/main.cpp    # Serial test-protocol application
├── datasets/           # Committed replay datasets + metadata sidecars
│   └── imu/            # Seeded IMU logs with ground-truth orientation
├── benchmarks/suites/  # Benchmark definitions as config (YAML)
├── configs/            # Run profiles (default, sim, stm32h7, ...)
├── dashboard/          # Streamlit dashboard (UI layer only)
├── docs/               # Guides and reference documentation
├── examples/           # Runnable example scripts
└── src/eaiv/           # Python package
    ├── plugins/        # Plugin registry + base classes
    ├── core/           # Orchestrator, reporter, regression, baseline, pipeline
    ├── targets/        # Hardware targets (qemu, serial, jlink, sim)
    ├── firmware/       # Flashing and firmware test execution
    ├── tinyml/         # Inference benchmarks
    ├── benchmarks/     # Memory footprint suite
    ├── power/          # Power monitor interface + simulated monitor
    ├── sensor_fusion/  # Fusion filters + replay experiments
    ├── datasets/       # Dataset generator, metadata schema, validation
    ├── telemetry/      # Protocol parser, adapters, providers, collector
    ├── hil/            # Fault models, simulator, HIL suite
    ├── dashboard/      # Typed data layer behind the UI
    └── rt_perf/        # Real-time profiling
```

## Quick start

```bash
git clone https://github.com/topherchris420/embedded-ai-validation-platform.git
cd embedded-ai-validation-platform
pip install -e ".[all]"

# Full validation run against the simulated device (no hardware required)
eaiv run --config configs/sim.yaml --suite all

# Individual suites
eaiv run --config configs/default.yaml --suite fusion
eaiv run --config configs/default.yaml --suite hil

# Full pipeline: validate -> telemetry -> regression gate -> baseline
eaiv pipeline --config configs/sim.yaml --telemetry-duration 2 --save-baseline first
eaiv pipeline --config configs/sim.yaml --baseline first

# Dashboard
streamlit run dashboard/python/app.py
```

See [docs/getting-started.md](docs/getting-started.md) for the guided
version, including moving from the simulator to real hardware.

## Installation

```bash
pip install -e .              # core
pip install -e ".[all]"      # everything below
pip install -e ".[dev]"      # pytest, ruff, black, mypy
pip install -e ".[jlink]"    # pylink-square for J-Link targets
pip install -e ".[tinyml]"   # onnxruntime / tflite-runtime
pip install -e ".[dashboard]"# streamlit, plotly, pandas
```

Requires Python 3.12+. Firmware builds additionally require PlatformIO
(`pip install platformio`).

## CLI reference

```bash
# Suite execution (exit code 0 iff all suites pass)
eaiv run --config <cfg> --suite firmware|tinyml|fusion|hil|memory|rt|all

# End-to-end pipeline with per-stage results and regression gate
eaiv pipeline --config <cfg> [--build-env esp32] [--baseline NAME]
              [--save-baseline NAME] [--telemetry-duration N]

# Hardware
eaiv flash build/firmware.elf --config <cfg>
eaiv monitor --config <cfg> --duration 10 [--summary] [--csv out.csv]

# Datasets (deterministic: same seed produces an identical file)
eaiv datasets generate --profile gentle --duration 20 --seed 42 -o log.csv
eaiv datasets validate datasets/

# Regression gating
eaiv baseline save reports/latest.json --name release-1
eaiv compare baselines/release-1.json reports/latest.json --max-regression-pct 10

# Introspection
eaiv show --config <cfg>      # resolved configuration (after inherit)
eaiv plugins                  # all registered plugins
eaiv targets                  # target backends only
```

## Supported hardware

| Board | Architecture | Status |
|-------|--------------|--------|
| ESP32 | Xtensa LX6 dual-core, 240 MHz | Supported; firmware built in CI |
| ESP32-S3 | Xtensa LX7 dual-core, 240 MHz | Supported; firmware built in CI |
| STM32H743 (Nucleo) | Arm Cortex-M7, 480 MHz | Supported; firmware built in CI |
| Raspberry Pi Pico | RP2040, dual Cortex-M0+, 133 MHz | Supported; firmware built in CI |
| Raspberry Pi Zero 2 W | Quad Cortex-A53 (Linux) | Planned (requires SSH target backend) |

Adding a board requires a PlatformIO environment plus, if no existing
transport fits, a `target` plugin — no framework changes. See
[docs/hardware-support.md](docs/hardware-support.md).

## Benchmark metrics

| Metric | Source | Unit |
|--------|--------|------|
| Inference latency (mean, p50, p90, p95, p99, min, max, stdev) | `tinyml` suite | ms |
| Throughput / FPS | `tinyml` suite | inferences/s |
| Startup time (cold load to first inference) | `tinyml` suite | ms |
| Confidence stability (output variance across repeated fixed-input runs) | `tinyml` suite | output units |
| Model size | `tinyml` suite | bytes |
| Estimated MACs | `tinyml` suite | count |
| Mean/peak power, energy per inference | `power_monitor` plugin | mW, mJ |
| ROM, static RAM, model flash cost | `memory` suite (ELF analysis) | KB |
| TFLite tensor-memory floor | `tinyml` suite | KB |
| On-device fusion update time | firmware `bench` command | µs |
| Boot time, free heap | firmware protocol (`U`/`M` lines) | ms, bytes |
| WCET, jitter, deadline misses | `rt` suite | µs, count |

Reports embed target identity (name, architecture, clock) and platform
version, so results are comparable across boards and releases. Output
formats: console, JSON, CSV (long format), Markdown, HTML. Metric
definitions and reproducibility rules: [docs/benchmarking.md](docs/benchmarking.md).

## Plugin system

Targets, fusion filters, fault models, power monitors, telemetry adapters,
and validation suites are plugins resolved through a single registry;
extending the platform requires no core changes:

```python
from eaiv.plugins import register_plugin
from eaiv.plugins.targets import Target, TargetInfo

@register_plugin("my_board", "target", "My custom board support")
class MyBoardTarget(Target):
    def flash(self, binary: str) -> None: ...
    def reset(self) -> None: ...
    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str: ...
    def read_serial(self, duration_s: float) -> str: ...
    def info(self) -> TargetInfo: ...
```

External packages contribute plugins through the `eaiv.plugins`
entry-point group. `eaiv plugins` lists everything registered. Interface
contracts and packaging: [docs/plugin-development.md](docs/plugin-development.md).

## Datasets

Replay datasets in [`datasets/imu/`](datasets/) are generated by a seeded
synthetic trajectory generator and are bit-for-bit reproducible. Each CSV
carries a `metadata.json` sidecar (sensors, units, sampling rate,
ground-truth columns, version, license, generator parameters) validated in
CI by `eaiv datasets validate`.

```csv
t_s,gx,gy,gz,ax,ay,az,roll_ref_deg,pitch_ref_deg
0.000000,0.190483,0.014057,0.008969,0.006064,0.001517,1.002614,0.0000,0.0000
```

Gyroscope rates are rad/s; accelerometer values are in g; ground-truth
orientation enables exact RMSE scoring of fusion filters.

## Testing

```bash
pytest tests/ -v                                   # full suite, hardware-free
pytest tests/ --cov=src/eaiv --cov-report=html     # with coverage
mypy src/eaiv && ruff check . && black --check .   # static checks
```

Every subsystem has a hardware-free test path via the simulated target,
the mock inference runtime, and committed replay datasets.

## Continuous integration

GitHub Actions workflows run on every push and pull request:

- Lint: ruff, black, mypy (strict, `disallow_untyped_defs`)
- Tests with coverage on Python 3.12
- Firmware builds for all four supported boards
- Documentation link validation and dataset validation
- Simulated benchmark run published to the job summary, with report
  artifacts uploaded

## Documentation

- [Getting Started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Benchmarking Guide](docs/benchmarking.md)
- [Usage Guide](docs/usage.md)
- [Configuration Reference](docs/config-reference.md)
- [Supported Hardware](docs/hardware-support.md)
- [Developer Guide](docs/developer-guide.md)
- [Plugin Development](docs/plugin-development.md)
- [HIL Testing](hil/README.md)
- [Firmware](firmware/README.md)
- [Benchmarks](benchmarks/README.md)
- [Dashboard](dashboard/README.md)
- [Examples](examples/README.md)
- [Migration Plan / ADR](docs/migration-plan.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT — see [LICENSE](LICENSE).

## Related projects

- [TensorFlow Lite Micro](https://www.tensorflow.org/lite/microcontrollers)
- [ONNX Runtime](https://onnxruntime.ai/)
- [PlatformIO](https://platformio.org/)
- [MLPerf Tiny](https://mlcommons.org/en/influence-tiny-benchmarks)
