"""Telemetry Lab — inspect a capture before you trust it.

Plots are the easy part. This page leads with the questions that decide
whether a capture is usable: is the sample rate what it claims, are
samples missing, are there outliers, and — when ground truth is present —
how far did the estimate drift from it.

Files come from disk (restricted to the session's allowed directories) or
from an upload with a size limit. Neither path lets a browser address
arbitrary files on the host.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from eaiv.dashboard.safety import MAX_UPLOAD_BYTES, UnsafePathError, check_upload, resolve_within
from eaiv.dashboard.signals import (
    analyze_sampling,
    analyze_signal,
    group_signals,
    orientation_error,
    reference_pairs,
)
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.state import Workspace

MAX_PLOT_POINTS = 20_000


def _discover(workspace: Workspace) -> list[Path]:
    """CSV captures under the dataset and report directories."""
    found: list[Path] = []
    for root in (workspace.dataset_dir, workspace.report_dir):
        if root.exists():
            found.extend(sorted(root.glob("**/*.csv")))
    return found


def _declared_rate(path: Path) -> float | None:
    try:
        from eaiv.datasets import read_metadata

        return float(read_metadata(path).sampling_rate_hz)
    except Exception:  # noqa: BLE001 - a sidecar is optional
        return None


def _downsample(frame: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if len(frame) <= MAX_PLOT_POINTS:
        return frame, False
    step = len(frame) // MAX_PLOT_POINTS + 1
    return frame.iloc[::step], True


def _plot_group(frame: pd.DataFrame, title: str, columns: list[str], x: str | None) -> None:
    plot_frame, reduced = _downsample(frame)
    figure = go.Figure()
    for column in columns:
        figure.add_trace(
            go.Scatter(
                x=plot_frame[x] if x else plot_frame.index,
                y=plot_frame[column],
                name=column,
                mode="lines",
                line={"width": 1.2},
            )
        )
    figure.update_layout(
        title=title + (" (downsampled for display)" if reduced else ""),
        height=300,
        margin={"l": 10, "r": 10, "t": 36, "b": 10},
        xaxis_title=x or "sample",
        hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch")


def _fault_windows(report: dict[str, Any] | None) -> list[tuple[float, float]]:
    """Outage windows from a run's HIL configuration, for overlaying."""
    if not report:
        return []
    faults = ((report.get("meta") or {}).get("config") or {}).get("hil", {}).get("faults") or []
    windows = []
    for fault in faults:
        if isinstance(fault, dict) and fault.get("kind") == "outage":
            start = float(fault.get("start_s", 0))
            windows.append((start, start + float(fault.get("duration_s", 0))))
    return windows


