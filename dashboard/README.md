# Dashboard Module

Real-time visualization dashboard for embedded AI validation metrics.

## Features

- **Real-time Telemetry** - Live sensor and inference data
- **Benchmark Comparison** - Compare runs over time
- **Latency Histograms** - Distribution analysis
- **Memory Usage** - RAM/Flash tracking
- **CPU Utilization** - Processing load
- **Power Profiles** - Energy consumption
- **Sensor Plots** - IMU, GPS, barometer visualization
- **Test History** - Historical test results
- **Interactive Charts** - Zoom, pan, export

## Architecture

```
dashboard/
├── python/         # Dashboard backend
│   ├── app.py      # Streamlit app
│   ├── api.py      # Data API
│   └── widgets/    # Custom widgets
└── static/         # Static assets
```

## Running the Dashboard

```bash
# Install dashboard dependencies
pip install eaiv[dashboard]

# Start dashboard
eaiv dashboard start

# Or run directly
streamlit run dashboard/python/app.py
```

## Dashboard Screens

### Overview

- System status cards
- Recent test runs
- Active targets
- Quick actions

### Real-time Telemetry

- Live sensor plots
- Inference timing
- Resource usage

### Benchmark Results

- Run comparison charts
- Latency distributions
- Memory usage over time

### Historical Data

- Test history timeline
- Regression detection
- Export to CSV/JSON

## Configuration

```yaml
dashboard:
  host: 0.0.0.0
  port: 8501
  data_dir: reports/
  refresh_interval_s: 5
  default_tests:
    - tinyml
    - fusion
    - rt_perf
```

## API

The dashboard exposes a REST API for programmatic access:

```bash
# Get latest results
curl http://localhost:8501/api/results/latest

# Get benchmark data
curl http://localhost:8501/api/benchmarks/mobilenet/history

# Get sensor data
curl http://localhost:8501/api/sensors/imu0/stream
```

## Adding Custom Widgets

```python
from dashboard.python.widgets import register_widget

@register_widget("my_widget")
def my_widget():
    st.write("Custom widget content")
    # Add interactive elements
```