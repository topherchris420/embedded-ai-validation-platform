"""Fail-closed checks shared by comparisons, promotion and release decisions.

These checks inspect the original payload, before normalization can turn a
malformed status or dropped suite into apparently passing evidence.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GateIssue:
    code: str
    message: str
    suite: str = ""
    metric: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def suite_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    suites = report.get("suites")
    if not isinstance(suites, list):
        return {}
    return {
        s["name"]: s
        for s in suites
        if isinstance(s, dict) and isinstance(s.get("name"), str) and s["name"]
    }


def _invalid_numbers(value: Any, path: str = "") -> list[str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [] if finite_number(value) else [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _invalid_numbers(v, f"{path}.{k}".lstrip("."))]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _invalid_numbers(v, f"{path}[{i}]")]
    return []


def report_issues(report: dict[str, Any]) -> list[GateIssue]:
    """Reasons a report cannot establish a passing validation result.

    Legacy reports can omit metadata and the aggregate verdict. Suite
    verdicts must still be explicit booleans, and all numbers must be finite.
    A skipped optional suite is allowed here; comparisons detect lost
    coverage, and release decisions separately report incomplete coverage.
    """
    issues: list[GateIssue] = []
    suites = report.get("suites")
    if not isinstance(suites, list) or not suites:
        return [GateIssue("empty-report", "Report must contain a non-empty suites list.")]
    for field in ("meta", "run"):
        if field in report and not isinstance(report[field], dict):
            issues.append(GateIssue("invalid-report", f"Report {field} must be an object."))
    meta = report.get("meta")
    if isinstance(meta, dict):
        for field in ("target", "inputs", "thresholds", "config"):
            if field in meta and not isinstance(meta[field], dict):
                issues.append(GateIssue("invalid-report", f"meta.{field} must be an object."))
        inputs = meta.get("inputs")
        if isinstance(inputs, dict) and any(not isinstance(v, dict) for v in inputs.values()):
            issues.append(GateIssue("invalid-report", "Input identities must be objects."))
    run = report.get("run")
    if isinstance(run, dict) and run.get("status") not in (None, "", "passed"):
        issues.append(GateIssue("incomplete-run", f"Run status is {run['status']!r}, not passed."))
    if "all_passed" in report and report["all_passed"] is not True:
        issues.append(GateIssue("report-failed", "Report does not declare all_passed=true."))
    names: set[str] = set()
    for index, suite in enumerate(suites):
        if (
            not isinstance(suite, dict)
            or not isinstance(suite.get("name"), str)
            or not suite["name"]
        ):
            issues.append(
                GateIssue("invalid-suite", f"Suite {index} needs a non-empty string name.")
            )
            continue
        name = suite["name"]
        if name in names:
            issues.append(
                GateIssue("duplicate-suite", f"Duplicate suite {name!r} hides evidence.", name)
            )
        names.add(name)
        if suite.get("passed") is not True:
            issues.append(
                GateIssue("suite-failed", f"Suite {name!r} does not declare passed=true.", name)
            )
        metrics = suite.get("metrics", {})
        if not isinstance(metrics, dict):
            issues.append(GateIssue("invalid-metrics", f"{name}.metrics must be an object.", name))
            continue
        for metric in _invalid_numbers(metrics):
            issues.append(
                GateIssue(
                    "invalid-number", f"{name}.{metric} is not a finite number.", name, metric
                )
            )
        declarations = suite.get("metric_meta", {})
        if not isinstance(declarations, dict):
            issues.append(
                GateIssue("invalid-metadata", f"{name}.metric_meta must be an object.", name)
            )
            continue
        for metric, entry in declarations.items():
            if not isinstance(entry, dict):
                issues.append(
                    GateIssue(
                        "invalid-metadata",
                        f"{name}.{metric} metadata must be an object.",
                        name,
                        metric,
                    )
                )
            elif "direction" in entry and (
                type(entry["direction"]) is not int or entry["direction"] not in (-1, 0, 1)
            ):
                issues.append(
                    GateIssue(
                        "invalid-direction",
                        f"{name}.{metric} direction must be -1, 0, or 1.",
                        name,
                        metric,
                    )
                )
    return issues
