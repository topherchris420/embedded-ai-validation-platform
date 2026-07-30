"""Field-level configuration validation.

Every problem is reported with the dotted path that caused it, a
severity, and — where one exists — the fix. Errors mean "this run cannot
work"; warnings mean "this will run, but probably not the way you
intended" (a missing model file, an unrecognised key, a deadline longer
than its period).

Nothing here executes a run or touches hardware, so the mission builder
can validate on every keystroke and CI can validate without a board.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from eaiv.configspec.schema import (
    SCHEMA,
    SECTIONS_BY_NAME,
    FieldSpec,
    FieldType,
    field_choices,
    get_nested,
    plugin_choices,
)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ConfigIssue:
    """One validation finding, addressed by dotted config path."""

    path: str
    message: str
    severity: Severity = Severity.ERROR
    hint: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity is Severity.ERROR

    def __str__(self) -> str:
        suffix = f" — {self.hint}" if self.hint else ""
        return f"[{self.severity}] {self.path}: {self.message}{suffix}"


@dataclass
class ValidationResult:
    issues: list[ConfigIssue]

    @property
    def errors(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.is_error]

    @property
    def warnings(self) -> list[ConfigIssue]:
        return [i for i in self.issues if not i.is_error]

    @property
    def ok(self) -> bool:
        return not self.errors

    def for_path(self, prefix: str) -> list[ConfigIssue]:
        return [i for i in self.issues if i.path == prefix or i.path.startswith(prefix + ".")]


_TYPE_CHECKS: dict[FieldType, tuple[type, ...]] = {
    FieldType.STRING: (str,),
    FieldType.PATH: (str,),
    FieldType.ENUM: (str,),
    FieldType.INTEGER: (int,),
    FieldType.FLOAT: (int, float),
    FieldType.BOOLEAN: (bool,),
    FieldType.LIST: (list,),
    FieldType.MAPPING: (dict,),
}


def _type_ok(spec: FieldSpec, value: Any) -> bool:
    expected = _TYPE_CHECKS.get(spec.type, (object,))
    if spec.type in (FieldType.INTEGER, FieldType.FLOAT) and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _check_field(
    issues: list[ConfigIssue],
    section: str,
    spec: FieldSpec,
    body: dict[str, Any],
    check_paths: bool,
) -> None:
    path = f"{section}.{spec.key}"
    value = get_nested(body, spec.key)

    if value is None:
        if spec.required:
            issues.append(
                ConfigIssue(
                    path,
                    "required field is missing",
                    hint=f"Add {path} — {spec.description}" if spec.description else "",
                )
            )
        return

    if not _type_ok(spec, value):
        issues.append(
            ConfigIssue(
                path,
                f"expected {spec.type}, got {type(value).__name__} ({value!r})",
            )
        )
        return

    if spec.type is FieldType.ENUM:
        choices = field_choices(spec)
        if choices and value not in choices:
            issues.append(
                ConfigIssue(
                    path,
                    f"{value!r} is not available",
                    hint=f"Available: {', '.join(choices)}",
                )
            )

    if spec.type in (FieldType.INTEGER, FieldType.FLOAT):
        number = float(value)
        if spec.minimum is not None and number < spec.minimum:
            issues.append(ConfigIssue(path, f"{value} is below the minimum {spec.minimum:g}"))
        if spec.maximum is not None and number > spec.maximum:
            issues.append(ConfigIssue(path, f"{value} is above the maximum {spec.maximum:g}"))

    if spec.type is FieldType.PATH and check_paths and value:
        file = Path(str(value))
        if not file.exists():
            issues.append(
                ConfigIssue(
                    path,
                    f"file not found: {value}",
                    severity=Severity.ERROR if spec.required else Severity.WARNING,
                    hint=(
                        "Suites depending on this input will fail or be skipped."
                        if not spec.required
                        else "Provide an existing file."
                    ),
                )
            )


def _known_keys(section_name: str) -> set[str]:
    """Top-level keys a section legitimately contains."""
    spec = SECTIONS_BY_NAME.get(section_name)
    if spec is None:
        return set()
    return {f.key.split(".", 1)[0] for f in spec.fields}


def _check_unknown_keys(issues: list[ConfigIssue], section_name: str, body: dict[str, Any]) -> None:
    spec = SECTIONS_BY_NAME.get(section_name)
    if spec is None or spec.free_form:
        return
    known = _known_keys(section_name)
    for key in body:
        if key not in known:
            issues.append(
                ConfigIssue(
                    f"{section_name}.{key}",
                    "unrecognised key — it will be ignored",
                    severity=Severity.WARNING,
                    hint=f"Known keys: {', '.join(sorted(known))}",
                )
            )


def _check_faults(issues: list[ConfigIssue], faults: Any) -> None:
    if not isinstance(faults, list):
        issues.append(ConfigIssue("hil.faults", "expected a list of fault specs"))
        return
    available = plugin_choices("fault")
    for index, item in enumerate(faults):
        path = f"hil.faults[{index}]"
        if not isinstance(item, dict):
            issues.append(ConfigIssue(path, "each fault must be a mapping with a 'kind'"))
            continue
        kind = item.get("kind")
        if not kind:
            issues.append(ConfigIssue(path, "missing 'kind'", hint=f"Available: {available}"))
        elif available and kind not in available:
            issues.append(
                ConfigIssue(
                    f"{path}.kind",
                    f"unknown fault model {kind!r}",
                    hint=f"Available: {', '.join(available)}",
                )
            )


def _check_task_set(issues: list[ConfigIssue], task_set: Any) -> None:
    if not isinstance(task_set, list):
        issues.append(ConfigIssue("rt_perf.task_set", "expected a list of task definitions"))
        return
    if not task_set:
        issues.append(
            ConfigIssue(
                "rt_perf.task_set",
                "no tasks defined — the rt suite will fail",
                severity=Severity.WARNING,
                hint="Add at least one task, or drop 'rt' from the suite selection.",
            )
        )
        return
    for index, task in enumerate(task_set):
        path = f"rt_perf.task_set[{index}]"
        if not isinstance(task, dict):
            issues.append(ConfigIssue(path, "each task must be a mapping"))
            continue
        for key in ("name", "period_ms", "deadline_ms", "wcet_budget_ms"):
            if key not in task:
                issues.append(ConfigIssue(f"{path}.{key}", "required task field is missing"))
        numbers: dict[str, float] = {}
        for key in ("period_ms", "deadline_ms", "wcet_budget_ms"):
            value = task.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                issues.append(ConfigIssue(f"{path}.{key}", f"expected a number, got {value!r}"))
                continue
            if value <= 0:
                issues.append(ConfigIssue(f"{path}.{key}", f"must be positive, got {value}"))
            numbers[key] = float(value)
        deadline = numbers.get("deadline_ms")
        period = numbers.get("period_ms")
        budget = numbers.get("wcet_budget_ms")
        if deadline is not None and period is not None and deadline > period:
            issues.append(
                ConfigIssue(
                    f"{path}.deadline_ms",
                    f"deadline {deadline:g}ms exceeds the period {period:g}ms",
                    severity=Severity.WARNING,
                    hint="A task that may still be running at its next release will pile up.",
                )
            )
        if budget is not None and deadline is not None and budget > deadline:
            issues.append(
                ConfigIssue(
                    f"{path}.wcet_budget_ms",
                    f"WCET budget {budget:g}ms exceeds the deadline {deadline:g}ms",
                    hint="A task cannot be allowed more execution time than its deadline.",
                )
            )


def _check_extra_suites(issues: list[ConfigIssue], extra: Any) -> None:
    if not isinstance(extra, dict):
        issues.append(ConfigIssue("extra_suites", "expected a mapping of suite name to settings"))
        return
    available = plugin_choices("suite")
    for name, spec in extra.items():
        if name not in available:
            issues.append(
                ConfigIssue(
                    f"extra_suites.{name}",
                    f"no registered suite plugin named {name!r}",
                    hint=(
                        f"Registered suites: {', '.join(available)}"
                        if available
                        else (
                            "No suite plugins are installed. Install the package that provides "
                            "it, or remove the entry."
                        )
                    ),
                )
            )
        if spec is not None and not isinstance(spec, dict):
            issues.append(
                ConfigIssue(f"extra_suites.{name}", "suite settings must be a mapping or empty")
            )


def validate_config(
    raw: dict[str, Any],
    check_paths: bool = True,
    include_advanced: bool = True,
) -> ValidationResult:
    """Validate a resolved configuration mapping.

    ``check_paths`` disables filesystem probing for callers validating a
    config destined for another machine.
    """
    issues: list[ConfigIssue] = []
    if not isinstance(raw, dict):
        return ValidationResult([ConfigIssue("", "configuration must be a mapping")])

    known_sections = set(SECTIONS_BY_NAME)
    for key in raw:
        if key not in known_sections and key != "inherit":
            issues.append(
                ConfigIssue(
                    key,
                    "unrecognised top-level section — it will be ignored",
                    severity=Severity.WARNING,
                    hint=f"Known sections: {', '.join(sorted(known_sections))}",
                )
            )

    target_kind = str(get_nested(raw, "target.kind") or "")

    for section in SCHEMA:
        body = raw.get(section.name)
        if body is None:
            continue
        if not isinstance(body, dict):
            issues.append(ConfigIssue(section.name, "expected a mapping"))
            continue
        if section.free_form:
            continue
        _check_unknown_keys(issues, section.name, body)
        for spec in section.fields:
            if spec.advanced and not include_advanced:
                continue
            if spec.target_kinds and target_kind and target_kind not in spec.target_kinds:
                value = get_nested(body, spec.key)
                # Shipped configs keep template blocks for every backend, so
                # flagging one that merely matches its default is pure noise.
                # A value the engineer actually changed is worth mentioning.
                if value is not None and value != spec.default:
                    issues.append(
                        ConfigIssue(
                            f"{section.name}.{spec.key}",
                            f"only applies to target kinds {', '.join(spec.target_kinds)}"
                            f" (current: {target_kind})",
                            severity=Severity.WARNING,
                            hint="Harmless, but it has no effect on this run.",
                        )
                    )
                continue
            _check_field(issues, section.name, spec, body, check_paths)

    if "target" not in raw:
        issues.append(
            ConfigIssue(
                "target",
                "no target section — nothing to validate against",
                hint="Add target.kind (e.g. 'sim' for a hardware-free run).",
            )
        )

    if isinstance(raw.get("hil"), dict) and "faults" in raw["hil"]:
        _check_faults(issues, raw["hil"]["faults"])
    if isinstance(raw.get("rt_perf"), dict) and "task_set" in raw["rt_perf"]:
        _check_task_set(issues, raw["rt_perf"]["task_set"])
    if "extra_suites" in raw:
        _check_extra_suites(issues, raw["extra_suites"])

    return ValidationResult(issues)


def validate_for_suite(
    raw: dict[str, Any], suite: str, check_paths: bool = True
) -> ValidationResult:
    """Validate only what the selected suite actually needs.

    Running just the fusion suite should not complain about a missing
    firmware ELF, so sections belonging to other suites are dropped.
    """
    result = validate_config(raw, check_paths=check_paths)
    if suite == "all":
        return result
    relevant = {"target", "reporting"}
    for section in SCHEMA:
        if section.suite == suite:
            relevant.add(section.name)
    if suite not in {s.suite for s in SCHEMA if s.suite}:
        relevant.add("extra_suites")
    return ValidationResult([i for i in result.issues if i.path.split(".", 1)[0] in relevant])


__all__ = [
    "ConfigIssue",
    "Severity",
    "ValidationResult",
    "validate_config",
    "validate_for_suite",
]
