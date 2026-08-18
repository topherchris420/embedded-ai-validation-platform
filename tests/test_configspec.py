"""Config schema, field-level validation, presets, and the command preview."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from eaiv.config import ConfigError, load_config
from eaiv.configspec import (
    PRESETS,
    PRESETS_BY_ID,
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
    validate_config,
    validate_for_suite,
)
from eaiv.configspec.schema import SECTIONS_BY_NAME, TARGET_SECTION


@pytest.fixture(autouse=True)
def _plugins():
    """Registry-derived choices need the built-in plugins registered."""
    from eaiv.cli import _load_all_plugins

    _load_all_plugins()


def _issues(raw: dict, **kwargs) -> dict[str, str]:
    return {i.path: i.message for i in validate_config(raw, **kwargs).issues}


def test_default_config_is_valid_out_of_the_box():
    result = validate_config(default_config("sim"), check_paths=False)
    assert result.ok, [str(i) for i in result.errors]


def test_choices_come_from_the_plugin_registry():
    kinds = plugin_choices("target")
    assert {"sim", "qemu", "serial", "jlink"} <= set(kinds)
    spec = TARGET_SECTION.field("kind")
    assert field_choices(spec) == kinds
    assert "ekf" in field_choices(SECTIONS_BY_NAME["sensor_fusion"].field("algorithm"))


def test_a_newly_registered_plugin_appears_in_the_choices():
    from eaiv.plugins import PluginMetadata, get_registry

    registry = get_registry()
    registry.register(
        PluginMetadata(name="my_board", version="0.1", description="", plugin_type="target"),
        lambda spec: None,
    )
    try:
        assert "my_board" in field_choices(TARGET_SECTION.field("kind"))
    finally:
        registry.unregister("target", "my_board")


def test_unknown_sections_and_keys_warn_but_do_not_fail():
    result = validate_config(
        {"target": {"kind": "sim", "nonsense": 1}, "not_a_section": {}}, check_paths=False
    )
    assert result.ok
    paths = {i.path for i in result.warnings}
    assert "target.nonsense" in paths
    assert "not_a_section" in paths


def test_unknown_target_kind_is_an_error_listing_alternatives():
    result = validate_config({"target": {"kind": "nope"}}, check_paths=False)
    assert not result.ok
    issue = next(i for i in result.errors if i.path == "target.kind")
    assert "not available" in issue.message
    assert "sim" in issue.hint


def test_type_errors_name_the_expected_type():
    messages = _issues(
        {"target": {"kind": "sim"}, "firmware": {"retries": "two"}}, check_paths=False
    )
    assert "expected integer" in messages["firmware.retries"]


def test_booleans_are_not_accepted_as_numbers():
    messages = _issues(
        {"target": {"kind": "sim"}, "firmware": {"timeout_s": True}}, check_paths=False
    )
    assert "firmware.timeout_s" in messages


def test_range_violations_are_reported():
    messages = _issues({"target": {"kind": "sim"}, "firmware": {"retries": 99}}, check_paths=False)
    assert "above the maximum" in messages["firmware.retries"]


def test_missing_paths_warn_and_say_what_it_costs(tmp_path):
    result = validate_config(
        {"target": {"kind": "sim"}, "tinyml": {"model": str(tmp_path / "absent.tflite")}}
    )
    assert result.ok  # a missing optional model does not block a run
    warning = next(i for i in result.warnings if i.path == "tinyml.model")
    assert "file not found" in warning.message
    assert "skipped" in warning.hint


def test_missing_required_path_is_an_error(tmp_path):
    result = validate_config(
        {"target": {"kind": "sim"}, "sensor_fusion": {"source": str(tmp_path / "no.csv")}}
    )
    assert not result.ok
    assert any(i.path == "sensor_fusion.source" for i in result.errors)


def test_unknown_fault_model_is_rejected_with_the_registered_list():
    result = validate_config(
        {"target": {"kind": "sim"}, "hil": {"faults": [{"kind": "gremlins"}]}},
        check_paths=False,
    )
    issue = next(i for i in result.errors if i.path == "hil.faults[0].kind")
    assert "unknown fault model" in issue.message
    assert "noise" in issue.hint


def test_task_set_consistency_is_checked():
    result = validate_config(
        {
            "target": {"kind": "sim"},
            "rt_perf": {
                "task_set": [
                    {"name": "loop", "period_ms": 5, "deadline_ms": 8, "wcet_budget_ms": 9}
                ]
            },
        },
        check_paths=False,
    )
    paths = {i.path: i for i in result.issues}
    # A deadline beyond the period is a warning; a budget beyond the
    # deadline is impossible, so it is an error.
    assert not paths["rt_perf.task_set[0].deadline_ms"].is_error
    assert paths["rt_perf.task_set[0].wcet_budget_ms"].is_error


def test_empty_task_set_warns_that_the_suite_will_fail():
    result = validate_config(
        {"target": {"kind": "sim"}, "rt_perf": {"task_set": []}}, check_paths=False
    )
    assert result.ok
    assert any("will fail" in i.message for i in result.warnings)


def test_unregistered_extra_suite_is_reported():
    result = validate_config(
        {"target": {"kind": "sim"}, "extra_suites": {"ghost": {}}}, check_paths=False
    )
    assert any(i.path == "extra_suites.ghost" for i in result.errors)


def test_template_blocks_for_other_backends_are_not_flagged():
    """Shipped configs carry serial/jlink/qemu blocks at their defaults; a
    sim run must not be buried in warnings about them."""
    raw = default_config("sim")
    set_nested(raw, "target.serial.port", "/dev/ttyACM0")  # the schema default
    set_nested(raw, "target.jlink.device", "STM32H743VI")
    result = validate_config(raw, check_paths=False)
    assert not [i for i in result.warnings if "only applies to target kinds" in i.message]


def test_changed_value_for_another_backend_is_flagged():
    raw = default_config("sim")
    set_nested(raw, "target.serial.port", "/dev/ttyUSB9")  # deliberately changed
    result = validate_config(raw, check_paths=False)
    assert any("only applies to target kinds" in i.message for i in result.warnings)


def test_suite_scoped_validation_ignores_other_suites(tmp_path):
    raw = {
        "target": {"kind": "sim"},
        "tinyml": {"model": str(tmp_path / "absent.tflite")},
        "sensor_fusion": {"source": "datasets/imu/imu_run1.csv"},
    }
    fusion_only = validate_for_suite(raw, "fusion")
    assert not [i for i in fusion_only.issues if i.path.startswith("tinyml")]
    everything = validate_for_suite(raw, "all")
    assert [i for i in everything.issues if i.path.startswith("tinyml")]


def test_target_fields_are_filtered_by_backend():
    sim_keys = {f.key for f in fields_for_target("sim")}
    serial_keys = {f.key for f in fields_for_target("serial")}
    assert "sim.telemetry_lines" in sim_keys
    assert "sim.telemetry_lines" not in serial_keys
    assert "serial.port" in serial_keys
    assert "kind" in sim_keys and "kind" in serial_keys


def test_nested_get_and_set():
    raw: dict = {}
    set_nested(raw, "a.b.c", 3)
    assert raw == {"a": {"b": {"c": 3}}}
    assert get_nested(raw, "a.b.c") == 3
    assert get_nested(raw, "a.x.c") is None
    # A non-mapping in the path is replaced rather than crashing.
    set_nested(raw, "a.b", 1)
    set_nested(raw, "a.b.d", 2)
    assert raw["a"]["b"] == {"d": 2}


def test_every_field_declares_a_description_and_label():
    for section in SECTIONS_BY_NAME.values():
        for spec in section.fields:
            assert spec.label, f"{section.name}.{spec.key} has no label"
            assert spec.description, f"{section.name}.{spec.key} has no description"
            if spec.type is FieldType.ENUM:
                assert spec.choices or spec.choices_plugin


# -- presets ---------------------------------------------------------------


def test_every_preset_builds_a_valid_configuration():
    for preset in PRESETS:
        raw = preset.build()
        result = validate_config(raw, check_paths=False)
        assert result.ok, f"{preset.id}: {[str(i) for i in result.errors]}"


def test_presets_cover_the_documented_missions():
    assert {
        "sim-smoke",
        "sim-release-gate",
        "firmware-only",
        "tinyml-benchmark",
        "fusion-accuracy",
        "hil-robustness",
        "rt-deadlines",
        "custom",
    } <= set(PRESETS_BY_ID)


def test_only_the_hardware_preset_requires_hardware():
    assert get_preset("firmware-only").requires_hardware
    assert not get_preset("sim-release-gate").requires_hardware


def test_unknown_preset_lists_the_available_ones():
    with pytest.raises(KeyError, match="sim-smoke"):
        get_preset("does-not-exist")


def test_preset_target_kind_can_be_overridden():
    raw = get_preset("sim-release-gate").build("serial")
    assert get_nested(raw, "target.kind") == "serial"


# -- missions --------------------------------------------------------------


def test_saved_mission_is_a_runnable_config(tmp_path):
    store = MissionStore(tmp_path)
    path = store.save(
        "Nightly gate",
        get_preset("sim-release-gate").build(),
        suite="all",
        baseline="release-1",
        preset="sim-release-gate",
    )
    # It loads through the normal config loader, so `eaiv run --config` works.
    cfg = load_config(path)
    assert cfg["target"]["kind"] == "sim"
    assert cfg["mission"]["baseline"] == "release-1"
    # And the mission block does not trip validation.
    assert validate_config(cfg.raw, check_paths=False).ok


def test_mission_listing_and_baseline_usage(tmp_path):
    store = MissionStore(tmp_path)
    store.save("a", default_config(), baseline="rel-1")
    store.save("b", default_config(), baseline="rel-2")
    store.save("c", default_config(), baseline="rel-1")
    assert {m.name for m in store.list()} == {"a", "b", "c"}
    assert {m.name for m in store.using_baseline("rel-1")} == {"a", "c"}


def test_mission_names_are_sanitized_into_filenames(tmp_path):
    store = MissionStore(tmp_path)
    path = store.save("../../escape attempt", default_config())
    assert path.parent == tmp_path
    assert path.name == "escape-attempt.yaml"
    with pytest.raises(ValueError):
        store.path("///")


def test_mission_round_trips_through_yaml(tmp_path):
    store = MissionStore(tmp_path)
    raw = get_preset("hil-robustness").build()
    store.save("hil", raw, suite="hil")
    reloaded = yaml.safe_load(store.path("hil").read_text())
    assert reloaded["hil"]["faults"] == raw["hil"]["faults"]


# -- config loader ---------------------------------------------------------


def test_inheritance_records_its_sources(tmp_path):
    (tmp_path / "base.yaml").write_text("target: {kind: qemu}\nfirmware: {retries: 5}\n")
    (tmp_path / "child.yaml").write_text("inherit: base.yaml\ntarget: {kind: sim}\n")
    cfg = load_config(tmp_path / "child.yaml")
    assert cfg["target"]["kind"] == "sim"
    assert cfg["firmware"]["retries"] == 5  # merged key-by-key, not replaced
    assert [Path(p).name for p in cfg.sources] == ["base.yaml", "child.yaml"]


def test_inheritance_cycles_are_reported_not_hung(tmp_path):
    (tmp_path / "a.yaml").write_text("inherit: b.yaml\n")
    (tmp_path / "b.yaml").write_text("inherit: a.yaml\n")
    with pytest.raises(ConfigError, match="cycle"):
        load_config(tmp_path / "a.yaml")


def test_malformed_yaml_names_the_file(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("target: {kind: sim\n  broken")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(bad)


def test_missing_parent_is_reported(tmp_path):
    (tmp_path / "child.yaml").write_text("inherit: nowhere.yaml\n")
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "child.yaml")


def test_non_mapping_config_is_rejected(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(path)


def test_config_serializes_back_to_valid_yaml():
    from eaiv.config import Config

    cfg = Config(get_preset("sim-release-gate").build())
    assert yaml.safe_load(cfg.to_yaml()) == cfg.raw


# -- command preview -------------------------------------------------------


def test_command_preview_matches_the_configured_mission():
    command = preview_command(
        "missions/nightly.yaml",
        suite="hil",
        baseline="release-1",
        save_baseline="release-2",
        telemetry_s=2.0,
        max_regression_pct=5.0,
    )
    assert command.startswith("eaiv pipeline --config missions/nightly.yaml")
    assert "--suite hil" in command
    assert "--baseline release-1" in command
    assert "--save-baseline release-2" in command
    assert "--telemetry-duration 2" in command
    assert "--max-regression-pct 5" in command


def test_command_preview_omits_defaults():
    command = preview_command("cfg.yaml")
    assert command == "eaiv pipeline --config cfg.yaml"


def test_command_preview_quotes_awkward_paths():
    assert "'my configs/a b.yaml'" in preview_command("my configs/a b.yaml")
