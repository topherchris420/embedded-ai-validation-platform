# Architecture

```
                         ┌─────────────────────┐
                         │       eaiv.cli       │
                         │  (click entry point) │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │  eaiv.core.Orchestrator │
                         │  builds target, runs   │
                         │  requested suites,     │
                         │  aggregates results    │
                         └──────────┬───────────┘
                                    │
   ┌───────────┬───────────┬─────┼─────────┬───────────────┬─────────────┐
   ▼           ▼           ▼     ▼         ▼               ▼             ▼
eaiv.targets eaiv.firmware eaiv.tinyml eaiv.sensor_fusion eaiv.rt_perf eaiv.hil
(qemu/serial (flash, boot, (benchmark  (compl/Mahony/     (WCET,       (faults,
 /jlink/sim) pattern match) lat/mem)   Madgwick/KF/EKF)   jitter)      replay, sim)
                                 │
     everything above is constructed through eaiv.plugins (registry +
     entry-point discovery); eaiv.datasets provides seeded replay logs
                                 │
                         ┌──────────▼───────────┐
                         │  eaiv.core.Reporter    │
                         │  console / JSON / HTML │
                         └────────────────────────┘
```

## Targets (`eaiv.targets`)

A `Target` is anything that can `flash()`, `reset()`, `run_command()`, and
`read_serial()`. Three backends ship out of the box:

- **`qemu`** — spawns `qemu-system-arm`, talks over stdin/stdout. No
  hardware required; used for CI and for developing suites without a
  board attached.
- **`serial`** — talks to a physical board over UART (pyserial). Assumes
  the binary is already flashed by a board-specific tool, or performs a
  minimal DTR-toggle reset.
- **`jlink`** — uses `pylink-square` if installed, otherwise shells out to
  `JLinkExe`/`JLinkCommander`. Real-time task telemetry (`rt_perf`) would
  normally be read back over RTT here; the current implementation leaves
  that as a documented stub since RTT block addresses are firmware- and
  board-specific.

- **`sim`** — in-process simulated device (`eaiv.hil.SimulatedTarget`):
  boots, streams telemetry from a dataset or the synthetic generator, and
  reports a test verdict. Lets the firmware suite run with zero external
  dependencies.

New backends implement the abstract methods of `eaiv.plugins.targets.Target`
and register with `@register_plugin("<name>", "target", ...)` — the config's
`target.kind` resolves through the plugin registry.

## Suites

Each suite is a small class with a `run() -> SuiteResult` method, so suites
compose independently of the CLI and can be imported and run directly (see
`examples/`).

- **`firmware.FirmwareTester`** — flashes a binary, resets, and watches
  serial output for configurable pass/fail regex patterns, with retries.
- **`tinyml.TinyMLBenchmark`** — loads a `.tflite`/`.onnx` model (or falls
  back to a deterministic mock runtime if the file/runtime isn't
  available), times N inference iterations after a warmup period, and
  reports latency percentiles, throughput, model size, and a rough MAC
  estimate.
- **`sensor_fusion.FusionExperiment`** — replays a recorded IMU CSV
  through any registered fusion filter and reports RMSE
  against a reference column (if present), drift, and sample period.
- **`hil.HILExperiment`** — replays a dataset clean and through a
  configured fault chain (noise, packet loss, jitter, outages), scores a
  fusion filter on both, and reports the accuracy degradation.
- **`rt_perf.RTProfiler`** — parses `TASK <name> exec_us=<n> jitter_us=<n>`
  lines from the target's command channel (or generates a synthetic trace
  when no target/telemetry is available) and reports WCET, deadline
  misses, and jitter per task.

## Reporting (`eaiv.core.reporter.Reporter`)

Every run produces three artifacts in `reports/` (or `--report-dir`):
a Rich console table, a timestamped JSON file (plus a stable `latest.json`
for CI diffing), and a static `report.html` page.

## Configuration (`eaiv.config`)

YAML configs support a single-level `inherit: other.yaml` key. The parent
is loaded and deep-merged with the child so environment-specific configs
(e.g. `configs/stm32h7.yaml`) only need to specify what differs from
`configs/default.yaml`.

## Plugin system (`eaiv.plugins`)

Targets, fusion filters, and fault models are all constructed through a
single registry keyed by `(plugin_type, name)`. Built-ins self-register on
import; external packages contribute via the `eaiv.plugins` entry-point
group, loaded by `load_entry_point_plugins()`. `eaiv plugins` lists
everything registered.

## Datasets (`eaiv.datasets`) and HIL (`eaiv.hil`)

The dataset generator produces seeded, analytically-derived IMU logs with
ground-truth orientation; committed logs under `datasets/imu/` are exactly
reproducible. The HIL layer streams those logs (or live synthetic data)
through composable fault models and into either fusion scoring or a fully
simulated target device — see [../hil/README.md](../hil/README.md).
