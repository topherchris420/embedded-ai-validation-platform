"""New Validation Run — the guided mission builder.

Seven steps, in the order an engineer actually thinks: choose the target,
point at the inputs, pick the suites, set the limits, choose the gate,
review the resolved configuration, launch. Every choice offered here is
read from the plugin registry and the config schema, so a target or a
fault model contributed by a plugin appears without a line of UI change.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from eaiv.configspec import (
    PRESETS,
    FieldSpec,
    FieldType,
    MissionStore,
    default_config,
    field_choices,
    fields_for_target,
    get_nested,
    get_preset,
    plugin_choices,
    preview_command,
    set_nested,
    validate_for_suite,
)
from eaiv.configspec.schema import SCHEMA, SECTIONS_BY_NAME, SectionSpec
from eaiv.core.orchestrator import BUILTIN_SUITES, SUITE_CONFIG_SECTION
from eaiv.dashboard.ui import components as ui
from eaiv.dashboard.ui.runner import LaunchSpec, get_launcher
from eaiv.dashboard.ui.state import Workspace, goto

_STATE_KEY = "mission_config"
_PRESET_KEY = "mission_preset"


def _config() -> dict[str, Any]:
    if _STATE_KEY not in st.session_state:
        preset = get_preset(st.session_state.get(_PRESET_KEY, "sim-release-gate"))
        st.session_state[_STATE_KEY] = preset.build()
    config: dict[str, Any] = st.session_state[_STATE_KEY]
    return config


def _apply_preset(preset_id: str) -> None:
    preset = get_preset(preset_id)
    st.session_state[_PRESET_KEY] = preset_id
    st.session_state[_STATE_KEY] = preset.build()
    st.session_state["mission_suite"] = preset.suite
    st.session_state["mission_telemetry_s"] = preset.telemetry_s
    st.session_state["mission_max_regression"] = preset.max_regression_pct


def _widget(section: str, spec: FieldSpec, config: dict[str, Any]) -> None:
    """Render one schema field and write it back into the mission config."""
    path = f"{section}.{spec.key}"
    current = get_nested(config.setdefault(section, {}), spec.key)
    if current is None:
        current = spec.default
    label = spec.label + (f" ({spec.unit})" if spec.unit else "")
    help_text = spec.description or None
    key = f"field::{path}"

    if spec.type is FieldType.ENUM:
        options = field_choices(spec)
        if not options:
            st.caption(f"{label}: no plugins registered for this field.")
            return
        if current not in options:
            current = spec.default if spec.default in options else options[0]
        value: Any = st.selectbox(
            label, options, index=options.index(current), help=help_text, key=key
        )
    elif spec.type is FieldType.BOOLEAN:
        value = st.checkbox(label, value=bool(current), help=help_text, key=key)
    elif spec.type is FieldType.INTEGER:
        value = int(
            st.number_input(
                label,
                value=int(current if current is not None else 0),
                step=1,
                min_value=int(spec.minimum) if spec.minimum is not None else None,
                max_value=int(spec.maximum) if spec.maximum is not None else None,
                help=help_text,
                key=key,
            )
        )
    elif spec.type is FieldType.FLOAT:
        value = float(
            st.number_input(
                label,
                value=float(current if current is not None else 0.0),
                help=help_text,
                key=key,
                format="%g",
            )
        )
    elif spec.type is FieldType.LIST or spec.type is FieldType.MAPPING:
        st.caption(f"{label} — edit in the YAML review step below.")
        return
    else:
        value = st.text_input(
            label,
            value=str(current if current is not None else ""),
            help=help_text,
            placeholder=spec.example,
            key=key,
        )
    set_nested(config[section], spec.key, value)


#: Input paths are collected in step 2, so the limits step must not render
#: them again — two widgets with the same key is a Streamlit error.
_INPUT_FIELDS: frozenset[str] = frozenset(
    {"tinyml.model", "memory.binary", "sensor_fusion.source", "hil.source"}
)


def _section_fields(section: SectionSpec, config: dict[str, Any], advanced: bool) -> None:
    for spec in section.fields:
        if spec.advanced and not advanced:
            continue
        if f"{section.name}.{spec.key}" in _INPUT_FIELDS:
            continue
        _widget(section.name, spec, config)


def _step_target(config: dict[str, Any], advanced: bool) -> str:
    st.markdown("#### 1 · Target")
    st.caption(
        "Which device to validate against. Every backend listed here is a registered "
        "`target` plugin — including any contributed by an installed package."
    )
    kinds = plugin_choices("target")
    current = str(get_nested(config, "target.kind") or "sim")
    if current not in kinds:
        current = kinds[0] if kinds else "sim"
    kind = st.selectbox(
        "Target backend",
        kinds,
        index=kinds.index(current) if current in kinds else 0,
        help="'sim' runs everything in software with no hardware attached.",
        key="field::target.kind",
    )
    set_nested(config.setdefault("target", {}), "kind", kind)
    if kind == "sim":
        st.caption(
            "The simulated device streams telemetry and reports a verdict in software. "
            "Results from it are labelled **simulated** everywhere they appear."
        )
    for spec in fields_for_target(kind, include_advanced=advanced):
        if spec.key == "kind":
            continue
        _widget("target", spec, config)
    return kind


def _field(section: str, key: str) -> FieldSpec:
    spec = SECTIONS_BY_NAME[section].field(key)
    if spec is None:  # pragma: no cover - guarded by the schema itself
        raise KeyError(f"No schema field {section}.{key}")
    return spec


def _step_inputs(config: dict[str, Any], advanced: bool) -> None:
    st.markdown("#### 2 · Firmware, model, and datasets")
    st.caption("Paths are resolved when the run starts; missing files are flagged below.")
    columns = st.columns(2)
    with columns[0]:
        _widget("tinyml", _field("tinyml", "model"), config)
        _widget("memory", _field("memory", "binary"), config)
    with columns[1]:
        _widget("sensor_fusion", _field("sensor_fusion", "source"), config)
        _widget("hil", _field("hil", "source"), config)
    del advanced


def _step_suites(config: dict[str, Any]) -> str:
    st.markdown("#### 3 · Validation suites")
    extra = list((config.get("extra_suites") or {}).keys())
    options = ["all", *BUILTIN_SUITES, *extra]
    current = st.session_state.get("mission_suite", "all")
    suite = st.radio(
        "Suite selection",
        options,
        index=options.index(current) if current in options else 0,
        horizontal=True,
        key="mission_suite",
        help="'all' runs every built-in suite plus any plugin suites in extra_suites.",
    )
    descriptions = {
        name: SECTIONS_BY_NAME[SUITE_CONFIG_SECTION[name]].description
        for name in BUILTIN_SUITES
        if SUITE_CONFIG_SECTION.get(name) in SECTIONS_BY_NAME
    }
    if suite == "all":
        for name, description in descriptions.items():
            st.caption(f"**{name}** — {description}")
    elif suite in descriptions:
        st.caption(descriptions[suite])
    return str(suite)


def _step_limits(config: dict[str, Any], suite: str, advanced: bool) -> None:
    st.markdown("#### 4 · Limits and fault scenarios")
    st.caption("These thresholds are what turn a measurement into a pass or a fail.")
    relevant = [
        section
        for section in SCHEMA
        if section.suite and (suite == "all" or section.suite == suite)
    ]
    for section in relevant:
        with st.expander(f"{section.title} — {section.description}", expanded=False):
            _section_fields(section, config, advanced)
            if section.name == "hil":
                _fault_editor(config)
            if section.name == "rt_perf":
                _task_editor(config)


def _fault_editor(config: dict[str, Any]) -> None:
    """Add fault models from the registry to the HIL chain."""
    hil = config.setdefault("hil", {})
    faults = hil.setdefault("faults", [])
    st.markdown("**Fault chain**")
    if faults:
        for index, fault in enumerate(list(faults)):
            columns = st.columns([4, 1])
            columns[0].code(str(fault), language="yaml")
            if columns[1].button("Remove", key=f"fault_rm_{index}"):
                faults.pop(index)
                st.rerun()
    else:
        st.caption("No faults injected — the HIL suite will measure the clean stream only.")
    available = plugin_choices("fault")
    if not available:
        return
    columns = st.columns([2, 1])
    kind = columns[0].selectbox("Fault model", available, key="fault_kind")
    if columns[1].button("Add fault", key="fault_add"):
        defaults: dict[str, dict[str, Any]] = {
            "noise": {"std": 0.05},
            "packet_loss": {"probability": 0.02, "seed": 1},
            "jitter": {"std_s": 0.002},
            "outage": {"start_s": 1.0, "duration_s": 0.5},
        }
        faults.append({"kind": kind, **defaults.get(kind, {})})
        st.rerun()


def _task_editor(config: dict[str, Any]) -> None:
    """Define the periodic task set profiled by the rt suite."""
    rt = config.setdefault("rt_perf", {})
    tasks = rt.setdefault("task_set", [])
    st.markdown("**Task set**")
    for index, task in enumerate(list(tasks)):
        columns = st.columns([3, 1])
        columns[0].code(str(task), language="yaml")
        if columns[1].button("Remove", key=f"task_rm_{index}"):
            tasks.pop(index)
            st.rerun()
    columns = st.columns([2, 1, 1, 1, 1])
    name = columns[0].text_input("Task name", value="control_loop", key="task_name")
    period = columns[1].number_input("Period ms", value=5.0, min_value=0.001, key="task_period")
    deadline = columns[2].number_input(
        "Deadline ms", value=5.0, min_value=0.001, key="task_deadline"
    )
    budget = columns[3].number_input("WCET ms", value=4.0, min_value=0.001, key="task_wcet")
    if columns[4].button("Add task", key="task_add") and name:
        tasks.append(
            {
                "name": name,
                "period_ms": float(period),
                "deadline_ms": float(deadline),
                "wcet_budget_ms": float(budget),
            }
        )
        st.rerun()


def _step_baseline(workspace: Workspace) -> tuple[str, str, float]:
    st.markdown("#### 5 · Baseline and regression policy")
    baselines = [b.name for b in workspace.baselines.list()]
    columns = st.columns(3)
    baseline = columns[0].selectbox(
        "Gate against baseline",
        ["(none)", *baselines],
        help="A run is failed when a metric moves in its bad direction beyond the allowance.",
        key="mission_baseline",
    )
    allowance = columns[1].slider(
        "Max regression",
        min_value=1.0,
        max_value=100.0,
        value=float(st.session_state.get("mission_max_regression", 10.0)),
        step=1.0,
        format="%g%%",
        key="mission_max_regression_slider",
    )
    promote = columns[2].text_input(
        "Promote to baseline",
        value="",
        placeholder="release-0.4",
        help="Only a fully passing run is promoted; a failing run is refused.",
        key="mission_promote",
    )
    if not baselines:
        st.caption(
            "No baselines saved yet. Run a mission, then promote it from the Baselines page."
        )
    return ("" if baseline == "(none)" else str(baseline)), str(promote), float(allowance)


def _step_review(
    workspace: Workspace, config: dict[str, Any], suite: str, telemetry_s: float
) -> bool:
    st.markdown("#### 6 · Review")
    result = validate_for_suite(config, suite)
    if result.errors:
        st.error(f"{len(result.errors)} configuration error(s) must be fixed before launching.")
    elif result.warnings:
        st.warning(f"{len(result.warnings)} warning(s) — the run will proceed.")
    else:
        st.success("Configuration is valid.")
    if result.issues:
        with st.expander("Configuration findings", expanded=bool(result.errors)):
            ui.issue_list(result.issues)

    import yaml

    with st.expander("Resolved configuration (YAML)", expanded=False):
        st.code(yaml.safe_dump(config, sort_keys=False), language="yaml")
    del workspace, telemetry_s
    return result.ok


def render(workspace: Workspace) -> None:
    st.subheader("New validation run")
    st.caption(
        "Configure a mission step by step. Nothing runs until you launch, and the exact "
        "equivalent command line is shown first."
    )

    preset_ids = [p.id for p in PRESETS]
    columns = st.columns([2, 1])
    with columns[0]:
        chosen = st.selectbox(
            "Start from a preset",
            preset_ids,
            index=preset_ids.index(st.session_state.get(_PRESET_KEY, "sim-release-gate")),
            format_func=lambda pid: get_preset(pid).title,
            key="preset_select",
        )
    with columns[1]:
        st.markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)
        if st.button("Load preset", key="preset_load"):
            _apply_preset(chosen)
            st.rerun()

    preset = get_preset(st.session_state.get(_PRESET_KEY, chosen))
    st.caption(preset.summary)
    if preset.answers:
        st.caption("Answers: " + " · ".join(preset.answers))
    if preset.requires_hardware:
        st.warning("This preset expects physical hardware attached.", icon=None)

    advanced = st.toggle("Show advanced settings", value=False, key="mission_advanced")
    config = _config()

    st.divider()
    _step_target(config, advanced)
    st.divider()
    _step_inputs(config, advanced)
    st.divider()
    suite = _step_suites(config)
    st.divider()
    _step_limits(config, suite, advanced)
    st.divider()
    telemetry_s = st.number_input(
        "Telemetry capture (seconds, 0 to skip)",
        min_value=0.0,
        value=float(st.session_state.get("mission_telemetry_s", 0.0)),
        step=0.5,
        key="mission_telemetry_input",
        help="Captures device output into telemetry.csv after the suites run.",
    )
    baseline, promote, allowance = _step_baseline(workspace)
    st.divider()
    valid = _step_review(workspace, config, suite, telemetry_s)

    st.markdown("#### 7 · Launch")
    mission_name = st.text_input(
        "Mission name",
        value=st.session_state.get("mission_name", preset.title),
        key="mission_name",
    )
    saved_path = st.session_state.get("mission_saved_path", "")
    st.caption("Equivalent command line:")
    st.code(
        preview_command(
            config_path=saved_path or "missions/<name>.yaml",
            suite=suite,
            report_dir=str(workspace.report_dir),
            baseline=baseline,
            save_baseline=promote,
            telemetry_s=telemetry_s,
            max_regression_pct=allowance,
        ),
        language="bash",
    )

    columns = st.columns([1, 1, 2])
    with columns[0]:
        launch = st.button("Launch validation", type="primary", disabled=not valid, key="launch")
    with columns[1]:
        save = st.button("Save mission", key="save_mission")

    if save:
        store = MissionStore(workspace.mission_dir)
        try:
            path = store.save(
                mission_name,
                config,
                suite=suite,
                baseline=baseline,
                telemetry_s=telemetry_s,
                max_regression_pct=allowance,
                preset=preset.id,
                title=mission_name,
            )
        except (OSError, ValueError) as exc:
            st.error(f"Could not save the mission: {exc}")
        else:
            st.session_state["mission_saved_path"] = str(path)
            st.success(f"Saved to {path} — run it anywhere with `eaiv pipeline --config {path}`.")

    if launch:
        launcher = get_launcher(workspace.report_dir, workspace.baseline_dir)
        run_id = launcher.start(
            LaunchSpec(
                config=config,
                suite=suite,
                baseline=baseline,
                save_baseline=promote,
                telemetry_s=float(telemetry_s),
                max_regression_pct=float(allowance),
                run_name=mission_name,
                config_path=st.session_state.get("mission_saved_path", ""),
            )
        )
        goto("Live run", live_run_id=run_id)


def reset_defaults() -> None:
    """Reset the builder to schema defaults (used by the sidebar)."""
    st.session_state[_STATE_KEY] = default_config("sim")


__all__ = ["render", "reset_defaults"]
