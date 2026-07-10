# Examples

Standalone scripts exercising the platform's main workflows. All of them
run with no hardware attached (`firmware_smoke_test.py` needs
`qemu-system-arm`).

| Example | Script | Shows |
|---------|--------|-------|
| 1. Validate an IMU fusion algorithm | `sensor_fusion_imu.py` | replay dataset → RMSE scoring across filters |
| 2. Benchmark TinyML inference | `benchmark_mobilenet.py` | latency percentiles, startup, power/energy, confidence stability |
| 3. Run HIL fault testing | `hil_fault_testing.py` | fault chains (noise, loss, jitter, outage) → accuracy degradation |
| 4. Add a new hardware target | `add_hardware_target.py` | target plugin registration → standard suites run unchanged |
| — Firmware smoke test on QEMU | `firmware_smoke_test.py` | flash/boot/pattern-match without a physical board |

```bash
pip install -e .
python examples/sensor_fusion_imu.py
python examples/benchmark_mobilenet.py
python examples/hil_fault_testing.py
python examples/add_hardware_target.py
```

The config-driven equivalents of these workflows are in
[docs/getting-started.md](../docs/getting-started.md); the same logic runs
through `eaiv run` / `eaiv pipeline` in CI.
