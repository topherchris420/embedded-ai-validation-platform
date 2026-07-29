"""Compare — the release-decision workspace.

Any two artifacts the platform can read are selectable here: recorded
runs, legacy report files, and stored baselines. The page leads with
whether the pair is comparable at all, because a delta between two
different boards or two different datasets is not evidence about the
change under review.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from eaiv.core.comparison import (
    CompatibilityLevel,
    MetricChange,
    compare_runs,
    to_json,
    to_markdown,
)
from eaiv.core.metrics import format_value
from eaiv.dashboard.runs import ReportSource, all_sources
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.state import Workspace, goto


def _baseline_sources(workspace: Workspace) -> list[ReportSource]:
    out: list[ReportSource] = []
    for info in workspace.baselines.list():
        out.append(
            ReportSource(
                id=f"baseline:{info.name}",
                label=f"baseline · {info.name} ({info.saved_at[:19]})",
                timestamp=info.saved_at,
                target=info.target,
                path=info.path,
                kind="baseline",
            )
        )
    return out


def _delta_chart(changes: list[MetricChange]) -> go.Figure | None:
    interesting = [c for c in changes if c.change_pct is not None and c.status != "informational"]
    interesting.sort(key=lambda c: abs(c.change_pct or 0), reverse=True)
    top = interesting[:18]
    if not top:
        return None
    top.reverse()
    colors = [
        "#b3261e" if c.status == "regressed" else "#1a7f45" if c.status == "improved" else "#8794a5"
        for c in top
    ]
    figure = go.Figure(
        go.Bar(
            x=[c.change_pct for c in top],
            y=[f"{c.suite}.{c.metric}" for c in top],
            orientation="h",
            marker_color=colors,
            text=[f"{c.change_pct:+.1f}%" for c in top],
            textposition="outside",
        )
    )
    figure.update_layout(
        height=max(240, 26 * len(top)),
        margin={"l": 10, "r": 30, "t": 24, "b": 10},
        xaxis_title="change vs baseline (%)",
        yaxis_title="",
        title="Largest movements",
    )
    return figure


def _changes_frame(changes: list[MetricChange]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Suite": c.suite,
                "Metric": c.metric,
                "Baseline": format_value(c.baseline, c.info) if c.baseline is not None else "—",
                "Current": format_value(c.current, c.info) if c.current is not None else "—",
                "Change": (
                    format_value(c.absolute_change, c.info)
                    if c.absolute_change is not None
                    else "—"
                ),
                "%": f"{c.change_pct:+.2f}" if c.change_pct is not None else "—",
                "Verdict": c.status,
                "Direction": c.info.direction_label,
                "Origin": str(c.info.provenance),
            }
            for c in changes
        ]
    )


def _load(source: ReportSource, workspace: Workspace) -> dict[str, Any] | None:
    if source.kind == "baseline":
        try:
            return workspace.baselines.load(source.id.split(":", 1)[1])
        except (FileNotFoundError, ValueError):
            return None
    return source.report()


def render(workspace: Workspace) -> None:
    st.subheader("Compare")
    st.caption(
        "Pick any two artifacts. The page states first whether they can be compared, then what "
        "moved, then what to do about it."
    )
    sources = all_sources(workspace.runs, workspace.report_dir) + _baseline_sources(workspace)
    if len(sources) < 2:
        if ui.empty_state(
            "Two artifacts are needed to compare",
            "Record at least two runs — or run the simulated demo, which produces three.",
            "New validation run",
            "compare_new",
        ):
            goto("New run")
        return

    ids = [s.id for s in sources]
    labels = {s.id: s.label for s in sources}
    columns = st.columns(2)
    baseline_id = columns[0].selectbox(
        "Baseline (reference)",
        ids,
        index=min(1, len(ids) - 1),
        format_func=lambda i: labels[i],
        key="cmp_baseline",
    )
    current_id = columns[1].selectbox(
        "Current (candidate)", ids, index=0, format_func=lambda i: labels[i], key="cmp_current"
    )
    allowance = st.slider(
        "Max regression before a metric fails the gate",
        1.0,
        100.0,
        10.0,
        step=1.0,
        format="%g%%",
        key="cmp_allowance",
    )

    if baseline_id == current_id:
        st.info("Select two different artifacts.", icon=None)
        return

    baseline_source = next(s for s in sources if s.id == baseline_id)
    current_source = next(s for s in sources if s.id == current_id)
    baseline_report = _load(baseline_source, workspace)
    current_report = _load(current_source, workspace)
    if baseline_report is None or current_report is None:
        st.error("One of the selected artifacts could not be read.")
        return

    comparison = compare_runs(
        baseline_report,
        current_report,
        max_regression_pct=allowance,
        baseline_label=baseline_source.label,
        current_label=current_source.label,
    )

    level = comparison.compatibility.level
    if level is CompatibilityLevel.INCOMPARABLE:
        st.error(f"**{level.label}** — read the differences below before drawing conclusions.")
    elif level is CompatibilityLevel.CAVEATED:
        st.warning(f"**{level.label}**")
    else:
        st.success(f"**{level.label}**")

    if comparison.compatibility.issues:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Field": issue.field,
                        "Baseline": issue.baseline,
                        "Current": issue.current,
                        "Why it matters": issue.explanation,
                    }
                    for issue in comparison.compatibility.issues
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown(
        f"""<div class="eaiv-banner">
  <div class="eaiv-label">Release recommendation</div>
  <h2>{ui.esc(comparison.recommendation)}</h2>
