"""Hardware and Plugins — what this installation can actually do.

Everything registered in the plugin registry, what package it came from,
whether its optional dependency is installed, and — for targets that can
say — whether hardware is currently reachable. The same environment
diagnosis as ``eaiv doctor``, rendered.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

import pandas as pd
import streamlit as st

from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.state import Workspace
from eaiv.diagnostics.doctor import CheckStatus, run_diagnostics
from eaiv.plugins import get_registry

#: Setup guidance for plugins whose dependency is not part of the core install.
SETUP_HINTS: dict[str, str] = {
    "jlink": 'pip install -e ".[jlink]" and install the Segger J-Link software.',
    "serial": "Connect the board; pyserial ships with the core install.",
    "qemu": "Install QEMU (qemu-system-arm) and put it on PATH.",
    "sim": "No setup required — this backend runs entirely in software.",
}


def _entry_point_sources() -> dict[str, str]:
    """Map plugin module names to the distribution that provides them."""
    sources: dict[str, str] = {}
    try:
        for entry in entry_points(group="eaiv.plugins"):
            distribution = getattr(entry, "dist", None)
            sources[entry.name] = getattr(distribution, "name", "") or entry.value
    except Exception:  # noqa: BLE001 - entry-point metadata is best effort
        return {}
    return sources


def _dependency_state(dependencies: list[str]) -> tuple[bool, str]:
    """Whether a plugin's declared dependencies import."""
    import importlib.util

    missing = []
    for dependency in dependencies:
        module = dependency.replace("-", "_").split("[")[0]
        aliases = {"pylink_square": "pylink", "tflite_runtime": "tflite_runtime"}
        module = aliases.get(module, module)
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            available = False
        if not available:
            missing.append(dependency)
    return (not missing), ", ".join(missing)


def _probe_target(kind: str, spec: dict[str, Any]) -> tuple[str, str]:
    """Try to connect to a target and report what happened.

    Only attempted on demand: probing hardware has side effects, so it
    never runs as part of rendering the page.
    """
    from eaiv.targets import build_target

    try:
        with build_target({"kind": kind, **spec}) as target:
            info = target.info()
            return "reachable", f"{info.name} · {info.arch} · {info.clock_hz / 1e6:.0f} MHz"
    except Exception as exc:  # noqa: BLE001 - the failure is the answer
        return "unreachable", f"{type(exc).__name__}: {exc}"


def render(workspace: Workspace) -> None:
    st.subheader("Hardware and plugins")
    st.caption(
        "Everything this installation can drive. Backends, filters, fault models, power "
        "monitors, and telemetry adapters all come from the same registry the CLI uses."
    )

    registry = get_registry()
    plugins = registry.list_plugins()
    sources = _entry_point_sources()

    rows = []
    for meta in sorted(plugins, key=lambda p: (p.plugin_type, p.name)):
        available, missing = _dependency_state(meta.dependencies)
        rows.append(
            {
                "": "●" if available else "▲",
                "Type": meta.plugin_type,
                "Name": meta.name,
                "Version": meta.version,
                "Available": "yes" if available else "missing dependency",
                "Missing": missing or "—",
                "Package": sources.get(meta.name, "eaiv (built-in)"),
                "Description": meta.description,
            }
        )
    frame = pd.DataFrame(rows)
    types = sorted({str(r["Type"]) for r in rows})
    chosen_types = st.multiselect("Plugin type", types, default=types, key="inv_types")
    st.dataframe(
        frame[frame["Type"].isin(chosen_types)] if chosen_types else frame,
        use_container_width=True,
        hide_index=True,
    )

    unavailable = [r for r in rows if r["Available"] != "yes"]
    if unavailable:
        st.markdown("**Setup needed**")
        for row in unavailable:
            hint = SETUP_HINTS.get(str(row["Name"]), f"Install: {row['Missing']}")
            st.caption(f"`{row['Type']}:{row['Name']}` — {hint}")

    st.divider()
    st.markdown("#### Target connection check")
    st.caption(
        "Probing a target opens the transport, so it runs only when you ask. The simulated "
        "backend always succeeds and touches no hardware."
    )
    target_names = [p.name for p in registry.list_plugins("target")]
    columns = st.columns([1, 2, 1])
    kind = columns[0].selectbox("Target", target_names, key="inv_target")
    port = columns[1].text_input(
        "Port / device (optional)", value="", placeholder="/dev/ttyACM0", key="inv_port"
    )
    columns[2].markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
    if columns[2].button("Probe", key="inv_probe"):
        spec: dict[str, Any] = {}
        if port and kind == "serial":
            spec["serial"] = {"port": port}
        state, detail = _probe_target(str(kind), spec)
        if state == "reachable":
            st.success(f"{kind}: {detail}")
        else:
            st.error(f"{kind}: {detail}")
            st.caption(SETUP_HINTS.get(str(kind), ""))

    st.divider()
    st.markdown("#### Environment")
    if st.button("Run full diagnosis", key="inv_doctor"):
        st.session_state["inv_diagnosis"] = run_diagnostics(
            report_dir=workspace.report_dir, dataset_dir=workspace.dataset_dir
        )
    diagnosis = st.session_state.get("inv_diagnosis")
    if diagnosis is None:
        st.caption("Equivalent command: `eaiv doctor`")
        return
    columns = st.columns(3)
    with columns[0]:
        ui.tile("Checks", str(len(diagnosis.checks)))
    with columns[1]:
        ui.tile("Failures", str(len(diagnosis.failures)), tone_css="fail" if diagnosis.failures else "")
    with columns[2]:
        ui.tile("Warnings", str(len(diagnosis.warnings)))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "": {
                        CheckStatus.OK: "●",
                        CheckStatus.WARN: "■",
                        CheckStatus.FAIL: "▲",
                        CheckStatus.SKIP: "–",
                    }[check.status],
                    "Category": check.category,
                    "Check": check.name,
                    "Status": check.status.label,
                    "Detail": check.detail,
                    "Fix": check.fix,
                }
                for check in diagnosis.checks
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


__all__ = ["render"]
