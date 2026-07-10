# Configuration Reference

Configs are YAML files passed to `eaiv run --config <file>`. A file may set
`inherit: <other.yaml>` (path relative to itself); the parent is loaded
first and deep-merged key-by-key, so children only state their overrides —
see `configs/sim.yaml` for an example.

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
| `model` | — | Path to `.tflite`/`.onnx`; a mock backend is used if missing so smoke runs work anywhere. |
| `runtime` | `tflite` | `tflite` \| `onnx` \| `mock`. |
| `iterations` | 50 | Timed iterations (after warmup). |
| `warmup` | 5 | Untimed warmup iterations. |

## `sensor_fusion`

| Key | Default | Notes |
|---|---|---|
| `source` | — | Replay CSV (`t_s,gx,gy,gz,ax,ay,az[,roll_ref_deg,pitch_ref_deg]`). |
| `algorithm` | `kalman` | `complementary` \| `mahony` \| `madgwick` \| `kalman` \| `ekf`, or any registered `fusion_filter` plugin. |
| `params` | `{}` | Forwarded to the filter constructor, e.g. `{beta: 0.2}` or `{alpha: 0.95}`. |
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
| `out_dir` | Where `report_<ts>.json`, `latest.json`, and `report.html` are written. |
| `format` | Informational — console/JSON/HTML are currently always produced. |

## Regression gating

`eaiv compare baseline.json reports/latest.json --max-regression-pct 10`
compares every numeric metric shared by the two reports and exits non-zero
if any worsens beyond the threshold. Metric direction is inferred from the
name (latency/error/memory ⇒ lower is better; fps/throughput ⇒ higher is
better; unknown metrics never gate).
