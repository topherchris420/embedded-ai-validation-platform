# Benchmarks Module

Reproducible benchmark suites for TinyML workloads on embedded devices.
Benchmarks are **data** (YAML suite definitions in `suites/`) executed by
the platform engine — the same definition runs on a simulated target in CI
and on real hardware at the bench.

## Metric coverage

| Metric | Suite | Source |
|--------|-------|--------|
| Inference latency (mean/p50/p95/p99) | `tinyml` | host runtime timing loop |
| Throughput / FPS | `tinyml` | derived from latency |
| Startup time (cold load → first inference) | `tinyml` | `startup_ms` |
| Model size | `tinyml` | model file |
| Estimated MACs | `tinyml` | shape heuristic |
| Power (mean/peak), energy per inference | `tinyml.power` | `power_monitor` plugin (`sim` today; INA226/PPK2 planned) |
| ROM / static RAM footprint | `memory` | ELF section analysis |
| Model flash cost | `memory` | model file + ELF |
| On-device fusion update time | firmware `bench` cmd | `eaiv monitor --summary` |
| WCET / jitter / deadline misses | `rt` | task telemetry |

## Suite definitions

```
benchmarks/suites/
├── inference-sim.yaml      # inference + simulated power, runs anywhere
├── memory-esp32.yaml       # ROM/RAM budget gate for the ESP32 build
└── robustness-faults.yaml  # fusion accuracy under fault injection
```

```bash
eaiv run --config benchmarks/suites/inference-sim.yaml --suite tinyml
eaiv run --config benchmarks/suites/memory-esp32.yaml --suite memory
eaiv run --config benchmarks/suites/robustness-faults.yaml --suite hil
```

## Regression gating

Every run writes `reports/latest.json`. Keep a known-good baseline and
gate CI with:

```bash
eaiv compare baseline.json reports/latest.json --max-regression-pct 10
```

Metric direction (lower-is-better vs higher-is-better) is inferred per
metric; see `eaiv.core.regression`.

## Configuration

```yaml
tinyml:
  model: models/mobilenet_v1_0.25_128_int8.tflite
  runtime: tflite            # tflite | onnx | mock
  iterations: 200
  warmup: 20
  power: {kind: sim, active_mw: 180.0}   # any power_monitor plugin

memory:
  binary: firmware/.pio/build/esp32/firmware.elf
  model: models/mobilenet_v1_0.25_128_int8.tflite
  max_rom_kb: 1024           # optional pass thresholds
  max_ram_kb: 256
  require: true              # missing binary fails instead of skipping
```

## Extending

- **New power hardware**: implement `eaiv.power.PowerMonitor`, register as
  a `power_monitor` plugin.
- **New benchmark suite**: implement a class with `run() -> SuiteResult`,
  wire into `Orchestrator` (or ship as a plugin package) — see
  [docs/plugin-development.md](../docs/plugin-development.md).
