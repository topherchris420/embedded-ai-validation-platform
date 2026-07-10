"""Streamlit dashboard for the Embedded AI Validation Platform.

Run with:
    streamlit run dashboard/python/app.py

Pages:
    Overview   — pass/fail tiles and the latest run's suite table
    Benchmarks — metric history across runs, latency distribution, power
    Telemetry  — sensor/telemetry CSV plots (datasets or captures)
    Compare    — regression diff between any two recorded reports
    History    — every recorded run, exportable artifacts

All data shaping lives in ``eaiv.dashboard`` (typed + unit-tested); this
file is presentation only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Keep string columns on the python backend: pyarrow-backed string arrays
# have crashed natively when frames are built on Streamlit's script thread
# (observed with pandas 3.x + pyarrow 25). Values here are tiny; the arrow
# fast path buys nothing.
try:
    pd.set_option("mode.string_storage", "python")
except (pd.errors.OptionError, AttributeError):
    pass

from eaiv.core.regression import compare_reports
from eaiv.dashboard import (
    latency_percentiles,
    load_reports,
    metric_history,
    numeric_metrics,
    suite_status,
)


def _load_csvs(data_dir: Path) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    if not data_dir.exists():
        return frames
    for f in sorted(data_dir.glob("**/*.csv")):
        try:
            frames[str(f.relative_to(data_dir))] = pd.read_csv(f)
        except (OSError, pd.errors.ParserError):
            continue
    return frames


def page_overview(reports: list[dict]) -> None:
    if not reports:
        st.info("No reports found. Run `eaiv run --config configs/sim.yaml` first.")
        return
    latest = reports[0]
    rows = suite_status(latest)
    passed_runs = sum(1 for r in reports if r.get("all_passed"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Recorded runs", len(reports))
    c2.metric("Run pass rate", f"{passed_runs / len(reports):.0%}")
    c3.metric("Latest run", str(latest.get("timestamp", ""))[:19])
    c4.metric("Latest verdict", "PASS" if latest.get("all_passed") else "FAIL")

    st.divider()
    st.subheader("Latest run")
    st.dataframe(
        pd.DataFrame(
            [
                {"suite": n, "status": "✅ PASS" if p else "❌ FAIL", "notes": notes}
                for n, p, notes in rows
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


def page_benchmarks(reports: list[dict]) -> None:
    if not reports:
        st.info("No reports found.")
        return
    suites = sorted({s.get("name", "") for r in reports for s in r.get("suites", [])})
    suite = st.selectbox("Suite", suites, index=suites.index("tinyml") if "tinyml" in suites else 0)

    latest_metrics = numeric_metrics(reports[0], suite)
    if not latest_metrics:
        st.info("No numeric metrics for this suite in the latest run.")
        return

    percentiles = latency_percentiles(latest_metrics)
    if percentiles:
        st.subheader("Latency distribution (latest run)")
        fig = go.Figure(go.Bar(x=list(percentiles.keys()), y=list(percentiles.values())))
        fig.update_layout(yaxis_title="ms", xaxis_title="percentile")
        st.plotly_chart(fig, use_container_width=True)

    power_keys = [k for k in latest_metrics if "power" in k or "energy" in k]
    if power_keys:
        st.subheader("Power (latest run)")
        cols = st.columns(len(power_keys))
        for col, key in zip(cols, power_keys):
            col.metric(key, f"{latest_metrics[key]:g}")

    st.subheader("Metric history across runs")
    metric = st.selectbox("Metric", sorted(latest_metrics.keys()))
    series = metric_history(reports, suite, metric)
    if len(series) < 2:
        st.info("Need at least two recorded runs for a trend — showing latest value.")
        st.metric(metric, f"{latest_metrics.get(metric, float('nan')):g}")
    else:
        df = pd.DataFrame(series, columns=["timestamp", metric])
        st.plotly_chart(
            px.line(df, x="timestamp", y=metric, markers=True), use_container_width=True
        )


def page_telemetry() -> None:
    source_dir = st.text_input("CSV directory", value="datasets")
    frames = _load_csvs(Path(source_dir))
    if not frames:
        st.info(
            "No CSVs found. Capture live telemetry with "
            "`eaiv monitor --config configs/sim.yaml --csv capture.csv`."
        )
        return
    name = st.selectbox("File", sorted(frames))
    df = frames[name]
    x = "t_s" if "t_s" in df.columns else None
    numeric_cols = [c for c in df.select_dtypes("number").columns if c != "t_s"]

    groups = {
        "Gyroscope (rad/s)": [c for c in numeric_cols if c.startswith("g")],
        "Accelerometer (g)": [c for c in numeric_cols if c.startswith("a")],
        "Orientation (deg)": [
            c for c in numeric_cols if c in ("roll", "pitch", "yaw") or c.endswith("_deg")
        ],
    }
    plotted: set[str] = set()
    for title, cols in groups.items():
        if not cols:
            continue
        plotted.update(cols)
        fig = go.Figure()
        for c in cols:
            fig.add_trace(go.Scatter(x=df[x] if x else None, y=df[c], name=c, mode="lines"))
        fig.update_layout(title=title, xaxis_title=x or "sample")
        st.plotly_chart(fig, use_container_width=True)

    leftovers = [c for c in numeric_cols if c not in plotted]
    if leftovers:
        with st.expander("Other fields"):
            fig = go.Figure()
            for c in leftovers:
                fig.add_trace(go.Scatter(x=df[x] if x else None, y=df[c], name=c, mode="lines"))
            st.plotly_chart(fig, use_container_width=True)


def page_compare(reports: list[dict]) -> None:
    if len(reports) < 2:
        st.info("Need at least two recorded reports to compare.")
        return
    labels = [f"{r.get('timestamp', '')[:19]}  ({Path(r['source_file']).name})" for r in reports]
    c1, c2 = st.columns(2)
    baseline_i = c1.selectbox(
        "Baseline", range(len(reports)), index=len(reports) - 1, format_func=lambda i: labels[i]
    )
    current_i = c2.selectbox(
        "Current", range(len(reports)), index=0, format_func=lambda i: labels[i]
    )
    threshold = st.slider("Max regression (%)", 1.0, 50.0, 10.0)

    result = compare_reports(reports[baseline_i], reports[current_i], max_regression_pct=threshold)
    if result.passed:
        st.success(f"No regressions across {len(result.deltas)} shared metrics")
    else:
        st.error(f"{len(result.regressions)} regression(s) beyond {threshold}%")
    if result.deltas:
        # Rendered as Markdown rather than st.dataframe: a static diff table
        # needs no sorting UI, and this render path is identical to the
        # report.md artifact reviewers see in PRs.
        lines = [
            "| suite | metric | baseline | current | change % | |",
            "|-------|--------|----------|---------|----------|-|",
        ]
        for d in result.deltas:
            flag = "❌ regressed" if d.regressed else ""
            lines.append(
                f"| {d.suite} | {d.metric} | {d.baseline:g} | {d.current:g} "
                f"| {d.change_pct:+.2f} | {flag} |"
            )
        st.markdown("\n".join(lines))


def page_history(reports: list[dict], report_dir: Path) -> None:
    if not reports:
        st.info("No reports found.")
        return
    rows = []
    for r in reports:
        for name, passed, _ in suite_status(r):
            rows.append({"timestamp": r.get("timestamp", ""), "suite": name, "passed": passed})
    df = pd.DataFrame(rows)
    fig = px.scatter(
        df,
        x="timestamp",
        y="suite",
        color="passed",
        color_discrete_map={True: "#0a7d1f", False: "#b3261e"},
        title="Suite outcomes over time",
    )
    st.plotly_chart(fig, use_container_width=True)
    with st.expander("Raw runs"):
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("Export latest artifacts")
    for artifact in ("report.md", "report.csv", "latest.json"):
        path = report_dir / artifact
        if path.exists():
            st.download_button(f"Download {artifact}", data=path.read_bytes(), file_name=artifact)


def main() -> None:
    st.set_page_config(page_title="Embedded AI Validation", page_icon="🤖", layout="wide")
    st.title("🤖 Embedded AI Validation Platform")

    with st.sidebar:
        page = st.radio("Page", ["Overview", "Benchmarks", "Telemetry", "Compare", "History"])
        st.divider()
        report_dir = Path(st.text_input("Report directory", value="reports"))

    reports = load_reports(report_dir)
    if page == "Overview":
        page_overview(reports)
    elif page == "Benchmarks":
        page_benchmarks(reports)
    elif page == "Telemetry":
        page_telemetry()
    elif page == "Compare":
        page_compare(reports)
    elif page == "History":
        page_history(reports, report_dir)


main()
