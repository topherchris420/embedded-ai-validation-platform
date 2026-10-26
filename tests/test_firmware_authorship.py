"""Declared firmware authorship: recorded, compared, and never a gate by itself."""

from __future__ import annotations

import json
from typing import Any

from eaiv.config import Config
from eaiv.configspec.schema import FIRMWARE_ORIGINS, default_config
from eaiv.core.comparison import CompatibilityLevel, check_compatibility
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.report_schema import firmware_authorship
from eaiv.insights import generate_insights
from eaiv.insights.models import Severity


def _report(
    origin: str | None,
    *,
    provenance: str = "simulated",
    source: str = "simulator",
    kind: str = "sim",
    tool: str = "",
    with_firmware_suite: bool = True,
) -> dict[str, Any]:
    firmware: dict[str, Any] = {"name": "fw.elf", "sha256": "ab" * 32}
    if origin is not None:
        firmware["authorship"] = {"origin": origin, "tool": tool}
    suites: list[dict[str, Any]] = []
    if with_firmware_suite:
        suites.append(
            {
                "name": "firmware",
                "passed": True,
                "metrics": {"boot_ms": 120.0, "attempts": 1},
                "notes": "",
                "metric_meta": {
                    "boot_ms": {"provenance": provenance, "source": source},
                    "attempts": {"provenance": provenance, "source": source},
                },
            }
        )
    else:
        suites.append(
            {
                "name": "fusion",
                "passed": True,
                "metrics": {"rmse_deg": 1.0},
                "notes": "",
                "metric_meta": {"rmse_deg": {"provenance": "simulated", "source": "dataset"}},
            }
        )
    return {
        "schema_version": 2,
        "timestamp": "2026-10-26T00:00:00+00:00",
        "meta": {
            "eaiv_version": "0.4.0",
            "target": {"kind": kind, "name": kind},
            "inputs": {"firmware": firmware},
        },
        "suites": suites,
        "all_passed": True,
    }


def _ids(report: dict[str, Any]) -> list[str]:
    return [i.id for i in generate_insights(report)]


# -- schema & recording ----------------------------------------------------


def test_default_origin_is_unknown_and_makes_no_claim():
    target = default_config("sim")["target"]
    assert target["binary_origin"] == "unknown"
    assert target["binary_origin_tool"] == ""
    assert FIRMWARE_ORIGINS[0] == "unknown"


def test_orchestrator_records_declared_authorship(tmp_path):
    cfg = Config(
        {
            "target": {
                "kind": "sim",
                "binary": "fw.elf",
                "binary_origin": "ai_assisted",
                "binary_origin_tool": "Cursor",
                "sim": {"telemetry_lines": 3},
            },
            "firmware": {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
        }
    )
    Orchestrator(cfg, report_dir=str(tmp_path)).run("firmware")
    payload = json.loads((tmp_path / "latest.json").read_text())
    assert payload["meta"]["inputs"]["firmware"]["authorship"] == {
        "origin": "ai_assisted",
        "tool": "Cursor",
    }


def test_legacy_or_malformed_reports_read_as_unknown():
    assert firmware_authorship({})["origin"] == "unknown"
    assert firmware_authorship(_report(None))["origin"] == "unknown"
    broken = _report(None)
    broken["meta"]["inputs"]["firmware"]["authorship"] = "ai"
    assert firmware_authorship(broken)["origin"] == "unknown"


# -- comparison ------------------------------------------------------------


def test_authorship_change_is_a_non_blocking_caveat():
    compatibility = check_compatibility(_report("human"), _report("ai_generated"))
    issue = next(i for i in compatibility.issues if i.field == "Firmware authorship")
    assert not issue.blocking
    assert (issue.baseline, issue.current) == ("human", "ai_generated")
    assert compatibility.level is CompatibilityLevel.CAVEATED


def test_unknown_on_either_side_adds_no_caveat():
    for base, curr in (("unknown", "ai_assisted"), (None, "human"), ("human", "human")):
        compatibility = check_compatibility(_report(base), _report(curr))
        assert all(i.field != "Firmware authorship" for i in compatibility.issues)


# -- insights --------------------------------------------------------------


def test_ai_firmware_validated_only_in_simulation_gets_a_finding():
    insights = generate_insights(_report("ai_generated", tool="Copilot"))
    finding = next(i for i in insights if i.id == "ai-firmware-not-on-device")
    assert finding.severity is Severity.MEDIUM
    assert not finding.severity.blocks_release
    labels = {e.label: e.value for e in finding.evidence}
    assert labels["Declared authorship"] == "ai_generated"
    assert labels["Tool"] == "Copilot"
    assert labels["Firmware suite provenance"] == "simulated"


def test_ai_firmware_without_a_firmware_suite_is_flagged():
    insights = generate_insights(_report("ai_assisted", with_firmware_suite=False))
    finding = next(i for i in insights if i.id == "ai-firmware-not-on-device")
    labels = {e.label: e.value for e in finding.evidence}
    assert labels["Firmware suite provenance"] == "firmware suite did not run"


def test_ai_firmware_measured_on_device_gets_no_finding():
    report = _report("ai_generated", provenance="measured", source="device", kind="serial")
    assert "ai-firmware-not-on-device" not in _ids(report)


def test_human_or_unknown_firmware_gets_no_finding():
    for origin in ("human", "unknown", None):
        assert "ai-firmware-not-on-device" not in _ids(_report(origin))
