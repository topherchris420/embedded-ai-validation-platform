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
        ┌──────────────┬───────────┼───────────────┬───────────────┐
        ▼              ▼           ▼               ▼               ▼
 eaiv.targets   eaiv.firmware  eaiv.tinyml   eaiv.sensor_fusion  eaiv.rt_perf
 (qemu/serial/   (flash, boot,  (benchmark    (Kalman/comp/       (WCET, jitter,
  jlink)         pattern match) latency/mem)  Mahony filters)     deadline miss)
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

New backends implement the four abstract methods in `eaiv.targets.base.Target`
and register in `eaiv.targets.build_target`.

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
  through a Kalman / complementary / Mahony filter and reports RMSE
  against a reference column (if present), drift, and sample period.
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
