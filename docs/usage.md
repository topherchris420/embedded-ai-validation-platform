# Usage

## Installation

```bash
pip install -e .                 # core
pip install -e ".[dev]"          # + pytest/ruff/mypy
pip install -e ".[jlink]"        # + pylink-square for J-Link targets
pip install -e ".[tinyml]"       # + onnxruntime / tflite-runtime
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

`eaiv run` exits with status `0` if every executed suite passed, `1`
otherwise — safe to use as a CI gate.

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

1. Create `eaiv/<suite>/` with a class exposing `run() -> SuiteResult`.
2. Wire it into `Orchestrator.run()` and the `--suite` CLI choices.
3. Add a config section, a standalone example script, and tests.
