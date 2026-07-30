"""Typed, inspectable view of the eaiv configuration.

The YAML files stay exactly as they were; this package adds a schema that
describes them — field types, defaults, descriptions, legal values pulled
live from the plugin registry — plus validation that reports problems by
dotted path, mission presets, and a CLI command preview.

    from eaiv.configspec import validate_config, PRESETS, preview_command

    result = validate_config(cfg.raw)
    if not result.ok:
        for issue in result.errors:
            print(issue)
"""

from __future__ import annotations

from eaiv.configspec.command import preview_command, run_command_preview
from eaiv.configspec.presets import (
    DEFAULT_PRESET_ID,
    PRESETS,
    PRESETS_BY_ID,
    MissionInfo,
    MissionPreset,
    MissionStore,
    get_preset,
    hardware_free_presets,
)
from eaiv.configspec.schema import (
    SCHEMA,
    SECTIONS_BY_NAME,
    FieldSpec,
    FieldType,
    SectionSpec,
    default_config,
    field_choices,
    fields_for_target,
    get_nested,
    plugin_choices,
    section_for_suite,
    set_nested,
)
from eaiv.configspec.validate import (
    ConfigIssue,
    Severity,
    ValidationResult,
    validate_config,
    validate_for_suite,
)

__all__ = [
    "DEFAULT_PRESET_ID",
    "PRESETS",
    "PRESETS_BY_ID",
    "SCHEMA",
    "SECTIONS_BY_NAME",
    "ConfigIssue",
    "FieldSpec",
    "FieldType",
    "MissionInfo",
    "MissionPreset",
    "MissionStore",
    "SectionSpec",
    "Severity",
    "ValidationResult",
    "default_config",
    "field_choices",
    "fields_for_target",
    "get_nested",
    "get_preset",
    "hardware_free_presets",
    "plugin_choices",
    "preview_command",
    "run_command_preview",
    "section_for_suite",
    "set_nested",
    "validate_config",
    "validate_for_suite",
]
