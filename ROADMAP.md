# Roadmap

The goal: the open-source reference implementation for embedded AI
validation — pytest + PlatformIO + MLPerf Tiny + hardware telemetry for
resource-constrained devices.

## Done (v0.4)

**Validation workflow**

- Validation runs as first-class objects: `RunManifest` with identity,
  timing, target, resolved config, stage results, artifacts, provenance,
  and structured failure detail; atomic writes into
  `reports/runs/<run-id>/`; abandoned runs reconciled to `interrupted`
  instead of left looking active
- Observable execution: typed `PipelineEvent` stream with pluggable sinks
  (memory, callback, JSONL, composite), monotonic per-run sequence numbers,
  and cooperative cancellation that works across processes through a file
  in the run directory
- Deterministic insight engine: evidence-backed findings with severity,
  category, impact, confidence, and a recommended action, ordered by an
  explicit priority table — every conclusion unit-testable
- Release decision: compatibility checks (target, provenance, input
  hashes, suite coverage, platform version) before any delta is trusted,
  plus grouped comparisons, new/missing metric detection, a recommendation,
  and Markdown/JSON export
- Typed configuration schema driving field-level validation, the mission
  builder's form, and the configuration reference from one declaration;
  eight mission presets; saved missions that are ordinary runnable configs
- Report schema v2 with reproduction context (resolved config, host, git,
  SHA-256 input hashes, thresholds, plugin versions) and per-metric unit,
  direction, and provenance; legacy reports normalized on read
- Measurement provenance end to end: every metric labelled `measured`,
  `simulated`, `estimated`, or `mock` with its source; `mock` metrics never
  gate a release; the verdict never says "ready to ship" for a run that is
  not fully measured
- EAIV Mission Control: Mission Control, New run, Live run, Results &
  Diagnosis, Compare, Telemetry Lab, Baselines, Hardware & plugins — over a
  Streamlit-free, unit-tested data layer
- Operational commands: `eaiv doctor`, `eaiv demo`, `eaiv dashboard`,
  `eaiv runs list|show|compare`, `eaiv config validate|resolve|presets`

**Platform (from v0.3, unchanged and still current)**

- Plugin architecture (targets, fusion filters, fault models, power
  monitors, telemetry adapters, suites) with entry-point discovery
- Suites: firmware smoke/regression, TinyML benchmarking (host runtimes),
  sensor-fusion replay scoring, RT profiling, HIL robustness, static memory
- Fusion filters: complementary, Mahony, Madgwick, 1-D Kalman, 4-state EKF
  with gyro-bias estimation
- Deterministic dataset generator + committed replay logs with ground truth
- HIL fault injection (noise, packet loss, jitter, outage) and a simulated
  target running the full firmware suite hardware-free
- Firmware: header-only C++ HAL + validation app building for ESP32,
  ESP32-S3, STM32H7, RPi Pico; on-device fusion benchmark, memory/uptime
  stats in the serial protocol
- Telemetry pipeline: typed protocol parser, per-board adapters, collector
  with summaries and CSV export
- Power measurement interface with a simulated monitor
- Static memory-footprint suite with ROM/RAM budget gates
- Reports in console/JSON/CSV/Markdown/HTML
- Python 3.12; ruff (explicitly pinned rule set), black, and mypy
  (`disallow_untyped_defs`, `check_untyped_defs`, `warn_return_any`,
  `no_implicit_optional` — not `strict`) enforced in CI, alongside docs
  link validation, dataset validation, a simulated release gate, and the
  guided demo

## Next (v0.5)

- **On-device TinyML**: TFLite-Micro benchmark harness in the firmware app,
  reporting on-device latency and RAM through the serial protocol. This is
  the single largest honesty gap left: today's TinyML numbers are
  host-side, and labelled as such
- **Power hardware drivers**: INA226 and Nordic PPK2 behind the existing
  `power_monitor` interface, so power metrics can be `measured` rather than
  `simulated`
- **Raspberry Pi Zero 2 W target**: SSH/Linux target backend (flash =
  deploy, serial = journald/stdout)
- **Physical IMU drivers**: MPU-6050 and LSM6DS3 implementations of `IImu`
- **Magnetometer-aware fusion**: mag input for Madgwick/EKF yaw correction
- **Run retention policy**: age/count-based pruning of `reports/runs/` and
  an archive format for long-term storage
- **Baseline promotion in CI**: a recipe storing baselines as workflow
  artifacts, with the gate reading the previous green run automatically

## Later

- MkDocs documentation site with generated API reference
- Live serial telemetry view in Mission Control (streaming rather than
  incrementally refreshed)
- Multi-run trend analysis: per-metric history with change-point detection
  across many runs, not just a pair
- QEMU semihosting harness for cycle-accurate Cortex-M profiling
- MLPerf Tiny workload pack (keyword spotting, visual wake words, anomaly
  detection) with reference models
- Camera/microphone virtual sensors for HIL
- Zephyr and ESP-IDF (non-Arduino) firmware variants

Contributions in any of these areas are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).