</div>""",
        unsafe_allow_html=True,
    )

    counts = comparison.counts
    columns = st.columns(6)
    for column, (label, key) in zip(
        columns,
        [
            ("Regressed", "regressed"),
            ("Improved", "improved"),
            ("Unchanged", "unchanged"),
            ("Informational", "informational"),
            ("New", "added"),
            ("Missing", "removed"),
        ],
    ):
        with column:
            ui.tile(label, str(counts[key]))

    chart = _delta_chart(comparison.changes)
    if chart is not None:
        st.plotly_chart(chart, use_container_width=True)

    st.subheader("By suite")
    sort_choice = st.radio(
        "Sort",
        ["Largest regression", "Largest improvement", "Metric name"],
        horizontal=True,
        key="cmp_sort",
    )
    for suite, items in comparison.by_suite().items():
        if sort_choice == "Largest regression":
            items = sorted(items, key=lambda c: (c.change_pct or 0) * (-c.info.direction or 1), reverse=True)
        elif sort_choice == "Largest improvement":
            items = sorted(items, key=lambda c: (c.change_pct or 0) * (c.info.direction or 1), reverse=True)
        else:
            items = sorted(items, key=lambda c: c.metric)
        with st.expander(f"{suite} ({len(items)} metrics)", expanded=suite in {"tinyml", "hil"}):
            st.dataframe(_changes_frame(items), use_container_width=True, hide_index=True)

    if comparison.added or comparison.removed:
        st.subheader("Coverage changes")
        if comparison.added:
            st.caption(
                "New metrics — present in the candidate, absent from the baseline. They cannot "
                "regress yet; promote a new baseline to start tracking them."
            )
            st.dataframe(
                _changes_frame(comparison.added), use_container_width=True, hide_index=True
            )
        if comparison.removed:
            st.caption(
                "Missing metrics — the baseline recorded them and the candidate did not. A "
                "silently dropped metric is a coverage regression."
            )
            st.dataframe(
                _changes_frame(comparison.removed), use_container_width=True, hide_index=True
            )

    st.subheader("Export")
    columns = st.columns(2)
    columns[0].download_button(
        "Download Markdown",
        data=to_markdown(comparison),
        file_name="comparison.md",
        key="cmp_md",
    )
    columns[1].download_button(
        "Download JSON", data=to_json(comparison), file_name="comparison.json", key="cmp_json"
    )


__all__ = ["render"]
