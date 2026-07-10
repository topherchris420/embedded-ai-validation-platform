# Dashboard Module

Streamlit dashboard over the platform's report and telemetry artifacts.

```bash
pip install -e ".[dashboard]"
streamlit run dashboard/python/app.py
```

Generate data first (no hardware needed):

```bash
eaiv run --config configs/sim.yaml                     # writes reports/
eaiv monitor --config configs/sim.yaml --csv capture.csv   # telemetry CSV
```

## Pages

| Page | Contents |
|------|----------|
| Overview | run counters, pass rate, latest run's suite verdict table |
| Benchmarks | latency distribution (percentiles), power/energy tiles, any metric's history across runs |
| Telemetry | grouped sensor plots (gyro / accel / orientation) from dataset or captured CSVs |
| Compare | interactive regression diff between any two recorded reports (same engine as `eaiv compare`) |
| History | suite outcomes over time, raw runs, one-click export of `report.md` / `report.csv` / `latest.json` |

## Architecture

Data shaping lives in `eaiv.dashboard` (typed, unit-tested, no
streamlit/pandas dependency); `dashboard/python/app.py` is presentation
only. Any other front end (Grafana exporter, notebook, TUI) can build on
the same functions:

```python
from eaiv.dashboard import load_reports, metric_history

reports = load_reports("reports")
series = metric_history(reports, suite="tinyml", metric="mean_ms")
```

Reports come from `eaiv.core.reporter` (`report_*.json`); telemetry CSVs
come from `eaiv monitor --csv` / `eaiv.telemetry.TelemetryCollector`.
