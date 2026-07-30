"""EAIV Mission Control — Streamlit entry point.

Run it with the CLI (``eaiv dashboard``) or directly:

    streamlit run src/eaiv/dashboard/ui/app.py

This module wires navigation and workspace settings; every page lives in
``eaiv.dashboard.ui.views`` and every calculation lives in the core
packages.
"""

from __future__ import annotations

import logging
import traceback

import pandas as pd
import streamlit as st

from eaiv.dashboard.ui import theme
from eaiv.dashboard.ui.state import (
    DEFAULT_BASELINE_DIR,
    DEFAULT_DATASET_DIR,
    DEFAULT_MISSION_DIR,
    DEFAULT_REPORT_DIR,
    clear_caches,
    workspace,
)
from eaiv.dashboard.ui.views import (
    baselines,
    compare,
    inventory,
    live_run,
    mission_control,
    new_run,
    results,
    telemetry_lab,
)

log = logging.getLogger("eaiv.dashboard")

PAGES = {
    "Mission Control": mission_control.render,
    "New run": new_run.render,
    "Live run": live_run.render,
    "Results": results.render,
    "Compare": compare.render,
    "Telemetry Lab": telemetry_lab.render,
    "Baselines": baselines.render,
    "Hardware & plugins": inventory.render,
}


def _configure_pandas() -> None:
    """Keep string columns on the python backend.

    Pyarrow-backed string arrays have crashed natively when frames are
    built on Streamlit's script thread (observed with pandas 3.x + pyarrow
    25). The frames here are tiny, so the arrow fast path buys nothing.
    """
    try:
        pd.set_option("mode.string_storage", "python")
    except (pd.errors.OptionError, AttributeError, KeyError):
        log.debug("pandas string_storage option unavailable; leaving the default")


def _load_plugins() -> None:
    """Register built-in plugins and discover external ones, once."""
    if st.session_state.get("_plugins_loaded"):
        return
    from eaiv.cli import _load_all_plugins

    try:
        _load_all_plugins()
    except Exception as exc:  # noqa: BLE001 - a broken plugin must not blank the app
        st.sidebar.error(f"A plugin failed to load: {exc}")
    st.session_state["_plugins_loaded"] = True


def _sidebar() -> str:
    with st.sidebar:
        st.markdown("### EAIV Mission Control")
        st.caption("Embedded AI validation")
        page = st.radio(
            "Navigation",
            list(PAGES),
            index=list(PAGES).index(st.session_state.get("page", "Mission Control")),
            key="page",
            label_visibility="collapsed",
        )
        st.divider()
        with st.expander("Workspace", expanded=False):
            st.text_input("Report directory", value=DEFAULT_REPORT_DIR, key="report_dir")
            st.text_input("Baseline directory", value=DEFAULT_BASELINE_DIR, key="baseline_dir")
            st.text_input("Mission directory", value=DEFAULT_MISSION_DIR, key="mission_dir")
            st.text_input("Dataset directory", value=DEFAULT_DATASET_DIR, key="dataset_dir")
            if st.button("Reload from disk", key="reload"):
                clear_caches()
                st.rerun()
        st.divider()
        st.caption(
            "Simulated, mock, and estimated values are labelled wherever they appear. "
            "Only metrics marked **measured** came from real measurement."
        )
    return str(page)


def main() -> None:
    st.set_page_config(
        page_title="EAIV Mission Control",
        page_icon="◎",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.inject()
    _configure_pandas()
    _load_plugins()
    page = _sidebar()
    space = workspace()
    try:
        PAGES[page](space)
    except Exception as exc:  # noqa: BLE001 - show the failure, keep the app usable
        st.error(f"{type(exc).__name__} while rendering {page}: {exc}")
        with st.expander("Details"):
            st.code(traceback.format_exc(), language="text")
        st.caption("Run `eaiv doctor` for a full diagnosis of this installation.")


if __name__ == "__main__":
    main()
