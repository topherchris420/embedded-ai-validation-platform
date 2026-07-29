"""Per-session workspace: where things live and how they are cached.

Streamlit re-executes the whole script on every interaction, so anything
expensive needs a cache and anything stateful needs to live outside the
script. This module owns both: the resolved directories for the session,
the stores built on top of them, and cached report parsing keyed on file
mtime so a rewritten report is picked up without a manual refresh.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from eaiv.core.baseline import BaselineStore
from eaiv.configspec.presets import MissionStore
from eaiv.dashboard.safety import PathPolicy
from eaiv.runs.store import RunStore

DEFAULT_REPORT_DIR = os.environ.get("EAIV_REPORT_DIR", "reports")
DEFAULT_BASELINE_DIR = os.environ.get("EAIV_BASELINE_DIR", "baselines")
DEFAULT_MISSION_DIR = os.environ.get("EAIV_MISSION_DIR", "missions")
DEFAULT_DATASET_DIR = os.environ.get("EAIV_DATASET_DIR", "datasets")


@dataclass(frozen=True)
class Workspace:
    """Every location and store one dashboard session works with."""

    report_dir: Path
    baseline_dir: Path
    mission_dir: Path
    dataset_dir: Path

    @property
    def runs(self) -> RunStore:
        return RunStore(self.report_dir)

    @property
    def baselines(self) -> BaselineStore:
        return BaselineStore(self.baseline_dir)

    @property
    def missions(self) -> MissionStore:
        return MissionStore(self.mission_dir)

    @property
    def policy(self) -> PathPolicy:
        """Directories this session may read files from."""
        return PathPolicy.build(
            Path.cwd(), self.report_dir, self.dataset_dir, self.baseline_dir, self.mission_dir
        )


def workspace() -> Workspace:
    """The active workspace, seeded from the environment and editable in the sidebar."""
    state = st.session_state
    return Workspace(
        report_dir=Path(state.get("report_dir", DEFAULT_REPORT_DIR)),
        baseline_dir=Path(state.get("baseline_dir", DEFAULT_BASELINE_DIR)),
        mission_dir=Path(state.get("mission_dir", DEFAULT_MISSION_DIR)),
        dataset_dir=Path(state.get("dataset_dir", DEFAULT_DATASET_DIR)),
    )


def goto(page: str, **params: Any) -> None:
    """Navigate to another page, carrying parameters through session state."""
    st.session_state["page"] = page
    for key, value in params.items():
        st.session_state[key] = value
    st.rerun()


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False, max_entries=128)
def _cached_report(path_text: str, mtime: float) -> dict[str, Any] | None:
    """Parse a report file, keyed on (path, mtime) so edits invalidate it."""
    from eaiv.core.report_schema import load_report_file

    del mtime  # part of the cache key only
    try:
        return load_report_file(path_text)
    except (OSError, ValueError):
        return None


def load_report(path: str | Path) -> dict[str, Any] | None:
    """Cached, normalized report load. Returns None for unreadable files."""
    file = Path(path)
    return _cached_report(str(file), _mtime(file))


@st.cache_data(show_spinner=False, max_entries=32)
def _cached_csv_head(path_text: str, mtime: float, max_rows: int) -> dict[str, Any]:
    """Read a bounded CSV preview without pulling the whole file into memory."""
    import csv

    del mtime
    rows: list[dict[str, str]] = []
    truncated = False
    with Path(path_text).open("r", newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if index >= max_rows:
                truncated = True
                break
            rows.append(row)
        columns = list(reader.fieldnames or [])
    return {"rows": rows, "columns": columns, "truncated": truncated}


def load_csv_preview(path: str | Path, max_rows: int = 200_000) -> dict[str, Any]:
    """Cached CSV read capped at ``max_rows`` data rows."""
    file = Path(path)
    return _cached_csv_head(str(file), _mtime(file), max_rows)


def clear_caches() -> None:
    _cached_report.clear()
    _cached_csv_head.clear()


__all__ = [
    "DEFAULT_BASELINE_DIR",
    "DEFAULT_DATASET_DIR",
    "DEFAULT_MISSION_DIR",
    "DEFAULT_REPORT_DIR",
    "Workspace",
    "clear_caches",
    "goto",
    "load_csv_preview",
    "load_report",
    "workspace",
]
