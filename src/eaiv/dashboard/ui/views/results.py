"""Results and Diagnosis — what happened, and what it means.

The table of numbers comes second. First is the diagnosis: for every
failure and regression, what the observed value was, what it was measured
against, how big the miss is, why the metric matters, and the next step.
All of it comes from the deterministic insight engine, so nothing on this
page is an assertion the run's own data cannot support.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from eaiv.core.metrics import format_value
from eaiv.core.regression import compare_reports
from eaiv.core.report_schema import metric_info
from eaiv.dashboard.data import latency_percentiles, numeric_metrics
from eaiv.dashboard.runs import all_sources
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.state import Workspace, goto
from eaiv.insights import decide, generate_insights
from eaiv.insights.models import Severity


def _suite_table(report: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for suite in report.get("suites") or []:
        rows.append(
            {
                "": "●" if suite.get("passed") else "▲",
                "Suite": suite.get("name", "?"),
                "Result": "PASS" if suite.get("passed") else "FAIL",
                "Metrics": len(suite.get("metrics") or {}),
                "Notes": str(suite.get("notes", ""))[:110],
            }
        )
    return pd.DataFrame(rows)


def _metric_table(report: dict[str, Any], suite: str) -> pd.DataFrame:
    entry: dict[str, Any] = next(
        (s for s in report.get("suites") or [] if s.get("name") == suite),
        {},
    )
    rows = []
    for name, value in (entry.get("metrics") or {}).items():
        if isinstance(value, dict):
            continue
        info = metric_info(report, suite, name)
        rows.append(ui.metric_row(name, value, info))
    return pd.DataFrame(rows)


def _latency_chart(metrics: dict[str, float]) -> go.Figure | None:
    percentiles = latency_percentiles(metrics)
    if len(percentiles) < 2:
        return None
    figure = go.Figure(
        go.Bar(
            x=list(percentiles.keys()),
            y=list(percentiles.values()),
            marker_color="#2f6f9f",
            text=[f"{v:.2f}" for v in percentiles.values()],
            textposition="outside",
        )
    )
    figure.update_layout(
        height=260,
        margin={"l": 10, "r": 10, "t": 24, "b": 10},
        yaxis_title="ms",
        xaxis_title="",
        title="Inference latency distribution",
    )
    return figure


def render(workspace: Workspace) -> None:
    store = workspace.runs
    store.reconcile_all()
    sources = all_sources(store, workspace.report_dir)
    if not sources:
        if ui.empty_state(
            "No results yet",
            "Run a validation mission — or the simulated demo from Mission Control — and its "
            "diagnosis will appear here.",
            "New validation run",
            "results_new",
        ):
            goto("New run")
        return

    preselected = st.session_state.get("results_run_id", "")
    ids = [s.id for s in sources]
    index = ids.index(preselected) if preselected in ids else 0
    labels = {s.id: s.label for s in sources}
    chosen = st.selectbox(
        "Run", ids, index=index, format_func=lambda i: labels.get(i, i), key="results_select"
    )
    source = next(s for s in sources if s.id == chosen)
    st.session_state["results_run_id"] = chosen

    report = source.report()
    if report is None:
        st.error(f"The report for {source.label} could not be read.")
        return

    manifest = source.manifest
    baseline_report = None
    baseline_name = manifest.baseline if manifest else ""
    if baseline_name:
        try:
            baseline_report = workspace.baselines.load(baseline_name)
        except (FileNotFoundError, ValueError):
            baseline_report = None
    regression = (
        compare_reports(
            baseline_report,
            report,
            max_regression_pct=manifest.max_regression_pct if manifest else 10.0,
        )
        if baseline_report
        else None
    )

    insights = generate_insights(
        report, regression=regression, manifest=manifest, baseline_name=baseline_name
    )
    decision = decide(report, insights)
    ui.verdict_banner(decision, source.label)
    ui.provenance_note(source.provenance)

    if source.kind == "legacy":
        st.caption(
            "This is a legacy report file with no run manifest. Stage timings, event log, and "
            "reproduction context are unavailable for it."
        )

    tabs = st.tabs(["Diagnosis", "Suites and metrics", "Reproduction", "Artifacts"])

    with tabs[0]:
        if not insights:
            st.success("No findings: every suite passed with no threshold or budget concerns.")
        blocking = [i for i in insights if i.severity.blocks_release]
        others = [i for i in insights if not i.severity.blocks_release]
        if blocking:
            st.markdown(f"**{len(blocking)} release-blocking finding(s)**")
            for insight in blocking:
                ui.insight_card(insight)
        if others:
            st.markdown(f"**{len(others)} further observation(s)**")
            for insight in others:
                ui.insight_card(insight)
        counts = {
            severity.label: sum(1 for i in insights if i.severity is severity)
            for severity in Severity
        }
        st.caption(
            "Findings by severity: "
            + ", ".join(f"{label} {count}" for label, count in counts.items() if count)
        )

    with tabs[1]:
        st.dataframe(_suite_table(report), width="stretch", hide_index=True)
        suites = [str(s.get("name")) for s in report.get("suites") or []]
        if suites:
            suite = st.selectbox("Suite detail", suites, key="results_suite")
            metrics = numeric_metrics(report, suite)
            chart = _latency_chart(metrics)
            if chart is not None:
                st.plotly_chart(chart, width="stretch")
            table = _metric_table(report, suite)
            if not table.empty:
                st.dataframe(table, width="stretch", hide_index=True)
            entry: dict[str, Any] = next(
                (s for s in report.get("suites") or [] if s.get("name") == suite), {}
            )
            nested = {k: v for k, v in (entry.get("metrics") or {}).items() if isinstance(v, dict)}
            for name, values in nested.items():
                st.markdown(f"**{name}**")
                st.dataframe(
                    pd.DataFrame(
                        [
                            ui.metric_row(k, v, metric_info(report, suite, f"{name}.{k}"))
                            for k, v in values.items()
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            if entry.get("notes"):
                st.caption(f"Suite notes: {entry['notes']}")

    with tabs[2]:
        meta = report.get("meta") or {}
        rows = [
            ("eaiv version", meta.get("eaiv_version", "—")),
            ("Report schema", report.get("schema_version", 1)),
            ("Target", str(meta.get("target", {}))),
            ("Git", str(meta.get("git", {}) or "not recorded")),
            ("Host", str(meta.get("host", {}) or "not recorded")),
            ("Baseline", baseline_name or "none"),
        ]
        st.dataframe(
            pd.DataFrame([{"Field": k, "Value": str(v)} for k, v in rows]),
            width="stretch",
            hide_index=True,
        )
        inputs = meta.get("inputs") or {}
        if inputs:
            st.markdown("**Inputs**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Input": key,
                            "Path": value.get("path", ""),
                            "Present": "yes" if value.get("exists") else "no",
                            "SHA-256": (value.get("sha256") or "")[:16],
                            "Size": value.get("size_bytes", ""),
                        }
                        for key, value in inputs.items()
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        thresholds = meta.get("thresholds") or {}
        if thresholds:
            st.markdown("**Thresholds applied**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Threshold": k, "Value": format_value(v)}
                        for k, v in sorted(thresholds.items())
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        if meta.get("config"):
            import yaml

            with st.expander("Resolved configuration"):
                st.code(yaml.safe_dump(meta["config"], sort_keys=False), language="yaml")

    with tabs[3]:
        if manifest is None or not manifest.artifacts:
            st.caption("No recorded artifacts for this run.")
        else:
            for artifact in manifest.artifacts:
                try:
                    path = store.artifact_path(manifest.run_id, artifact.path)
                except ValueError:
                    continue
                if not path.exists():
                    continue
                st.download_button(
                    f"{artifact.name} — {artifact.description or artifact.kind}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=f"res_dl_{manifest.run_id}_{artifact.name}",
                )


__all__ = ["render"]
