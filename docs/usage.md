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
eaiv run --config configs/stm32h7.yaml --suite tinyml
eaiv show --config configs/stm32h7.yaml     # print resolved config as JSON
eaiv targets                                # list supported target backends
```

`eaiv run` exits with status `0` if every executed suite passed, `1`
otherwise — safe to use as a CI gate.

## Configuration reference

### `target`
| Key | Values | Notes |
|---|---|---|
| `kind` | `qemu` \| `serial` \| `jlink` | Selects the backend. |
| `binary` | path | ELF/binary to flash (or already-flashed reference for `serial`). |
| `qemu.machine`, `qemu.cpu` | e.g. `mps2-an385`, `cortex-m3` | Passed to `qemu-system-arm -M`/`-cpu`. |
| `serial.port`, `serial.baud` | e.g. `/dev/ttyACM0`, `115200` | pyserial connection params. |
| `jlink.device`, `jlink.interface` | e.g. `STM32H743VI`, `swd` | Passed to pylink/JLinkExe. |

### `firmware`
`timeout_s`, `retries`, `pass_patterns` (list of substrings), `fail_patterns`.

### `tinyml`
`model` (path to `.tflite`/`.onnx`), `runtime`, `inputs` (currently
informational — synthetic input is generated from the model's declared
input shape), `iterations`, `warmup`.

### `sensor_fusion`
`source` (CSV path — see column format below), `algorithm`
(`kalman`/`complementary`/`mahony`), `sample_rate_hz`, `metrics`.

CSV columns: `t_s, gx, gy, gz, ax, ay, az` and optionally `roll_ref_deg,
pitch_ref_deg` to enable RMSE scoring against ground truth.

### `rt_perf`
`task_set`: list of `{name, period_ms, deadline_ms, wcet_budget_ms}`.
`duration_s`: profiling window.

Expects the target's command channel to emit lines like:
```
TASK control_loop exec_us=812 jitter_us=40
```
If no target telemetry is available, a synthetic (clearly-labeled) trace is
generated instead so the suite remains runnable in CI/local dev.

### `reporting`
`format` (informational — console/JSON/HTML are currently always written),
`out_dir`.

## Adding a new target backend

1. Subclass `eaiv.targets.base.Target`, implement `flash`, `reset`,
   `run_command`, `read_serial`, `info`.
2. Register it in `eaiv.targets.build_target`'s mapping.
3. Add a `configs/*.yaml` example and a test using a fake in-memory target
   (see `tests/test_firmware.py::FakeTarget` for the pattern).

## Adding a new suite

1. Create `eaiv/<suite>/` with a class exposing `run() -> SuiteResult`.
2. Wire it into `Orchestrator.run()` and the `--suite` CLI choices.
3. Add a config section, a standalone example script, and tests.
