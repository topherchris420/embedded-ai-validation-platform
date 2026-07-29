"""Live Run — watch a mission execute.

Everything on this page is read from the run directory rather than from
session memory, so refreshing the browser, opening a second tab, or
restarting the server all show the same run in the same state. A run that
died with its process shows up as interrupted instead of spinning
forever.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from eaiv.dashboard.runs import stage_timeline
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.runner import get_launcher
from eaiv.dashboard.ui.state import Workspace, goto
from eaiv.runs.events import EventKind
from eaiv.runs.models import RunStatus

#: How often the live view refreshes itself while a run is in flight.
REFRESH_SECONDS = 2


def _pick_run(workspace: Workspace) -> str | None:
    store = workspace.runs
    manifests = store.list(limit=40)
    if not manifests:
        return None
    running = [m for m in manifests if m.status is RunStatus.RUNNING]
    default = st.session_state.get("live_run_id") or (
        running[0].run_id if running else manifests[0].run_id
    )
    ids = [m.run_id for m in manifests]
    labels = {m.run_id: f"{m.display_name} · {str(m.status)} · {m.created_at[:19]}" for m in manifests}
    if default not in ids:
        default = ids[0]
    chosen = st.selectbox(
        "Run",
        ids,
        index=ids.index(default),
        format_func=lambda rid: labels.get(rid, rid),
        key="live_run_select",
    )
    st.session_state["live_run_id"] = chosen
    return str(chosen)


def _render_body(workspace: Workspace, run_id: str) -> None:
    store = workspace.runs
    try:
        manifest = store.load(run_id)
    except (OSError, ValueError) as exc:
        st.error(f"Cannot read run {run_id}: {exc}")
        return

    ui.run_header(manifest)

    launcher = get_launcher(workspace.report_dir, workspace.baseline_dir)
    is_active = manifest.status in (RunStatus.RUNNING, RunStatus.PENDING)
    columns = st.columns([1, 1, 2])
    with columns[0]:
        if is_active:
            if store.cancel_requested(run_id):
                st.caption("Cancellation requested — stopping after the current stage.")
            elif st.button("Cancel run", key=f"cancel_{run_id}"):
                launcher.cancel(run_id)
                st.rerun()
        elif manifest.status.is_terminal:
            if st.button("Open results", type="primary", key=f"results_{run_id}"):
                goto("Results", results_run_id=run_id)
    with columns[1]:
        if is_active and not launcher.is_live_here(run_id):
            st.caption("Started by another session — status is read from disk.")

    if manifest.failure is not None:
        with st.container():
            st.error(
                f"**{manifest.failure.type}** in stage `{manifest.failure.stage or '—'}`  \n"
                f"{manifest.failure.message}"
            )
            if manifest.failure.hint:
                st.caption(manifest.failure.hint)
            if manifest.failure.traceback:
                with st.expander("Traceback"):
                    st.code(manifest.failure.traceback, language="text")

    st.subheader("Pipeline stages")
    ui.stage_timeline(stage_timeline(manifest))

    events = store.events(run_id)
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Log")
        lines = [
            f"{e.timestamp[11:23]}  {str(e.kind):<16} {e.stage or '-':<12} {e.message}"
            for e in events
        ]
        ui.log_block(lines[-400:], "Waiting for the first event...")

    with right:
        st.subheader("Suites")
        suite_events = [
            e for e in events if e.kind in (EventKind.SUITE_PASSED, EventKind.SUITE_FAILED)
        ]
        if suite_events:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Suite": e.data.get("suite", "?"),
                            "Result": "PASS" if e.kind is EventKind.SUITE_PASSED else "FAIL",
                            "Notes": str(e.data.get("notes", ""))[:80],
                        }
                        for e in suite_events
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No suite has reported yet.")

        st.subheader("Metrics as they arrive")
        metric_events = [e for e in events if e.kind is EventKind.METRIC]
        if metric_events:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Suite": e.data.get("suite", ""),
                            "Metric": e.data.get("metric", ""),
                            "Value": e.data.get("value", ""),
                            "Unit": e.data.get("unit", ""),
                        }
                        for e in metric_events[-60:]
                    ]
                ),
                use_container_width=True,
                hide_index=True,
                height=260,
            )
        else:
            st.caption("No metrics recorded yet.")

        connected = [e for e in events if e.kind is EventKind.TARGET_CONNECTED]
        if connected:
            info = connected[-1].data
            st.subheader("Connected target")
            st.dataframe(
                pd.DataFrame([{"Property": k, "Value": v} for k, v in info.items()]),
                use_container_width=True,
                hide_index=True,
            )

        if manifest.artifacts:
            st.subheader("Artifacts")
            for artifact in manifest.artifacts:
                try:
                    path = store.artifact_path(run_id, artifact.path)
                except ValueError:
                    continue
                if not path.exists():
                    continue
                st.download_button(
                    f"{artifact.name} ({artifact.size_bytes:,} bytes)",
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=f"dl_{run_id}_{artifact.name}",
                )


def render(workspace: Workspace) -> None:
    st.subheader("Live run")
    workspace.runs.reconcile_all()
    run_id = _pick_run(workspace)
    if run_id is None:
        ui.empty_state(
            "No runs to watch",
            "Start a mission and this page will show its stages, logs, and metrics as they "
            "arrive.",
            "New validation run",
            "live_new",
        ) and goto("New run")
        return

    manifest = workspace.runs.load(run_id)
    if manifest.status in (RunStatus.RUNNING, RunStatus.PENDING):
        st.caption(f"Refreshing every {REFRESH_SECONDS}s while the run is active.")
        fragment = getattr(st, "fragment", None)
        if fragment is not None:

            @fragment(run_every=f"{REFRESH_SECONDS}s")
            def _live() -> None:
                _render_body(workspace, run_id)

            _live()
            return
        if st.button("Refresh", key="live_manual_refresh"):
            st.rerun()
    _render_body(workspace, run_id)


__all__ = ["REFRESH_SECONDS", "render"]
