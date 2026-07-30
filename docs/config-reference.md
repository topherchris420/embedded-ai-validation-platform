# Configuration Reference

Configs are YAML files passed to `eaiv run --config <file>`. A file may set
`inherit: <other.yaml>` (path relative to itself); the parent is loaded
first and deep-merged key-by-key, so children only state their overrides —
see `configs/sim.yaml` for an example.

## Check a config before you run it

```bash
eaiv config validate configs/sim.yaml            # field by field, with fixes
eaiv config validate configs/sim.yaml --suite hil  # only what that suite needs
eaiv config resolve  configs/sim.yaml            # after `inherit:` merging
```

Validation reports every problem by dotted path with a severity:

- **errors** mean the run cannot work — an unregistered `target.kind`, a
  wrong type, an out-of-range value, a WCET budget larger than its
  deadline, a missing required input;
- **warnings** mean it will run but probably not as intended — a missing
  optional model file, an unrecognised key, a deadline longer than its
  period, a setting that only applies to a different backend.

The loader itself reports malformed YAML, a missing `inherit:` parent, and
inheritance cycles by name, rather than raising a traceback.

Everything in this reference — types, defaults, descriptions, and legal
values — comes from one declarative schema
([`eaiv/configspec/schema.py`](../src/eaiv/configspec/schema.py)), which
also drives the mission builder's form. Enumerated choices are read from
the plugin registry, so a backend, filter, fault model, power monitor, or
telemetry adapter contributed by an installed package is legal
configuration and appears in the UI without any change here.

## Mission presets

`eaiv config presets` lists ready-made starting points (simulator smoke
test, full simulated release gate, firmware-only, TinyML benchmark,
sensor-fusion accuracy, HIL robustness, real-time deadlines, custom).
Mission Control's **New run** page starts from one, and **Save mission**
writes an ordinary config — plus a `mission:` block recording the suite
selection, baseline, and preset — into `missions/`. `eaiv pipeline --config`
accepts it directly.

## `target`

| Key | Values | Notes |
|---|---|---|
| `kind` | `qemu` \| `serial` \| `jlink` \| `sim` | Selects the backend (any registered `target` plugin). |
| `binary` | path | ELF/binary to flash. |
| `qemu.machine`, `qemu.cpu` | e.g. `mps2-an385`, `cortex-m3` | Passed to `qemu-system-arm -M`/`-cpu`. |
| `serial.port`, `serial.baud` | e.g. `/dev/ttyACM0`, `115200` | pyserial connection params. |
| `jlink.device`, `jlink.interface` | e.g. `STM32H743VI`, `swd` | Passed to pylink/JLinkExe. |
| `sim.dataset` | CSV path | Telemetry source for the simulated device (synthetic if omitted). |
| `sim.telemetry_lines` | int | Lines emitted per boot (default 50). |
| `sim.fail` | bool | Force a failing device (for testing the tester). |

## `firmware`

| Key | Default | Notes |
|---|---|---|
| `timeout_s` | 30 | Serial-read window per attempt. |
| `retries` | 2 | Re-flash/re-boot attempts before failing. |
| `pass_patterns` | `["PASS"]` | Substrings that mark success (firmware emits `ALL_TESTS_OK`). |
| `fail_patterns` | `["FAIL"]` | Substrings that short-circuit to failure. |

## `tinyml`

| Key | Default | Notes |
|---|---|---|
| `model` | — | Path to `.tflite`/`.onnx`; the mock backend is used when the path is empty or missing, so smoke runs work anywhere. |
| `runtime` | `tflite` | `tflite` \| `onnx` \| `mock`. Setting `mock` forces the stand-in even when a model file exists. |
| `iterations` | 50 | Timed iterations (after warmup). |
| `warmup` | 5 | Untimed warmup iterations. |
| `inputs` | — | Optional `.npy` sample; random input of the right shape when absent. |
| `power.kind` | — | Any registered `power_monitor` plugin; adds mean/peak power and energy per inference. `sim` is synthetic. |

