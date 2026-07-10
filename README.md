# Embedded AI Validation Platform

An industry-grade platform for validating, benchmarking, profiling, and testing embedded AI systems running on resource-constrained hardware.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Typed](https://img.shields.io/badge/mypy-strict-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![CI](https://github.com/topherchris420/embedded-ai-validation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/topherchris420/embedded-ai-validation-platform/actions/workflows/ci.yml)

## 🎯 Purpose

This platform is designed to be the equivalent of **pytest + PlatformIO + MLPerf Tiny + hardware telemetry** specifically for embedded devices. It's useful for engineers working in:

- 🤖 Robotics
- 🏭 Industrial automation
- 🏥 Medical devices
- 📡 IoT
- 🚗 Autonomous systems
- ⚡ Edge AI
- 📟 Embedded firmware
- 🔬 Research

## ✨ Features

- **Firmware Testing** - Flash, boot, and exercise firmware test binaries over serial/J-Link/QEMU
- **TinyML Benchmarking** - Benchmark `.tflite` / ONNX models on-device; capture latency, RAM, ROM, MACs
- **Sensor Fusion** - Complementary / Mahony / Madgwick / Kalman / EKF filters on recorded or live IMU streams
- **Real-time Profiling** - Measure worst-case execution time, jitter, deadline misses, and ISR latency
- **Hardware-in-the-Loop** - Simulated target, fault injection (noise, packet loss, jitter, outages), dataset replay
- **Dashboard** - Real-time visualization of metrics and benchmark results
- **Plugin Architecture** - Easy extension for new boards, sensors, benchmarks, filters, faults
- **Regression Gating** - `eaiv compare` diffs report artifacts and fails CI on metric regressions
- **Telemetry Pipeline** - typed serial protocol, per-board adapter plugins, live capture to CSV/statistics
- **Power & Memory** - energy-per-inference via `power_monitor` plugins; static ROM/RAM budget gates

## 🏗️ Architecture

```
embedded-ai-validation-platform/
├── firmware/           # PlatformIO validation firmware (C++ HAL + app)
│   ├── include/eaiv/   # Board/IMU/filter abstraction headers
│   └── src/main.cpp    # Serial test-protocol application
├── datasets/           # Committed, reproducible replay datasets
│   └── imu/            # Seeded IMU logs with ground-truth orientation
├── configs/            # YAML run profiles (default, sim, stm32h7, ...)
├── dashboard/          # Streamlit dashboard
├── docs/               # Architecture, usage, config & hardware reference
├── examples/           # Standalone example scripts
└── src/eaiv/           # Python package
    ├── plugins/        # Plugin registry + base classes
    ├── core/           # Orchestrator, reporter, regression gate
    ├── targets/        # Hardware targets (qemu, serial, jlink, sim)
    ├── firmware/       # Firmware flashing/testing
    ├── tinyml/         # TinyML benchmarks
    ├── sensor_fusion/  # Fusion filters + replay experiments
    ├── datasets/       # Synthetic dataset generator
    ├── hil/            # Fault injection, simulator, HIL suite
    └── rt_perf/        # Real-time profiling
```

## 🚀 Quick Start

```bash
# Clone and install
git clone https://github.com/topherchris420/embedded-ai-validation-platform.git
cd embedded-ai-validation-platform
pip install -e ".[all]"

# Run the full validation suite hardware-free (simulated target)
eaiv run --config configs/sim.yaml --suite all

# Run individual suites
eaiv run --config configs/default.yaml --suite fusion
eaiv run --config configs/default.yaml --suite hil

# Explore
eaiv plugins                          # everything registered
eaiv show --config configs/sim.yaml   # resolved configuration

# Start the dashboard
streamlit run dashboard/python/app.py
```

## 📦 Installation

### Core Dependencies

```bash
pip install -e .
```

### Full Development Environment

```bash
pip install -e ".[all]"
```

### Individual Extras

```bash
pip install -e ".[dev]"       # Development tools
pip install -e ".[jlink]"      # J-Link debugging
pip install -e ".[tinyml]"     # TinyML runtimes
pip install -e ".[dashboard]" # Dashboard
pip install -e ".[hil]"        # HIL testing
```

## 💻 CLI Usage

### Running suites

```bash
eaiv run --config configs/default.yaml --suite all
eaiv run --config configs/stm32h7.yaml --suite tinyml
eaiv run --config configs/sim.yaml --suite firmware      # no hardware
eaiv run --config configs/default.yaml --suite hil       # fault injection
```

### Hardware tools

```bash
eaiv flash build/firmware.elf --config configs/stm32h7.yaml
eaiv monitor --config configs/esp32.yaml --duration 10
```

### Datasets and regression gating

```bash
# Deterministic synthetic IMU log (same seed => identical file)
eaiv datasets generate --profile gentle --duration 20 --seed 42 -o log.csv

# Fail CI when any metric worsens by more than 10%
eaiv compare baseline.json reports/latest.json --max-regression-pct 10
```

### Introspection

```bash
eaiv show --config configs/default.yaml   # resolved config (after inherit)
eaiv plugins                              # all registered plugins
eaiv targets                              # target backends only
```

## 🔧 Supported Hardware

| Board | Architecture | Status |
|-------|--------------|--------|
| ESP32 | Xtensa LX6 dual-core | ✅ |
| ESP32-S3 | Xtensa LX7 dual-core | ✅ |
| STM32H743 | ARM Cortex-M7 | ✅ |
| RPi Pico | RP2040 (Cortex-M0+) | ✅ |
| RPi Zero 2 W | ARM Cortex-A53 | 🔜 |

Firmware for every ✅ board is built in CI; see [docs/hardware-support.md](docs/hardware-support.md)
for target-backend details and how to add a board.

## 📊 Benchmark Metrics

| Metric | Description |
|--------|-------------|
| Inference Latency | Time per inference (ms) |
| FPS | Frames per second |
| RAM Usage | Memory consumption (KB) |
| Flash Size | Model storage (KB) |
| CPU Utilization | Processor usage (%) |
| Power Consumption | Energy draw (mW) |
| Startup Time | Time to first inference (ms) |
| Energy per Inference | mJ, via `power_monitor` plugins |
| ROM / static RAM | ELF footprint analysis (KB) |

## 🔌 Plugin System

Targets, fusion filters, and fault models are all plugins — extend the
platform without touching core code:

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

External packages can ship plugins via the `eaiv.plugins` entry-point
group. `eaiv plugins` lists everything registered — including the built-in
fusion filters (`complementary`, `mahony`, `madgwick`, `kalman`, `ekf`)
and HIL fault models (`noise`, `packet_loss`, `jitter`, `outage`).

## 📁 Datasets

Committed, replay-capable IMU logs live in [`datasets/imu/`](datasets/) —
generated with a seeded synthetic trajectory generator, so they carry exact
ground-truth orientation columns and are reproducible bit-for-bit:

```csv
t_s,gx,gy,gz,ax,ay,az,roll_ref_deg,pitch_ref_deg
0.000000,0.190483,0.014057,0.008969,0.006064,0.001517,1.002614,0.0000,0.0000
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=src/eaiv --cov-report=html

# Run specific test
pytest tests/test_tinyml.py -v
```

## 📈 CI/CD

GitHub Actions workflows are included for:

- Code linting (ruff, black, mypy)
- Unit tests with coverage
- Firmware builds (ESP32, STM32, RPi Pico)
- Documentation generation
- Integration tests

## 📚 Documentation

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

## 🤝 Contributing

Contributions are welcome! Please read the [Contributing Guide](CONTRIBUTING.md) before submitting PRs.

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

## 🔗 Related Projects

- [TensorFlow Lite Micro](https://www.tensorflow.org/lite/microcontrollers)
- [ONNX Runtime](https://onnxruntime.ai/)
- [PlatformIO](https://platformio.org/)
- [MLPerf Tiny](https://mlcommons.org/en/influence-tiny-benchmarks)