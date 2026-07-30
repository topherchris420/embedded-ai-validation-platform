# Usage

## Installation

```bash
pip install -e .                 # core
pip install -e ".[dev]"          # + pytest/ruff/black/mypy
pip install -e ".[dashboard]"    # + streamlit/plotly/pandas (Mission Control)
pip install -e ".[jlink]"        # + pylink-square for J-Link targets
pip install -e ".[tinyml]"       # + onnxruntime / tflite-runtime
pip install -e ".[all]"          # everything
```

Then confirm the environment, with a fix for anything missing:

```bash
eaiv doctor
```

QEMU targets additionally require the system package:

```bash
sudo apt-get install qemu-system-arm
```

## CLI

```bash
eaiv run --config configs/default.yaml --suite all
eaiv run --config configs/sim.yaml --suite firmware   # hardware-free
eaiv run --config configs/default.yaml --suite hil    # fault-injection run
eaiv show --config configs/stm32h7.yaml     # print resolved config as JSON
eaiv plugins                                # list all registered plugins
eaiv targets                                # list target backends only
eaiv flash build/firmware.elf --config configs/stm32h7.yaml
eaiv monitor --config configs/esp32.yaml --duration 10
eaiv datasets generate --profile gentle --duration 20 --seed 42 -o log.csv
eaiv compare baseline.json reports/latest.json --max-regression-pct 10
eaiv baseline save reports/latest.json --name release-1   # named baselines
eaiv baseline list
eaiv datasets validate datasets/                          # metadata checks
eaiv pipeline --config configs/sim.yaml --baseline release-1  # full CI flow
```

### Operations and inspection

```bash
eaiv doctor                        # environment diagnosis with fixes
eaiv doctor --config configs/sim.yaml --json
eaiv demo                          # three simulated runs, one of them failing
eaiv dashboard                     # launch EAIV Mission Control

eaiv runs list                     # recorded runs, newest first
eaiv runs show <run-id> --logs     # stages, artifacts, diagnosis, event log
eaiv runs compare <base> <cur> --format markdown

eaiv config validate configs/sim.yaml           # field-by-field
eaiv config validate configs/sim.yaml --suite hil
eaiv config resolve  configs/sim.yaml -o resolved.yaml
eaiv config presets                             # mission presets
```

## Exit codes

| Command | 0 | non-zero |
|---------|---|----------|
| `eaiv run` | every executed suite passed | any suite failed |
| `eaiv pipeline` | every stage, suite, and the gate passed | anything failed or the run was cancelled |
| `eaiv compare`, `eaiv runs compare` | no gated regressions | regressions, or the runs are not comparable |
| `eaiv config validate` | no errors (warnings allowed) | at least one error |
| `eaiv doctor` | everything required works | something required is broken |
| `eaiv datasets validate` | every dataset valid | any problem found |
| `eaiv demo` | the demo ran as designed | the demo itself misbehaved |

`eaiv demo` exits 0 even though its third run fails: that failure is the
demonstration, not a fault.

`eaiv run` writes report artifacts only. `eaiv pipeline` additionally
records the run under `<report-dir>/runs/<run-id>/` — manifest, event log,
artifacts, and the resolved config it used. Pass `--no-record` to opt out.
See [runs-and-reports.md](runs-and-reports.md).

## Configuration reference

Moved to [config-reference.md](config-reference.md), which covers every
suite section including `hil` fault specs and the `sim` target.

## Adding a new target backend

1. Subclass `eaiv.plugins.targets.Target`, implement `flash`, `reset`,
   `run_command`, `read_serial`, `info`.
2. Register it: `@register_plugin("myboard", "target", "My board")` — or
   ship it in an external package exposing the module via the
   `eaiv.plugins` entry-point group.
3. Add a `configs/*.yaml` example and a test using a fake in-memory target
   (see `tests/test_firmware.py::FakeTarget` for the pattern).

## Adding a new suite

An external suite needs no core change: register a `suite` plugin and list
it under `extra_suites` in the config.

```python
from eaiv.plugins import register_plugin
from eaiv.core.results import SuiteResult

@register_plugin("my_suite", "suite", "What it validates")
class MySuite:
    def __init__(self, spec: dict) -> None:
        self.spec = spec

    def run(self) -> SuiteResult:
        ...
```

```yaml
extra_suites:
  my_suite: {threshold: 3.0}
```

Declare where your metrics came from with `metric_meta` — see
[plugin-development.md](plugin-development.md#declaring-metric-provenance).

For a suite that belongs in the core set:

1. Create `eaiv/<suite>/` with a class exposing `run() -> SuiteResult`.
2. Add it to `BUILTIN_SUITES` and the `builders` map in
   `Orchestrator.run()`, plus `SUITE_CONFIG_SECTION`.
3. Add a `SectionSpec` to `eaiv/configspec/schema.py` so it validates and
   appears in the mission builder.
4. Add a standalone example script and tests.