These timings are **host-side measurements even with a real runtime** —
this suite does not execute the model on the device. Reports label them
accordingly (`measured`/`host`, or `mock`), and metrics labelled `mock`
never gate a release.

## `sensor_fusion`

| Key | Default | Notes |
|---|---|---|
| `source` | — | Replay CSV (`t_s,gx,gy,gz,ax,ay,az[,roll_ref_deg,pitch_ref_deg]`). |
| `algorithm` | `kalman` | `complementary` \| `mahony` \| `madgwick` \| `kalman` \| `ekf`, or any registered `fusion_filter` plugin. |
| `params` | `{}` | Forwarded to the filter constructor, e.g. `{beta: 0.2}` or `{alpha: 0.95}`. |
| `max_rmse_deg` | 10.0 | Roll/pitch RMSE above this fails the suite. |
| `metrics` | all | Subset of `rmse`, `drift_deg_per_min`, `lag_ms`. |

RMSE metrics are only produced when the CSV has reference columns.

## `hil`

| Key | Default | Notes |
|---|---|---|
| `source` | `datasets/imu/imu_run1.csv` | Replay dataset. |
| `algorithm`, `params` | `madgwick`, `{}` | Fusion filter evaluated under faults. |
| `faults` | `[]` | List of fault specs, applied in order (below). |
| `max_faulted_rmse_deg` | 15.0 | Pass threshold for the faulted run. |

Fault specs (`kind` plus constructor args; any registered `fault` plugin):

```yaml
faults:
  - {kind: noise, std: 0.05, fields: [gx, gy, gz], seed: 0}
  - {kind: packet_loss, probability: 0.02, seed: 1}
  - {kind: jitter, std_s: 0.002, seed: 0}
  - {kind: outage, start_s: 5.0, duration_s: 0.5}
```

## `rt_perf`

| Key | Notes |
|---|---|
| `task_set` | List of `{name, period_ms, deadline_ms, wcet_budget_ms}`. |
| `duration_s` | Profiling window. |

Expects target command-channel lines like `TASK control_loop exec_us=812
jitter_us=40`; a clearly-labeled synthetic trace is generated when no
target telemetry is available.

## `reporting`

| Key | Notes |
|---|---|
| `out_dir` | Where `report_<ts>.json`, `latest.json`, `report.{csv,md,html}`, and `runs/<run-id>/` are written. |
| `format` | Informational — every format is always produced. |

## Regression gating

`eaiv compare baseline.json reports/latest.json --max-regression-pct 10`
compares every numeric metric shared by the two reports and exits non-zero
if any worsens beyond the threshold. Metric direction comes from a suite's
declared metadata when present, and is otherwise inferred from the name
(latency/error/memory ⇒ lower is better; fps/throughput ⇒ higher is better;
unknown metrics never gate).

Metrics a suite labelled `mock` are reported but never gate: a stand-in
runtime's timings vary by orders of magnitude between runs and say nothing
about the code under review. Legacy reports declare no provenance and gate
exactly as they always did. See
[runs-and-reports.md](runs-and-reports.md#provenance-and-the-regression-gate).

For a richer comparison — compatibility checks, grouped deltas, new and
missing metrics, and a release recommendation — use
`eaiv runs compare <baseline-id> <current-id>` or Mission Control's
**Compare** page.

## `mission` (written by Mission Control)

An optional block the mission builder adds when saving. The suites ignore
it; it records intent so a saved mission can be reopened exactly as saved.

| Key | Notes |
|---|---|
| `name`, `title` | Identity in the mission list. |
| `preset` | Which preset it started from. |
| `suite` | Suite selection to run. |
| `baseline` | Baseline to gate against. |
| `telemetry_s`, `max_regression_pct` | Capture window and gate allowance. |
| `saved_at` | UTC timestamp. |
