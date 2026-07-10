# Getting Started

From zero to a full validation run in about five minutes — no hardware,
no model weights, no QEMU required.

## Install

```bash
git clone https://github.com/topherchris420/embedded-ai-validation-platform.git
cd embedded-ai-validation-platform
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
```

## First validation run (simulated device)

```bash
eaiv run --config configs/sim.yaml --suite all
```

This boots a fully software-simulated device, runs all six suites
(firmware smoke test, TinyML benchmark, sensor fusion, HIL fault
injection, memory footprint, RT profiling), and writes reports to
`reports/` in five formats (console, JSON, CSV, Markdown, HTML).

Look at what you got:

```bash
cat reports/report.md
eaiv plugins            # everything registered: targets, filters, faults, ...
```

## The full pipeline in one command

```bash
eaiv pipeline --config configs/sim.yaml --telemetry-duration 2 --save-baseline first
```

Runs validate → telemetry capture → report, then promotes the run to a
named baseline. Now make it a regression gate:

```bash
eaiv pipeline --config configs/sim.yaml --baseline first
echo $?    # 0 = no regressions; non-zero fails your CI job
```

## Explore the results

```bash
pip install -e ".[dashboard]"
streamlit run dashboard/python/app.py
```

Overview tiles, latency distributions, power metrics, metric history,
per-hardware comparison, and an interactive baseline diff with a
BETTER/WORSE release verdict.

## Work with real data

```bash
# Generate a reproducible IMU dataset (with metadata sidecar)
eaiv datasets generate --profile aggressive --seed 7 -o mylog.csv
eaiv datasets validate mylog.csv

# Capture live telemetry from the (simulated or real) device
eaiv monitor --config configs/sim.yaml --summary --csv capture.csv
```

## Move to real hardware

1. Build and flash the validation firmware:
   ```bash
   pip install platformio
   cd firmware && pio run -e esp32 && cd ..
   eaiv flash firmware/.pio/build/esp32/firmware.bin --config configs/esp32.yaml
   ```
2. Create `configs/esp32.yaml` (inherit from default, set
   `target: {kind: serial, serial: {port: /dev/ttyUSB0}}` — see
   [config-reference.md](config-reference.md)).
3. Re-run the exact same commands as above with your config. Everything —
   suites, telemetry, baselines, dashboard — is target-agnostic.

## Next steps

- [Benchmarking guide](benchmarking.md) — metrics, baselines, CI gating
- [Plugin development](plugin-development.md) — add boards, filters,
  faults, power monitors without touching core code
- [Hardware support](hardware-support.md) — supported boards and
  transports
- Worked examples: [../examples/README.md](../examples/README.md)
