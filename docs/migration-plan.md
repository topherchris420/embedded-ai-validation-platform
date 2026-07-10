# Migration Plan: Embedded AI Validation Platform

This document records the repository analysis performed before the modular
re-architecture, and the incremental plan used to carry it out. It stays in
the tree as an architecture-decision record.

## 1. Repository analysis

### Reusable components (kept, extended)

| Component | Location | Assessment |
|-----------|----------|------------|
| Plugin registry | `src/eaiv/plugins/` | Sound design (metadata + factory); needed de-duplication and CLI integration |
| Config loader with `inherit:` merging | `src/eaiv/config.py` | Clean, kept as-is |
| Orchestrator / Reporter / Results | `src/eaiv/core/` | Good separation; extended with HIL suite and regression comparison |
| Fusion filters (complementary, Mahony, 1-D Kalman) | `src/eaiv/sensor_fusion/fusion.py` | Compact reference implementations; extended with Madgwick and quaternion EKF |
| Target backends (QEMU, serial, J-Link) | `src/eaiv/targets/` | Usable; QEMU enables hardware-free CI |
| Firmware tester / ELF footprint tools | `src/eaiv/firmware/` | Kept |
| RT profiler, TinyML benchmark | `src/eaiv/rt_perf/`, `src/eaiv/tinyml/` | Kept |
| Streamlit dashboard | `dashboard/python/app.py` | Kept, minor cleanup |

### Technical debt found (and fixed)

1. **Broken `Target` base class**: a refactor renamed the stored constructor
   argument from `spec` to `config`, while every subclass and
   `FirmwareTester` still read `target.spec`. Three tests failed on `main`;
   QEMU `reset()` raised `AttributeError`.
2. **Red lint job**: 12 `ruff` errors and 33 files failing `black --check`,
   so the CI lint job could never pass.
3. **Invalid CI action**: `firmware.yml` referenced
   `platformio/action pio-platform-reset@v1` — not a real action, and a
   syntax error besides. The firmware build workflow could never run.
4. **Promised-but-empty modules**: `hil/`, `benchmarks/`, `datasets/`, and
   `sensor_fusion/` (top level) contained only READMEs describing features
   that did not exist. `firmware/` had a `platformio.ini` but no source, so
   even a fixed workflow could not build anything.
5. **Duplicate target construction paths**: `build_target()` consulted the
   plugin registry, then fell back to a hard-coded factory dict that
   duplicated the registrations three lines below it. The CLI `targets`
   command hard-coded the same list a third time.
6. **Dangling references**: `configs/default.yaml` pointed at
   `datasets/imu_run1.csv` and a `.tflite` model that were not in the repo;
   the README linked to `CONTRIBUTING.md`, `docs/hardware.md`, and
   `docs/config-reference.md`, none of which existed.
7. **Dependency drift**: `requirements.txt` duplicated `pyproject.toml`
   dependencies but was missing `pydantic`.
8. **README errors**: ESP32-S3 described as "RISC-V + AI Accelerator"
   (it is a dual-core Xtensa LX7).

### Architecture decisions

- **Single Python package (`src/eaiv/`)** remains the home of all host-side
  code. Top-level directories (`firmware/`, `hil/`, `datasets/`, …) hold
  non-Python assets and module documentation, mirroring the package layout.
- **Everything constructible is a plugin.** Targets, sensors, benchmarks,
  fusion filters, and fault models register through `eaiv.plugins`; external
  packages can contribute via the `eaiv.plugins` entry-point group.
- **Hardware-agnostic by construction**: suites talk to the abstract
  `Target`; adding a board means one PlatformIO env + (optionally) one
  target plugin.
- **Reproducibility**: replay datasets are committed (or regenerable from a
  seeded generator), benchmark passes are decoupled from thresholds, and
  regression detection compares report JSON artifacts across runs.

## 2. Incremental migration steps

Each step is one reviewable commit; the platform stays green after each.

1. `fix:` repair `Target` regression, ruff errors, invalid CI action.
2. `style:` mechanical black reformat (unblocks the lint job).
3. `docs:` this migration plan.
4. `refactor:` single construction path through the plugin registry;
   CLI reads the registry; entry-point discovery for third-party plugins.
5. `feat(sensor_fusion):` Madgwick and quaternion EKF filters, filters as
   plugins, magnetometer-aware update API.
6. `feat(datasets):` seeded synthetic IMU trajectory generator, committed
   replay datasets, config paths that resolve.
7. `feat(hil):` virtual sensors, dataset replay, fault injection (noise,
   dropout, timing jitter, packet loss), simulated target, HIL suite wired
   into the orchestrator.
8. `feat(cli):` `plugins`, `flash`, `monitor`, `hil`, `datasets`, and
   `compare` (regression gate) commands.
9. `feat(firmware):` C++ HAL (board + sensor abstraction), serial
   test-protocol application buildable for every supported board.
10. `docs:` CONTRIBUTING, ROADMAP, hardware and config references, README
    corrections.

## 3. Out of scope (tracked in ROADMAP)

- On-device TFLite-Micro benchmark harness (host-side runtimes work today).
- Power measurement drivers (INA226/PPK2) — interface defined, drivers TBD.
- Raspberry Pi Zero 2 W target (Linux-class; needs SSH target backend).
- MkDocs-published API documentation site.
