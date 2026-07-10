# Sensor Fusion Module

Framework for sensor fusion experiments on embedded devices.

## Supported Sensors

- **IMU** - Inertial Measurement Unit
  - Accelerometer
  - Gyroscope
  - Magnetometer (optional)
- **Barometer** - Pressure/temperature
- **GPS** - Position, velocity, heading

## Algorithms

| Algorithm | Description | Use Case |
|-----------|-------------|----------|
| Complementary Filter | Simple weighted fusion | Roll/pitch estimation |
| Mahony Filter | Proportional-only AHRS | Low-compute applications |
| Madgwick Filter | Gradient descent AHRS | High-accuracy orientation |
| Kalman Filter | Optimal state estimation | Position tracking |
| Extended Kalman Filter | Non-linear estimation | GPS/IMU fusion |

## Architecture

```
sensor_fusion/
├── algorithms/     # Filter implementations
├── experiments/   # Experiment runners
├── replay/        # Dataset replay
└── datasets/      # IMU data logs
```

## Usage

### Live Sensor Fusion

```python
from eaiv.sensor_fusion.fusion import build_filter
from eaiv.sensors import IMUSensor

# Create filter
filter = build_filter("madgwick")

# Process sensor data
imu = IMUSensor(config)
imu.start()
for _ in range(100):
    data = imu.read_imu()
    orientation = filter.update(0.005, data.gyro_xyz_rad_s, data.accel_xyz_g)
    print(f"Roll: {orientation.roll_deg:.2f}, Pitch: {orientation.pitch_deg:.2f}")
imu.stop()
```

### Dataset Replay

```bash
# Run fusion experiment with CSV replay
eaiv run --config configs/fusion.yaml --suite fusion

# Replay with algorithm comparison
eaiv fusion-compare --dataset datasets/imu_run1.csv --algorithms kalman,mahony,madgwick
```

## Dataset Format

CSV format for IMU data:

```csv
timestamp_s,gx,gy,gz,ax,ay,az,mx,my,mz
0.0,0.001,0.002,-0.0005,0.01,0.02,0.98,25.1,12.3,45.2
0.005,0.001,0.002,-0.0005,0.01,0.02,0.98,25.1,12.3,45.2
...
```

## Metrics

- **RMSE** - Root mean square error vs ground truth
- **Drift** - Degrees per minute of drift
- **Latency** - Processing delay in ms
- **Convergence Time** - Time to stabilize