def render(workspace: Workspace) -> None:
    st.subheader("Telemetry Lab")
    st.caption(
        "Inspect a captured or recorded signal log: timing health, per-channel statistics, "
        "outliers, and orientation error against ground truth."
    )

    source_mode = st.radio(
        "Source", ["Files on disk", "Upload a CSV"], horizontal=True, key="tl_source"
    )

    frame: pd.DataFrame | None = None
    label = ""
    declared_rate: float | None = None

    if source_mode == "Upload a CSV":
        upload = st.file_uploader(
            f"CSV file (max {MAX_UPLOAD_BYTES // 1024 // 1024} MB)", type=["csv"], key="tl_upload"
        )
        if upload is None:
            st.caption("Upload a capture, or switch to the files already on disk.")
            return
        try:
            check_upload(upload.name, upload.size)
        except ValueError as exc:
            st.error(str(exc))
            return
        try:
            frame = pd.read_csv(io.BytesIO(upload.getvalue()))
        except (ValueError, pd.errors.ParserError) as exc:
            st.error(f"{upload.name} is not a readable CSV: {exc}")
            return
        label = upload.name
    else:
        candidates = _discover(workspace)
        custom = st.text_input(
            "Or a directory to scan",
            value=str(workspace.dataset_dir),
            help=f"Restricted to: {workspace.policy.describe()}",
            key="tl_dir",
        )
        if custom and custom != str(workspace.dataset_dir):
            try:
                root = resolve_within(workspace.policy, custom)
            except UnsafePathError as exc:
                st.error(str(exc))
                return
            candidates = sorted(root.glob("**/*.csv")) if root.exists() else []
        if not candidates:
            st.info(
                "No CSV captures found. Generate one with "
                "`eaiv datasets generate --profile gentle --duration 20 -o datasets/imu/log.csv`, "
                "or capture live telemetry with `eaiv monitor --csv capture.csv`.",
                icon=None,
            )
            return
        chosen = st.selectbox("Capture", candidates, format_func=lambda p: str(p), key="tl_file")
        path = Path(chosen)
        try:
            frame = pd.read_csv(path)
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            st.error(f"{path} could not be parsed: {exc}")
            return
        label = str(path)
        declared_rate = _declared_rate(path)

    if frame is None or frame.empty:
        st.warning("The selected capture has no rows.")
        return

    numeric_columns = [c for c in frame.select_dtypes("number").columns if c != "t_s"]
    if not numeric_columns:
        st.warning("No numeric signals in this file.")
        return

    x_axis = "t_s" if "t_s" in frame.columns else None

    if x_axis:
        times = frame["t_s"].tolist()
        sampling = analyze_sampling(times, declared_rate)
        columns = st.columns(4)
        with columns[0]:
            ui.tile("Samples", f"{sampling.samples:,}")
        with columns[1]:
            ui.tile("Duration", f"{sampling.duration_s:.2f} s")
        with columns[2]:
            ui.tile(
                "Mean rate",
                f"{sampling.mean_rate_hz:.2f} Hz",
                f"declared {declared_rate:.2f} Hz" if declared_rate else "no sidecar",
            )
        with columns[3]:
            ui.tile(
                "Interval jitter",
                f"{sampling.jitter_s * 1000:.3f} ms",
                f"median interval {sampling.median_interval_s * 1000:.3f} ms",
            )
        if sampling.issues:
            for issue in sampling.issues:
                st.warning(issue, icon=None)
        else:
            st.success("Timing is consistent: monotonic timestamps, no gaps detected.")
        if sampling.gaps:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "At (s)": f"{start:.4f}",
                            "Gap (s)": f"{length:.4f}",
                            "Missing samples (est.)": (
                                max(0, round(length / sampling.median_interval_s) - 1)
                                if sampling.median_interval_s
                                else 0
                            ),
                        }
                        for start, length in sampling.gaps[:50]
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
    else:
        st.caption("No `t_s` column: timing checks are unavailable for this capture.")

    st.divider()
    st.markdown("**Signals**")
    groups = group_signals(list(frame.columns))
    selected_groups = st.multiselect(
        "Groups to plot", list(groups.keys()), default=list(groups.keys())[:3], key="tl_groups"
    )
    if x_axis and len(frame) > 1:
        t_min, t_max = float(frame["t_s"].min()), float(frame["t_s"].max())
        if t_max > t_min:
            window = st.slider("Time range (s)", t_min, t_max, (t_min, t_max), key="tl_range")
            frame = frame[(frame["t_s"] >= window[0]) & (frame["t_s"] <= window[1])]

    for title in selected_groups:
        members = [c for c in groups[title] if c in numeric_columns]
        if members:
            _plot_group(frame, title, members, x_axis)

    st.divider()
    st.markdown("**Per-signal statistics**")
    stats = [analyze_signal(name, frame[name].tolist()) for name in numeric_columns]
    st.dataframe(pd.DataFrame([s.to_dict() for s in stats]), width="stretch", hide_index=True)
    flagged = [s for s in stats if s.outliers]
    if flagged:
        st.caption(
            "Outliers are flagged with a modified Z score above 3.5 (median-based, so a few "
            "extreme samples cannot hide behind their own effect on the mean)."
        )
        inspect = st.selectbox("Inspect outliers in", [s.name for s in flagged], key="tl_outlier")
        target = next(s for s in flagged if s.name == inspect)
        indices = target.outlier_indices[:200]
        st.dataframe(
            frame.iloc[indices][[c for c in (x_axis, inspect) if c]],
            width="stretch",
        )

    pairs = reference_pairs(list(frame.columns))
    if pairs and x_axis:
        st.divider()
        st.markdown("**Estimated versus ground truth**")
        rows = []
        for axis, estimated, reference in pairs:
            error = orientation_error(
                frame[x_axis].tolist(), frame[estimated].tolist(), frame[reference].tolist(), axis
            )
            if error is None:
                continue
            rows.append(
                {
                    "Axis": error.axis,
                    "RMSE (deg)": round(error.rmse_deg, 4),
                    "Max error (deg)": round(error.max_error_deg, 4),
                    "Mean bias (deg)": round(error.mean_error_deg, 4),
                    "Drift (deg/min)": round(error.drift_deg_per_min, 4),
                    "Samples": error.samples,
                }
            )
            figure = go.Figure()
            plot_frame, _ = _downsample(frame)
            figure.add_trace(
                go.Scatter(x=plot_frame[x_axis], y=plot_frame[estimated], name="estimated")
            )
            figure.add_trace(
                go.Scatter(
                    x=plot_frame[x_axis],
                    y=plot_frame[reference],
                    name="ground truth",
                    line={"dash": "dot"},
                )
            )
            figure.update_layout(
                title=f"{axis} — estimate vs ground truth",
                height=280,
                margin={"l": 10, "r": 10, "t": 36, "b": 10},
                xaxis_title="t (s)",
                yaxis_title="deg",
            )
            st.plotly_chart(figure, width="stretch")
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    elif not pairs:
        st.caption(
            "No ground-truth columns (`roll_ref_deg`, `pitch_ref_deg`, ...) in this capture, so "
            "orientation error cannot be scored."
        )

    st.divider()
    st.download_button(
        "Download the filtered data",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=f"{Path(label).stem or 'telemetry'}-filtered.csv",
        key="tl_download",
    )


__all__ = ["render"]
