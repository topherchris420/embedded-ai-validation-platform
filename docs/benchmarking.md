# Benchmarking Guide

How the platform measures embedded AI workloads, what the numbers mean,
and how to keep releases honest with baselines.

## Metric categories

### Model performance (`tinyml` suite)

| Metric | Meaning |
|--------|---------|
| `mean_ms`, `p50_ms`, `p90_ms`, `p95_ms`, `p99_ms`, `min_ms`, `max_ms` | inference latency distribution |
| `stdev_ms` | inference variance |
| `throughput_ips` / `fps` | inferences per second from mean latency |
| `confidence_stability` | max per-element std of the output vector across repeated runs on one fixed input; 0.0 = bit-stable, growth indicates numeric noise (uninitialized buffers, racy accelerators) |
| `estimated_macs` | crude dense-equivalent MAC lower bound |
| `model_size_bytes` | model file size |

### Runtime (`tinyml` suite)

| Metric | Meaning |
|--------|---------|
| `startup_ms` | cold model load through first completed inference |

On-device boot time comes from the firmware's `U boot_ms=` protocol line
(`eaiv monitor --summary`).

### Memory (`memory` suite + `tinyml`)

| Metric | Meaning |
|--------|---------|
| `rom_kb`, `ram_static_kb` | ELF section analysis (.text/.rodata/.data, .data/.bss) |
| `model_flash_kb`, `total_flash_kb` | model storage cost on top of code |
| `tensor_arena_est_kb` | TFLite tensor-memory floor (real TFLM arenas add scratch + padding) |

Budget gates: `memory.max_rom_kb` / `memory.max_ram_kb` fail the suite
when exceeded.

### Power (`tinyml.power`, any `power_monitor` plugin)

| Metric | Meaning |
|--------|---------|
| `mean_power_mw`, `peak_power_mw` | supply-rail draw over the timed loop |
| `energy_per_inference_mj` | trace energy divided by inference count |

The `sim` monitor gives deterministic numbers with no instrumentation;
INA226/PPK2 drivers implement the same `PowerMonitor` interface
([plugin-development.md](plugin-development.md)).

## Runtimes

`.tflite` runs on tflite-runtime (or TensorFlow's interpreter), `.onnx`
on ONNX Runtime. A missing model file falls back to a deterministic mock
so pipelines stay runnable anywhere — mock results are flagged with
`"backend": "mock"`.

## Cross-board comparability

Every report embeds `meta.target` (name/arch/clock) and `meta.eaiv_version`.
The dashboard's "By hardware" chart compares the latest value of any
metric across boards; benchmark definitions under `benchmarks/suites/`
pin iteration counts and seeds so runs differ only by hardware.

## Reproducibility rules

- Fixed seeds everywhere (`inputs`, datasets, fault chains, simulated power).
- Warmup iterations are excluded from stats (`tinyml.warmup`).
- Confidence stability runs outside the timed loop, so enabling it does
  not perturb latency numbers.

## Baselines and CI gating

```bash
eaiv run --config benchmarks/suites/inference-sim.yaml --suite tinyml
eaiv baseline save reports/latest.json --name release-0.4-esp32

# later, in CI:
eaiv pipeline --config benchmarks/suites/inference-sim.yaml \
    --suite tinyml --baseline release-0.4-esp32 --max-regression-pct 10
```

Direction is inferred per metric (latency/error/memory lower-is-better,
fps/accuracy higher-is-better, unknown metrics never gate). The exit code
is the gate; the Markdown report in the CI job summary is the explanation.
Keep one baseline per board per release — comparing across boards is the
dashboard's job, not the gate's.

## Adding a benchmark

Register a `suite` plugin and list it under `extra_suites` in config —
see [plugin-development.md](plugin-development.md). Its metrics
automatically flow into reports, baselines, the regression gate, and the
dashboard.
