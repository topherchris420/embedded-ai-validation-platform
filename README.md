# eaiv — Embedded AI Validation Platform

`eaiv` is an open-source test harness for validating AI workloads on
resource-constrained embedded hardware. It bundles four cooperating
subsystems:

| Subsystem | What it does |
|-----------|--------------|
| `firmware` | Flash, boot, and exercise firmware test binaries over serial/J-Link/QEMU. |
| `tinyml`   | Benchmark `.tflite` / ONNX models on-device; capture latency, RAM, ROM, MACs. |
| `sensor_fusion` | Run Kalman / complementary / Mahony filters on recorded or live IMU streams. |
| `rt_perf`  | Measure worst-case execution time, jitter, deadline misses, and ISR latency. |

## Why

Embedded AI projects usually validate each subsystem by hand: flash the
board, watch the serial monitor, eyeball the numbers, repeat. `eaiv` turns
that loop into a single reproducible command that CI can run on every push —
against real hardware over J-Link/serial, or against QEMU when no board is
attached.

## Quick start

```bash
git clone https://github.com/topherchris420/embedded-ai-validation-platform.git
cd embedded-ai-validation-platform
pip install -e .
eaiv run --config configs/stm32h7.yaml --suite all
```

Run a single suite:

```bash
eaiv run --config configs/default.yaml --suite tinyml
```

Inspect resolved config (after YAML `inherit` merging):

```bash
eaiv show --config configs/stm32h7.yaml
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the subsystem breakdown
and [docs/usage.md](docs/usage.md) for configuration reference and examples.

## Status

Early-stage / smoke-tested. APIs may shift. Contributions and hardware
target reports (boards tested, quirks found) are welcome via issues/PRs.

## License

MIT — see [LICENSE](LICENSE).
