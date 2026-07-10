"""Streamlit dashboard for Embedded AI Validation Platform.

Run with:
    streamlit run dashboard/python/app.py
    eaiv dashboard start
"""

from __future__ import annotations

import json
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pandas import read_csv


def load_results(data_dir: Path = Path("reports")) -> list[dict]:
    """Load test results from JSON files."""
    results = []
    if not data_dir.exists():
        return results
    for f in data_dir.glob("**/results.json"):
        try:
            data = json.loads(f.read_text())
            data["source_file"] = str(f)
            results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(results, key=lambda x: x.get("timestamp", ""), reverse=True)


def load_sensor_data(data_dir: Path = Path("datasets")) -> dict:
    """Load sensor datasets."""
    datasets = {}
    if not data_dir.exists():
        return datasets
    for f in data_dir.glob("**/*.csv"):
        try:
            datasets[f.stem] = read_csv(f)
        except OSError:
            continue
    return datasets


def main() -> None:
    """Main dashboard application."""
    st.set_page_config(
        page_title="Embedded AI Validation",
        page_icon="🤖",
        layout="wide",
    )

    st.title("🤖 Embedded AI Validation Platform")
    st.markdown("Real-time monitoring and benchmark analysis for embedded AI systems")

    # Sidebar for navigation
    with st.sidebar:
        st.header("Navigation")
        page = st.radio(
            "Go to",
            ["Overview", "Benchmarks", "Sensors", "History"],
        )

        st.divider()

        st.header("Configuration")
        data_dir = st.text_input("Data Directory", value="reports")

    # Load data
    data_path = Path(data_dir)
    results = load_results(data_path)
    sensor_data = load_sensor_data(Path("datasets"))

    if page == "Overview":
        # Overview page
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Tests", len(results))

        with col2:
            passed = sum(1 for r in results if r.get("passed"))
            st.metric("Passed", passed)

        with col3:
            failed = len(results) - passed
            st.metric("Failed", failed)

        with col4:
            if results:
                latest = results[0].get("timestamp", "N/A")
                st.metric("Latest Run", latest[:10] if latest else "N/A")

        st.divider()

        # Recent results
        st.subheader("Recent Test Runs")
        if results:
            for r in results[:10]:
                status = "✅" if r.get("passed") else "❌"
                st.write(f"{status} {r.get('test_suite', 'unknown')} - {r.get('timestamp', '')}")
        else:
            st.info("No test results found. Run some tests first!")

    elif page == "Benchmarks":
        st.subheader("📊 Benchmark Results")

        # Filter by benchmark name
        benchmark_names = list(set(r.get("benchmark", "") for r in results))
        if benchmark_names:
            selected = st.selectbox("Select Benchmark", benchmark_names)
            benchmark_results = [r for r in results if r.get("benchmark") == selected]

            if benchmark_results:
                # Extract latency data
                latencies = []
                for r in benchmark_results:
                    metrics = r.get("metrics", {})
                    if "latency_mean_ms" in metrics:
                        latencies.append(
                            {
                                "timestamp": r.get("timestamp", ""),
                                "mean_ms": metrics["latency_mean_ms"],
                                "min_ms": metrics.get("latency_min_ms", 0),
                                "max_ms": metrics.get("latency_max_ms", 0),
                            }
                        )

                if latencies:
                    df = px.data.DataFrame(latencies)

                    # Latency over time
                    fig = px.line(
                        df,
                        x="timestamp",
                        y="mean_ms",
                        title=f"{selected} - Latency Over Time",
                        labels={"mean_ms": "Latency (ms)", "timestamp": "Time"},
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # Distribution
                    fig2 = px.histogram(
                        df,
                        x="mean_ms",
                        title=f"{selected} - Latency Distribution",
                        labels={"mean_ms": "Latency (ms)", "count": "Count"},
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("No latency data available for this benchmark")
        else:
            st.info("No benchmark results found")

    elif page == "Sensors":
        st.subheader("📡 Sensor Data")

        if sensor_data:
            sensor_name = st.selectbox("Select Sensor Dataset", list(sensor_data.keys()))
            df = sensor_data[sensor_name]

            # Check for IMU columns
            imu_cols = [
                c for c in df.columns if any(s in c for s in ["ax", "ay", "az", "gx", "gy", "gz"])
            ]

            if imu_cols:
                col1, col2 = st.columns(2)

                with col1:
                    st.write("### Accelerometer")
                    if "ax" in df.columns:
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(y=df["ax"], name="X"))
                        fig.add_trace(go.Scatter(y=df["ay"], name="Y"))
                        fig.add_trace(go.Scatter(y=df["az"], name="Z"))
                        fig.update_layout(yaxis_title="Acceleration (g)")
                        st.plotly_chart(fig, use_container_width=True)

                with col2:
                    st.write("### Gyroscope")
                    if "gx" in df.columns:
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(y=df["gx"], name="X"))
                        fig.add_trace(go.Scatter(y=df["gy"], name="Y"))
                        fig.add_trace(go.Scatter(y=df["gz"], name="Z"))
                        fig.update_layout(yaxis_title="Angular Velocity (rad/s)")
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No sensor data columns found")
                st.write("Available columns:", list(df.columns))
        else:
            st.info("No sensor datasets found")

    elif page == "History":
        st.subheader("📜 Test History")

        if results:
            # Create timeline
            df = px.data.DataFrame(results)
            fig = px.timeline(
                df,
                x_start="timestamp",
                x_end="timestamp",
                y="test_suite",
                color="passed",
                title="Test History Timeline",
            )
            st.plotly_chart(fig, use_container_width=True)

            # Raw data
            with st.expander("View Raw Data"):
                st.dataframe(df)
        else:
            st.info("No test history found")


if __name__ == "__main__":
    main()
