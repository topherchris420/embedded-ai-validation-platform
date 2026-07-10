# Hardware-in-the-Loop (HIL) Testing Module

Python-based simulation layer (`eaiv.hil`) for testing embedded validation
logic without real hardware.

## Features

- **Sample streams** — replay recorded CSV logs or generate seeded synthetic
  IMU trajectories
- **Fault injection** — composable, deterministic fault models:
  - `noise` — additive Gaussian sensor noise
  - `packet_loss` — random independent sample loss
  - `jitter` — Gaussian timing jitter (timestamps stay monotonic)
  - `outage` — sensor silent for a time window
- **Simulated target** — a software `Target` plugin (`kind: sim`) that
  emulates a device booting, streaming telemetry, and reporting a test
  verdict over serial, so the firmware suite runs hardware-free in CI
- **Robustness suite** — replays a dataset clean and faulted through a
  fusion algorithm and reports the accuracy degradation

## Python API

```python
from eaiv.hil import Simulator, build_fault, replay_csv

sim = Simulator(
    replay_csv("datasets/imu/imu_run1.csv"),
    [
        build_fault({"kind": "noise", "std": 0.05}),
        build_fault({"kind": "packet_loss", "probability": 0.02, "seed": 1}),
        build_fault({"kind": "jitter", "std_s": 0.002}),
    ],
)
result = sim.run()
print(result.emitted, result.dropped, f"{result.drop_rate:.1%}")
```

## Config-driven usage

```yaml
# configs/default.yaml
hil:
  source: datasets/imu/imu_run1.csv
  algorithm: madgwick
  params: {beta: 0.2}
  faults:
    - {kind: noise, std: 0.05, fields: [gx, gy, gz, ax, ay, az]}
    - {kind: packet_loss, probability: 0.02, seed: 1}
    - {kind: jitter, std_s: 0.002}
  max_faulted_rmse_deg: 15.0
```

```bash
eaiv run --config configs/default.yaml --suite hil
```

## Simulated firmware runs

```yaml
target:
  kind: sim
  binary: build/firmware.elf
  sim:
    telemetry_lines: 50
```

```bash
eaiv run --config configs/sim.yaml --suite firmware
```

## Extending

Fault models are `fault` plugins — register new ones without touching core
code:

```python
from eaiv.hil import Fault
from eaiv.plugins import register_plugin

@register_plugin("spike", "fault", "Occasional large outliers")
class SpikeFault(Fault):
    def __init__(self, magnitude: float = 5.0, period_s: float = 1.0) -> None: ...
    def apply(self, t_s, values): ...
```
