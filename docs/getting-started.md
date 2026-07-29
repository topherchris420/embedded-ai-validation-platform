# Getting Started

From clone to a diagnosed validation result in three commands — no
hardware, no model weights, no QEMU.

## Install

```bash
git clone https://github.com/topherchris420/embedded-ai-validation-platform.git
cd embedded-ai-validation-platform
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
```

## Check the environment

```bash
eaiv doctor
```

Reports the Python version, required and optional dependencies,
PlatformIO/QEMU/J-Link availability, serial ports, plugin discovery, and
whether the report directory is writable — with a concrete fix for
anything missing. Exit code 0 means everything *required* works; warnings
about optional extras are fine.

## Run the guided demo

```bash
eaiv demo
```

Three real validations against the simulated device:

1. a reference run, promoted to the `demo-baseline` baseline;
2. a candidate run gated against it;
3. a run whose sensor stream is degraded until the fusion filter genuinely
   leaves its 15° error envelope — a real threshold crossing, not a
   hard-coded failure.

The third run failing is the point: it gives you something to diagnose.
Every metric the demo produces is labelled **simulated**, because none of
it was measured on hardware.

## Open Mission Control

```bash
eaiv dashboard
```

The landing page answers, before you click anything: is this safe to ship,
what changed since the baseline, what was it tested on, what is the worst
problem, what to do next, and when validation last passed. From there you
can build and launch a new mission, watch it run, read the diagnosis,
compare runs, and promote a baseline — see the
[dashboard guide](../dashboard/README.md).

If you have no runs yet, Mission Control offers the demo as a button
rather than telling you to go back to the terminal.

## The same thing from the command line

```bash
# Every suite against the simulated device
eaiv run --config configs/sim.yaml --suite all

# The full recorded pipeline: validate -> telemetry -> gate -> promote
eaiv pipeline --config configs/sim.yaml --telemetry-duration 2 \
              --save-baseline first --run-name "first gate"

# Now use it as a regression gate
eaiv pipeline --config configs/sim.yaml --baseline first
echo $?    # 0 = no regressions; non-zero fails your CI job

# Inspect what was recorded
eaiv runs list
eaiv runs show <run-id>
eaiv runs compare <baseline-run-id> <candidate-run-id>
```

`eaiv pipeline` records each run under `reports/runs/<run-id>/` with its
manifest, event log, artifacts, and the exact resolved configuration it
used. See [runs and reports](runs-and-reports.md).

## Build a mission without editing YAML

Presets cover the common intents:

```bash
eaiv config presets
```

| Preset | Answers |
|--------|---------|
| `sim-smoke` | Does the firmware still boot and report a verdict? |
| `sim-release-gate` | Would this change pass CI? Did anything regress? |
| `firmware-only` | Does this build boot on real hardware? |
| `tinyml-benchmark` | How fast is this model, and how heavy is its tail? |
| `fusion-accuracy` | How much orientation error does this filter accumulate? |
| `hil-robustness` | How much accuracy is lost under degraded sensors? |
| `rt-deadlines` | Did any task miss its deadline? |
| `custom` | Whatever you configure it to answer. |

Pick one in Mission Control's **New run** page, adjust the fields, review
the resolved YAML, and launch. "Save mission" writes an ordinary config
file that `eaiv pipeline --config` accepts, so anything you build in the
browser runs unchanged in CI.

## Check a configuration before you run it

```bash
eaiv config validate configs/sim.yaml     # field-by-field, with fixes
eaiv config resolve  configs/sim.yaml     # after `inherit:` merging
```

## Work with real data

```bash
# A reproducible IMU dataset (with a metadata sidecar)
eaiv datasets generate --profile aggressive --seed 7 -o mylog.csv
eaiv datasets validate mylog.csv

# Capture live telemetry from the (simulated or real) device
eaiv monitor --config configs/sim.yaml --summary --csv capture.csv
```

Drop either file into Mission Control's **Telemetry Lab** to check its
sampling rate, find gaps and outliers, and score orientation estimates
against ground truth.

## Move to real hardware

Simulated results are useful for catching regressions in logic. They
cannot certify timing, memory, or power behaviour on a device — the
platform says so on every screen and in every report. When you are ready:

1. Build and flash the validation firmware:
   ```bash
   pip install platformio
   cd firmware && pio run -e esp32 && cd ..
   eaiv flash firmware/.pio/build/esp32/firmware.bin --config configs/esp32.yaml
   ```
2. Create `configs/esp32.yaml` (inherit from default, set
   `target: {kind: serial, serial: {port: /dev/ttyUSB0}}` — see
   [config-reference.md](config-reference.md)).
3. Re-run the exact same commands with your config. Everything — suites,
   telemetry, baselines, dashboard — is target-agnostic.

Metrics gathered through a real transport are labelled **measured**;
`sim` and `qemu` are both labelled **simulated**, because an emulator
models timing rather than exhibiting it.

## Next steps

- [Dashboard guide](../dashboard/README.md) — the Mission Control workflow
- [Runs and reports](runs-and-reports.md) — run storage, report schema,
  events, provenance, backward compatibility
- [Benchmarking guide](benchmarking.md) — metrics, baselines, CI gating
- [Configuration reference](config-reference.md) — every field, its
  default, and its validation
- [Plugin development](plugin-development.md) — add boards, filters,
  faults, power monitors without touching core code
- [Hardware support](hardware-support.md) — supported boards and
  transports
- Worked examples: [../examples/README.md](../examples/README.md)
