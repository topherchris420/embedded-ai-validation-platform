# Benchmarks Module

Benchmark suite for TinyML workloads on embedded devices.

## Metrics Collected

| Metric | Description | Units |
|--------|-------------|-------|
| Inference Latency | Time per inference | ms |
| FPS | Frames per second | fps |
| RAM Usage | Memory consumption | KB |
| Flash Size | Model size in storage | KB |
| CPU Utilization | Processor usage | % |
| Power Consumption | Energy draw | mW |
| Startup Time | Time to first inference | ms |
| MACs | Multiply-accumulate operations | count |

## Supported Models

- TensorFlow Lite Micro (`.tflite`)
- ONNX Runtime (`.onnx`)
- Custom model formats

## Architecture

```
benchmarks/
├── tinyml/         # TinyML benchmarking (existing code)
├── latency/        # Latency measurement
├── memory/         # Memory profiling
├── power/          # Power consumption tracking
└── results/        # Result storage and comparison
```

## Running Benchmarks

```bash
# Run all benchmarks
eaiv run --config configs/default.yaml --suite tinyml

# Run specific benchmark
eaiv run --config configs/esp32.yaml --suite tinyml --model models/mobilenet.tflite

# Compare with baseline
eaiv compare --baseline reports/baseline.json --current reports/current.json
```

## Benchmark Configuration

```yaml
tinyml:
  model: models/mobilenet_v1_0.25_128_int8.tflite
  runtime: tflite
  iterations: 50
  warmup: 5
  batch_size: 1
```

## Adding New Benchmarks

Implement the `Benchmark` plugin interface:

```python
from eaiv.plugins import register_plugin
from eaiv.plugins.benchmarks import Benchmark, BenchmarkResult

@register_plugin("custom_benchmark", "benchmark", "Custom benchmark")
class CustomBenchmark(Benchmark):
    def load_model(self, path: str) -> ModelMetadata:
        # Load model
        ...

    def run(self) -> BenchmarkResult:
        # Run benchmark
        ...
```