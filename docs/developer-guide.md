# Developer Guide

How the repository is laid out, how to work in it, and how the pieces fit.

## Repository layout

The platform is one Python package plus non-Python asset trees that mirror
it. If you think in terms of the conceptual architecture (firmware /
benchmarks / sensor fusion / HIL / dashboard / python / plugins), this is
where each piece lives:

| Concern | Host-side code | Assets / docs |
|---------|----------------|---------------|
| Firmware (HAL, drivers, app) | — | `firmware/` (PlatformIO project) |
| Benchmarks (inference, memory, latency, power, startup) | `src/eaiv/tinyml/`, `src/eaiv/benchmarks/`, `src/eaiv/power/` | `benchmarks/suites/` (definitions as YAML) |
| Sensor fusion (filters, replay) | `src/eaiv/sensor_fusion/` | `sensor_fusion/README.md` |
| Datasets (generation, replay logs) | `src/eaiv/datasets/` | `datasets/imu/*.csv` |
| HIL (simulator, virtual sensors, faults, runners) | `src/eaiv/hil/` | `hil/README.md` |
| Telemetry (protocol, adapters, collection) | `src/eaiv/telemetry/` | — |
| Dashboard | `src/eaiv/dashboard/` (data layer) | `dashboard/python/app.py` (Streamlit UI) |
| Python tooling (CLI, flashing, monitoring, automation) | `src/eaiv/cli.py`, `src/eaiv/firmware/`, `src/eaiv/targets/` | — |
| Plugin system | `src/eaiv/plugins/` | [plugin-development.md](plugin-development.md) |
| CI | — | `.github/workflows/`, `ci/check_docs.py` |

Everything importable lives under `src/eaiv/` (single installable package,
`pip install -e .`); top-level directories hold what cannot or should not
be a Python module — firmware sources, datasets, suite definitions,
workflows — each with a README documenting its part of the system.

## Environment

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"          # dev tools + dashboard + tinyml extras
pip install platformio            # only for firmware work
```

## The development loop

```bash
pytest tests/ -q                 # unit + integration tests (hardware-free)
ruff check . && black --check .  # lint/format (CI-enforced)
mypy src/eaiv                    # strict-ish typing (CI-enforced)
python ci/check_docs.py          # markdown link validation (CI-enforced)
eaiv run --config configs/sim.yaml --suite all   # end-to-end smoke
cd firmware && pio run           # builds all four board environments
```

Everything above runs with no hardware attached: the `sim` target
emulates a device end-to-end (boot, telemetry, verdict, commands), QEMU
covers Cortex-M binaries, and the mock TinyML runtime stands in for
missing model files.

## Key flows

### Validation run

`eaiv run` → `Orchestrator` builds the target via the plugin registry,
runs each requested suite (`firmware`, `tinyml`, `fusion`, `hil`,
`memory`, `rt`), and hands the `AggregateResult` to `Reporter`, which
writes console + JSON + CSV + Markdown + HTML artifacts under `reports/`.

### Telemetry capture

`eaiv monitor --csv/--summary` → `TelemetryCollector` reads the target's
serial stream through a `telemetry_adapter` plugin into typed records
(`BOOT`/`T`/`B`/`M`/`U`/verdict lines) → per-field statistics or a CSV
the dashboard plots.

### Regression gating

Keep a known-good `reports/latest.json` as a baseline artifact; gate CI
with `eaiv compare baseline.json reports/latest.json`. Metric direction
is inferred from the metric name (see `eaiv.core.regression`). The
dashboard's Compare page is the interactive view of the same engine.

## Testing strategy

- Every suite has a **hardware-free path** exercised in CI (sim target,
  mock runtime, committed replay datasets); tests assert on observable
  behavior — suite results, CLI output, serial protocol — not internals.
- Determinism is a hard rule: seeded RNGs everywhere; the committed
  datasets are regenerable bit-for-bit.
- Firmware is compile-verified for all four boards on every firmware
  change; on-device behavior is exercised through the shared serial
  protocol, so `FirmwareTester` tests against `SimulatedTarget` cover the
  host-side logic.
- The dashboard's data layer (`eaiv.dashboard`) is unit-tested; the
  Streamlit layer stays thin.

## Versioning and commits

- [Conventional Commits](https://www.conventionalcommits.org/); one
  logical change per commit; keep the tree green at every commit.
- Version lives in `pyproject.toml` and `eaiv.__version__` (and
  `kVersion` in the firmware app).

See also: [architecture.md](architecture.md),
[config-reference.md](config-reference.md),
[plugin-development.md](plugin-development.md),
[hardware.md](hardware.md), [../CONTRIBUTING.md](../CONTRIBUTING.md),
[../ROADMAP.md](../ROADMAP.md).
