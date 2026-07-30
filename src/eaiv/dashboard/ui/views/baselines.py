"""Baseline Manager — promote, inspect, and retire references.

A baseline is what every future run is judged against, so promotion is
treated as a deliberate act: only fully passing runs can be promoted,
deletion asks for confirmation, and the missions currently gating against
a baseline are listed before you remove it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from eaiv.core.comparison import compare_runs
from eaiv.dashboard.runs import run_sources
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.state import Workspace, goto
from eaiv.runs.models import RunStatus


def _archive_dir(workspace: Workspace) -> Path:
    return workspace.baseline_dir / "archive"


def render(workspace: Workspace) -> None:
    st.subheader("Baselines")
    st.caption(
        "Named reference reports. A run is gated against one of these, and only a fully "
        "passing run may become one."
    )

    store = workspace.baselines
    infos = store.list()
    missions = workspace.missions.list()

    if infos:
        rows = []
        for info in infos:
            users = [m.title for m in missions if m.baseline == info.name]
            rows.append(
                {
                    "": "●" if info.all_passed else "▲",
                    "Baseline": info.name,
                    "Saved": info.saved_at[:19],
                    "Target": info.target,
                    "eaiv": info.eaiv_version,
                    "Verdict": "PASS" if info.all_passed else "FAIL",
                    "Used by missions": ", ".join(users) or "—",
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info(
            "No baselines yet. Promote a passing run below to start gating against it.",
            icon=None,
        )

    st.divider()
    st.markdown("#### Promote a run")
    sources = run_sources(workspace.runs)
    passing = [
        s for s in sources if s.manifest is not None and s.manifest.status is RunStatus.PASSED
    ]
    failing = [s for s in sources if s not in passing]

    if not sources:
        if ui.empty_state(
            "No recorded runs to promote",
            "Run a mission first; a baseline is a snapshot of a run that passed.",
            "New validation run",
            "bl_new",
        ):
            goto("New run")
    elif not passing:
        st.warning(
            f"None of the {len(sources)} recorded run(s) passed, so none can be promoted. "
            "Fix the failures on the Results page first.",
            icon=None,
        )
    else:
        columns = st.columns([2, 1, 1])
        chosen_id = columns[0].selectbox(
            "Passing run",
            [s.id for s in passing],
            format_func=lambda i: next(s.label for s in passing if s.id == i),
            key="bl_run",
        )
        name = columns[1].text_input(
            "Baseline name",
            value="",
            placeholder="release-0.4",
            key="bl_name",
            help="Filename-safe; used with --baseline and in the gate.",
        )
        columns[2].markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        # The button stays enabled and validates on click. Disabling it on an
        # empty name looks broken: Streamlit only commits a text input when it
        # loses focus, so a user who typed a name would still see a greyed-out
        # button until they clicked elsewhere.
        if columns[2].button("Promote", type="primary", key="bl_promote"):
            if not name.strip():
                st.error("Give the baseline a name first.")
                return
            source = next(s for s in passing if s.id == chosen_id)
            report = source.report()
            if report is None:
                st.error("That run's report could not be read.")
            else:
                try:
                    path = store.save(report, name)
                except (OSError, ValueError) as exc:
                    st.error(f"Could not save the baseline: {exc}")
                else:
                    st.success(f"Promoted {source.label} to baseline {name!r} ({path}).")
                    st.rerun()
        if failing:
            st.caption(
                f"{len(failing)} run(s) are hidden here because they did not pass. Promotion of "
                "a failing run is refused by design."
            )

    if not infos:
        return

    st.divider()
    st.markdown("#### Inspect a baseline")
    chosen = st.selectbox("Baseline", [i.name for i in infos], key="bl_inspect")
    try:
        payload = store.load(chosen)
    except (FileNotFoundError, ValueError) as exc:
        st.error(str(exc))
        return

    meta = payload.get("meta") or {}
    columns = st.columns(4)
    with columns[0]:
        ui.tile("Verdict", "PASS" if payload.get("all_passed") else "FAIL")
    with columns[1]:
        ui.tile("Suites", str(len(payload.get("suites") or [])))
    with columns[2]:
        ui.tile("Target", str((meta.get("target") or {}).get("name", "—")))
    with columns[3]:
        ui.tile("eaiv", str(meta.get("eaiv_version", "—")))

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Suite": s.get("name"),
                    "Result": "PASS" if s.get("passed") else "FAIL",
                    "Metrics": len(s.get("metrics") or {}),
                }
                for s in payload.get("suites") or []
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    if sources:
        st.markdown("**Compare a candidate against this baseline**")
        candidate_id = st.selectbox(
            "Candidate run",
            [s.id for s in sources],
            format_func=lambda i: next(s.label for s in sources if s.id == i),
            key="bl_candidate",
        )
        candidate = next(s for s in sources if s.id == candidate_id)
        candidate_report = candidate.report()
        if candidate_report is not None:
            comparison = compare_runs(
                payload,
                candidate_report,
                baseline_label=chosen,
                current_label=candidate.label,
            )
            st.caption(comparison.recommendation)
            counts = comparison.counts
            columns = st.columns(4)
            for column, key in zip(
                columns, ["regressed", "improved", "unchanged", "added"], strict=False
            ):
                with column:
                    ui.tile(key.capitalize(), str(counts[key]))
            if st.button("Open full comparison", key="bl_open_compare"):
                goto("Compare")

    st.divider()
    st.markdown("#### Retire a baseline")
    dependents = [m for m in missions if m.baseline == chosen]
    if dependents:
        st.warning(
            f"{len(dependents)} saved mission(s) gate against {chosen!r}: "
            + ", ".join(m.title for m in dependents)
            + ". They will fail to load this baseline once it is gone.",
            icon=None,
        )
    action = st.radio(
        "Action",
        ["Archive (keep the file)", "Delete permanently"],
        key="bl_action",
        horizontal=True,
    )
    confirm = st.text_input(
        f"Type the baseline name ({chosen}) to confirm", value="", key="bl_confirm"
    )
    if st.button("Apply", disabled=confirm != chosen, key="bl_apply"):
        path = store.path(chosen)
        try:
            if action.startswith("Archive"):
                destination = _archive_dir(workspace)
                destination.mkdir(parents=True, exist_ok=True)
                path.rename(destination / path.name)
                st.success(f"Archived {chosen!r} to {destination}.")
            else:
                path.unlink(missing_ok=True)
                st.success(f"Deleted baseline {chosen!r}.")
        except OSError as exc:
            st.error(f"Could not {action.split()[0].lower()} the baseline: {exc}")
        else:
            st.rerun()


__all__ = ["render"]
