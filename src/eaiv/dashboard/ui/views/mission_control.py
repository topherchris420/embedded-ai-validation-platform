"""Mission Control — the landing page.

It answers six questions before the engineer clicks anything: is this
safe to ship, what changed since the baseline, what was it tested on,
what is the worst problem, what should I do next, and when did validation
last pass.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from eaiv.dashboard.runs import all_sources, recent_activity
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.state import Workspace, goto
from eaiv.dashboard.ui.theme import chip, status_tone
from eaiv.insights import decide, generate_insights
from eaiv.runs.models import RunManifest, RunStatus


def _headroom(report: dict[str, Any]) -> tuple[str, str]:
    """Tightest configured budget and how much of it is left."""
    thresholds = (report.get("meta") or {}).get("thresholds") or {}
    metrics: dict[str, Any] = {}
    for suite in report.get("suites") or []:
        if suite.get("name") == "memory":
            metrics = suite.get("metrics") or {}
    pairs = (
        ("rom_kb", "memory.max_rom_kb", "Flash"),
        ("ram_static_kb", "memory.max_ram_kb", "Static RAM"),
    )
    tightest: tuple[float, str, str] | None = None
    for metric, threshold_key, label in pairs:
        used = metrics.get(metric)
        budget = thresholds.get(threshold_key)
        if not isinstance(used, (int, float)) or not isinstance(budget, (int, float)):
            continue
        if budget <= 0:
            continue
        remaining = float(budget) - float(used)
        fraction = remaining / float(budget)
        if tightest is None or fraction < tightest[0]:
            tightest = (fraction, f"{remaining:,.1f} KB", f"{label}, {fraction:.0%} of budget left")
    if tightest is None:
        return "—", "No memory budget configured"
    return tightest[1], tightest[2]


def _activity_chart(points: list[Any]) -> go.Figure:
    frame = pd.DataFrame(
        [
            {
                "run": p.name,
                "when": p.timestamp[:19],
                "pass rate": (p.passed_suites / p.total_suites) if p.total_suites else 0.0,
                "status": p.status,
                "target": p.target,
            }
            for p in points
        ]
    )
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=frame["when"],
            y=frame["pass rate"],
            mode="lines+markers",
            name="suite pass rate",
            line={"color": "#2f6f9f", "width": 2},
            marker={
                "size": 10,
                "symbol": [
                    "circle" if s == "passed" else "triangle-up" if s == "failed" else "square"
                    for s in frame["status"]
                ],
            },
            hovertemplate="%{customdata[0]}<br>%{x}<br>pass rate %{y:.0%}<br>%{customdata[1]}",
            customdata=frame[["run", "status"]].to_numpy(),
        )
    )
    figure.update_layout(
        height=240,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        yaxis={"title": "suite pass rate", "tickformat": ".0%", "range": [-0.05, 1.05]},
        xaxis={"title": ""},
        showlegend=False,
    )
    return figure


def _no_data(workspace: Workspace) -> None:
    st.markdown(
        """<div class="eaiv-banner">
  <div class="eaiv-label">Getting started</div>
  <h2>No validation runs recorded yet</h2>
  <p>Mission Control needs at least one run before it can judge anything.
     The demo below produces three complete runs against the simulated device —
     no board, no toolchain, no model weights required.</p>
