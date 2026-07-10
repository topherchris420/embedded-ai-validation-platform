# Datasets Module

Reusable datasets for embedded AI validation and testing.

## Dataset Formats

### IMU Data (CSV)

```csv
timestamp_s,gx,gy,gz,ax,ay,az,mx,my,mz
0.0,0.001,0.002,-0.0005,0.01,0.02,0.98,25.1,12.3,45.2
```

Columns:
- `timestamp_s` - Unix timestamp in seconds
- `gx, gy, gz` - Gyroscope (rad/s)
- `ax, ay, az` - Accelerometer (g)
- `mx, my, mz` - Magnetometer (μT) - optional

### Benchmark Results (JSON)

```json
{
  "benchmark": "mobilenet_v1",
  "timestamp": "2024-01-15T10:30:00Z",
  "target": "esp32",
  "metrics": {
    "latency_mean_ms": 45.2,
    "ram_peak_kb": 128,
    "flash_model_kb": 342
  }
}
```

### Test Results (JSON)

```json
{
  "test_suite": "firmware",
  "timestamp": "2024-01-15T10:30:00Z",
  "passed": true,
  "duration_s": 12.5,
  "metrics": {
    "test_count": 10,
    "passed_count": 10,
    "failed_count": 0
  }
}
```

## Included Datasets

| Dataset | Description | Size | Format |
|---------|-------------|------|--------|
| `imu_walk.csv` | Walking IMU data | 10MB | CSV |
| `imu_static.csv` | Static IMU data | 1MB | CSV |
| `imu_rotation.csv` | Rotation test data | 5MB | CSV |
| `gps_route.csv` | GPS route data | 2MB | CSV |

## Replay Tools

```bash
# Replay IMU dataset
eaiv replay datasets/imu_walk.csv

# Convert to different format
eaiv convert datasets/imu_walk.csv --output imu_walk.json

# Generate synthetic data
eaiv generate imu --output synthetic.csv --duration 60
```

## Adding New Datasets

1. Add dataset to appropriate subdirectory
2. Create `README.md` in dataset folder
3. Add metadata to `datasets/index.json`

## Dataset Index

```json
{
  "imu_walk": {
    "path": "imu/walk.csv",
    "description": "10 minutes of walking IMU data",
    "duration_s": 600,
    "sample_rate_hz": 200,
    "sensors": ["accel", "gyro"],
    "license": "MIT"
  }
}
```