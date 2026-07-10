# Hardware-in-the-Loop (HIL) Testing Module

Python-based hardware simulator for testing embedded firmware without real hardware.

## Features

- **Virtual Sensors** - Generate synthetic sensor data
- **Fault Injection** - Test error handling
  - Sensor noise
  - Dropouts
  - Timing jitter
  - Packet loss
- **Dataset Replay** - Play back recorded sensor logs
- **Firmware Automation** - Run tests automatically
- **Result Collection** - Capture and analyze test results

## Architecture

```
hil/
├── simulator/      # Sensor/actuator simulation
├── faults/         # Fault injection engine
├── replay/          # Dataset replay
├── injector/       # Serial/network injection
└── runner/         # Test orchestration
```

## Usage

### Python API

```python
from eaiv.hil import Simulator, VirtualSensor, FaultInjector

# Create simulator
sim = Simulator(config)

# Add virtual sensors
imu = VirtualSensor("imu", config)
imu.set_replay_data(load_dataset("imu_run1.csv"))
sim.add_sensor(imu)

# Inject faults
injector = FaultInjector(sim)
injector.add_fault("imu_noise", noise_level=0.1)
injector.add_fault("timing_jitter", jitter_ms=5)

# Run firmware test
result = sim.run_firmware("build/firmware.elf")
print(result.passed)
```

### CLI Usage

```bash
# Run HIL test
eaiv hil run --firmware build/firmware.elf --simulator esp32

# Replay dataset with fault injection
eaiv hil replay --dataset datasets/imu_run1.csv --faults noise,jitter

# Compare with baseline
eaiv hil compare --baseline results/baseline.json --current results/current.json
```

## Fault Types

| Fault | Description | Parameters |
|-------|-------------|------------|
| `noise` | Add Gaussian noise | `std_dev`, `mean` |
| `drift` | Gradual sensor drift | `rate_per_min`, `axis` |
| `dropout` | Random data dropouts | `probability`, `duration` |
| `stuck` | Stuck sensor value | `value`, `duration` |
| `jitter` | Timing variation | `max_jitter_ms` |
| `packet_loss` | Network packet loss | `loss_rate` |
| `corruption` | Data corruption | `bit_flip_probability` |

## Test Scenarios

```yaml
hil:
  simulator: esp32
  firmware: build/firmware.elf
  sensors:
    - name: imu0
      type: imu
      replay: datasets/imu_run1.csv
  faults:
    - type: noise
      target: imu0
      params:
        std_dev: 0.05
  duration_s: 60
```

## Integration with CI

```yaml
# .github/workflows/hil-test.yml
name: HIL Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run HIL tests
        run: eaiv hil run --firmware build/firmware.elf
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: hil-results
          path: reports/hil/
```