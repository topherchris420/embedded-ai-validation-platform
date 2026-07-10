# Datasets Module

Reusable, replay-capable datasets for embedded AI validation and HIL testing.

## Committed datasets

| File | Contents |
|------|----------|
| `imu/imu_run1.csv` | 20 s @ 100 Hz, gentle roll/pitch/yaw motion (seed 42) — default fusion replay |
| `imu/imu_static_biased.csv` | 10 s @ 100 Hz, static with constant gyro bias — bias-estimation testing |
| `imu/imu_aggressive.csv` | 15 s @ 200 Hz, large fast motion — filter stress testing |

All committed logs are generated with `eaiv.datasets.generate_imu_trajectory`
using a fixed seed, so they are exactly reproducible:

```python
from eaiv.datasets import generate_imu_trajectory, write_imu_csv

samples = generate_imu_trajectory(duration_s=20, rate_hz=100, profile="gentle", seed=42)
write_imu_csv(samples, "datasets/imu/imu_run1.csv")
```

or from the CLI:

```bash
eaiv datasets generate --profile gentle --duration 20 --rate 100 --seed 42 -o my_log.csv
```

## IMU CSV schema

```csv
t_s,gx,gy,gz,ax,ay,az,roll_ref_deg,pitch_ref_deg
0.000000,0.188496,0.001000,0.002000,0.010000,0.020000,0.980000,0.0000,0.0000
```

- `t_s` — sample time in seconds from log start
- `gx, gy, gz` — gyroscope body rates (rad/s)
- `ax, ay, az` — accelerometer (g)
- `roll_ref_deg, pitch_ref_deg` — ground-truth orientation (synthetic logs
  only); fusion experiments compute RMSE against these when present

The schema is what `eaiv.sensor_fusion.experiments.FusionExperiment` and the
HIL replay source consume directly.

## Benchmark results (JSON)

Benchmark runs write `reports/latest.json` (see `eaiv.core.reporter`); use
`eaiv compare` to diff two report files and gate regressions in CI.