</div>""",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Run the simulated demo**")
        st.caption(
            "Three real runs: a reference build, a candidate gated against it, and one whose "
            "sensor stream is degraded until the fusion filter genuinely fails. Every metric "
            "is labelled as simulated."
        )
        if st.button("Run simulated demo", type="primary", key="mc_demo"):
            _run_demo(workspace)
    with right:
        st.markdown("**Build your own mission**")
        st.caption(
            "Pick a preset, choose a target, review the resolved configuration, and launch. "
            "The mission builder writes the YAML for you."
        )
        if st.button("New validation run", key="mc_new_from_empty"):
            goto("New run")


def _run_demo(workspace: Workspace) -> None:
    from eaiv.diagnostics import run_demo

    with st.spinner("Running three simulated validations..."):
        try:
            result = run_demo(
                report_dir=workspace.report_dir,
                baseline_dir=workspace.baseline_dir,
                dataset_dir=workspace.dataset_dir,
                mission_dir=workspace.mission_dir,
            )
        except Exception as exc:  # noqa: BLE001 - surface the reason, keep the app alive
            st.error(f"The demo could not complete: {exc}")
            st.caption("Run `eaiv doctor` for a full diagnosis of the environment.")
            return
    st.success(
        f"Recorded {len(result.runs)} simulated runs and the baseline "
        f"{result.baseline!r}. All measurements are labelled simulated."
    )
    st.rerun()


def render(workspace: Workspace) -> None:
    store = workspace.runs
    store.reconcile_all()
    manifests = store.list(limit=40)
    sources = all_sources(store, workspace.report_dir)

    if not manifests and not sources:
        _no_data(workspace)
        return

    latest_manifest: RunManifest | None = manifests[0] if manifests else None
    latest_source = sources[0] if sources else None
    report = latest_source.report() if latest_source else None

    running = [m for m in manifests if m.status is RunStatus.RUNNING]
    if running:
        st.info(
            f"{len(running)} run(s) in progress: {', '.join(m.display_name for m in running)}",
            icon=None,
        )
        if st.button("Open live run", key="mc_open_live"):
            goto("Live run", live_run_id=running[0].run_id)

    insights = (
        generate_insights(
            report,
            manifest=latest_manifest,
            baseline_name=latest_manifest.baseline if latest_manifest else "",
        )
        if report
        else []
    )
    decision = decide(report, insights)
    subtitle = ""
    if latest_manifest is not None:
        subtitle = (
            f"Latest run {latest_manifest.display_name} · "
            f"{latest_manifest.created_at[:19]} · target {latest_manifest.target_label}"
        )
    ui.verdict_banner(decision, subtitle)

    action_col, spacer = st.columns([1, 3])
    with action_col:
        if st.button("New validation run", type="primary", key="mc_new"):
            goto("New run")
    del spacer

    st.divider()

    last_pass = store.latest_successful()
    passed_suites = latest_manifest.summary.passed_suites if latest_manifest else 0
    total_suites = latest_manifest.summary.total_suites if latest_manifest else 0
    if total_suites == 0 and report:
        suites = report.get("suites") or []
        total_suites = len(suites)
        passed_suites = sum(1 for s in suites if s.get("passed"))
    regressions = latest_manifest.summary.regressions if latest_manifest else 0
    worst = latest_manifest.summary.worst_regression if latest_manifest else None
    headroom_value, headroom_sub = _headroom(report) if report else ("—", "No report")

    columns = st.columns(3)
    with columns[0]:
        tone = status_tone(str(latest_manifest.status) if latest_manifest else "unknown")
        ui.tile(
            "Latest run",
            tone.label,
            (latest_manifest.created_at[:19] if latest_manifest else "—"),
            tone.css,
        )
    with columns[1]:
        ui.tile(
            "Target",
            (
                latest_manifest.target_label
                if latest_manifest
                else (latest_source.target if latest_source else "—")
            ),
            (report or {}).get("meta", {}).get("target", {}).get("arch", "") or "",
        )
    with columns[2]:
        rate = f"{passed_suites}/{total_suites}" if total_suites else "—"
        ui.tile(
            "Suites passed",
            rate,
            f"{(passed_suites / total_suites):.0%} pass rate" if total_suites else "",
        )

    columns = st.columns(3)
    with columns[0]:
        ui.tile(
            "Regressions",
            str(regressions),
            (
                f"worst: {worst['suite']}.{worst['metric']} {worst['change_pct']:+.1f}%"
                if worst
                else (
                    "vs baseline"
                    if latest_manifest and latest_manifest.baseline
                    else "no baseline gate"
                )
            ),
        )
    with columns[1]:
        ui.tile("Budget headroom", headroom_value, headroom_sub)
    with columns[2]:
        ui.tile(
            "Last successful validation",
            last_pass.created_at[:19] if last_pass else "never",
            last_pass.display_name if last_pass else "No run has passed yet",
        )

    st.markdown("")
    if report:
        ui.provenance_note(latest_manifest.provenance if latest_manifest else "unknown")

    st.divider()
    left, right = st.columns([3, 2])

    with left:
        st.subheader("What to do next")
        if not insights:
            st.caption("No findings — every suite passed with no threshold or budget concerns.")
        for insight in insights[:3]:
            ui.insight_card(insight)
        if len(insights) > 3 and st.button(
            f"See all {len(insights)} findings", key="mc_all_insights"
        ):
            goto("Results", results_run_id=latest_manifest.run_id if latest_manifest else "")

    with right:
        st.subheader("Recent runs")
        points = recent_activity(store, limit=15)
        if len(points) >= 2:
            st.plotly_chart(_activity_chart(points), use_container_width=True)
        rows = []
        for manifest in manifests[:8]:
            tone = status_tone(str(manifest.status))
            rows.append(
                {
                    "": tone.glyph,
                    "Run": manifest.display_name,
                    "Status": tone.label,
                    "When": manifest.created_at[:16],
                    "Target": manifest.target_label,
                }
            )
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        legacy = [s for s in sources if s.kind == "legacy"]
        if legacy:
            st.caption(
                f"{len(legacy)} legacy report file(s) without a run manifest are also "
                "available on the Compare page."
            )
        st.markdown(
            "Status glyphs: "
            + " ".join(chip(status_tone(s)) for s in ("passed", "failed", "cancelled", "running")),
            unsafe_allow_html=True,
        )


__all__ = ["render"]
