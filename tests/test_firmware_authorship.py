"""Declared firmware authorship: recorded, compared, and never a gate by itself."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from eaiv.cli import _load_all_plugins, main
from eaiv.config import Config
from eaiv.configspec import validate_config
from eaiv.configspec.schema import FIRMWARE_ORIGINS, default_config
from eaiv.core.comparison import CompatibilityLevel, check_compatibility
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.report_schema import firmware_authorship, firmware_device_evidence
from eaiv.insights import generate_insights
from eaiv.insights.models import Confidence, Severity
from eaiv.insights.verdict import Verdict, decide


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


def test_malformed_report_shapes_read_as_unknown_without_raising():
    for meta in ("not metadata", {"inputs": []}, {"inputs": {"firmware": "fw.elf"}}):
        report = _report("ai_generated")
        report["meta"] = meta
        assert firmware_authorship(report)["origin"] == "unknown"
    report = _report("ai_generated")
    report["suites"] = "not a list"
    assert firmware_device_evidence(report) == (False, "firmware suite did not run")


def test_unrecognised_origin_reads_as_unknown_not_as_a_guess():
    for value in ("AI-generated", "ai", "Human", 3, None):
        report = _report("human")
        report["meta"]["inputs"]["firmware"]["authorship"]["origin"] = value
        assert firmware_authorship(report)["origin"] == "unknown"


def _run_firmware(tmp_path, **target: Any) -> dict[str, Any]:
    cfg = Config(
        {
            "target": {"kind": "sim", "sim": {"telemetry_lines": 3}, **target},
            "firmware": {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
        }
    )
    Orchestrator(cfg, report_dir=str(tmp_path)).run("firmware")
    payload: dict[str, Any] = json.loads((tmp_path / "latest.json").read_text())
    return payload


def test_orchestrator_records_unrecognised_origin_as_unknown(tmp_path, caplog):
    payload = _run_firmware(tmp_path, binary="fw.elf", binary_origin="AI-generated")
    assert payload["meta"]["inputs"]["firmware"]["authorship"]["origin"] == "unknown"
    assert "binary_origin 'AI-generated'" in caplog.text


def test_declaration_is_kept_without_a_binary_path(tmp_path):
    payload = _run_firmware(tmp_path, binary_origin="ai_generated", binary_origin_tool=" Cursor ")
    assert payload["meta"]["inputs"]["firmware"] == {
        "authorship": {"origin": "ai_generated", "tool": "Cursor"}
    }
    assert firmware_authorship(payload)["origin"] == "ai_generated"


def test_no_binary_and_no_declaration_records_no_firmware_input(tmp_path):
    payload = _run_firmware(tmp_path, binary_origin="unknown")
    assert "firmware" not in payload["meta"]["inputs"]


# -- config validation -----------------------------------------------------


@pytest.mark.parametrize("value", ["AI-generated", "Human", "ai", ""])
def test_invalid_origin_is_a_field_level_error(value):
    _load_all_plugins()
    result = validate_config({"target": {"kind": "sim", "binary_origin": value}}, check_paths=False)
    issue = next(i for i in result.errors if i.path == "target.binary_origin")
    assert repr(value) in issue.message
    assert issue.hint == "Available: unknown, human, ai_assisted, ai_generated"
    # Only the bad field is reported; nothing else in the config is blamed.
    assert {i.path for i in result.errors} == {"target.binary_origin"}


def test_non_string_origin_or_tool_is_a_type_error():
    _load_all_plugins()
    result = validate_config(
        {"target": {"kind": "sim", "binary_origin": 1, "binary_origin_tool": ["Cursor"]}},
        check_paths=False,
    )
    errors = {i.path: i.message for i in result.errors}
    assert errors["target.binary_origin"].startswith("expected enum")
    assert errors["target.binary_origin_tool"].startswith("expected string")


@pytest.mark.parametrize("value", FIRMWARE_ORIGINS)
def test_every_declared_origin_validates(value):
    _load_all_plugins()
    config = default_config("sim")
    config["target"].update({"binary_origin": value, "binary_origin_tool": "Cursor"})
    assert validate_config(config, check_paths=False).ok


def test_cli_config_validate_rejects_an_invalid_origin(tmp_path):
    path = tmp_path / "eaiv.yaml"
    path.write_text("target:\n  kind: sim\n  binary_origin: AI-generated\n")
    result = CliRunner().invoke(main, ["config", "validate", str(path), "--no-paths", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert not payload["ok"]
    assert [i["path"] for i in payload["issues"] if i["severity"] == "error"] == [
        "target.binary_origin"
    ]


# -- comparison ------------------------------------------------------------


def test_authorship_change_is_a_non_blocking_caveat():
    compatibility = check_compatibility(_report("human"), _report("ai_generated"))
    issue = next(i for i in compatibility.issues if i.field == "Firmware authorship")
    assert not issue.blocking
    assert (issue.baseline, issue.current) == ("human", "ai_generated")
    assert compatibility.level is CompatibilityLevel.CAVEATED


def test_same_or_both_unknown_authorship_adds_no_caveat():
    for base, curr in (("human", "human"), ("unknown", None), (None, None)):
        compatibility = check_compatibility(_report(base), _report(curr))
        assert all(i.field != "Firmware authorship" for i in compatibility.issues)


def test_one_sided_declaration_is_a_caveat_not_a_match():
    for base, curr in (("ai_generated", None), ("unknown", "ai_assisted"), (None, "human")):
        compatibility = check_compatibility(_report(base), _report(curr))
        issue = next(i for i in compatibility.issues if i.field == "Firmware authorship")
        assert not issue.blocking
        assert "only one of the runs" in issue.explanation


def test_caveat_names_the_declared_tool():
    compatibility = check_compatibility(_report("human"), _report("ai_assisted", tool="Cursor"))
    issue = next(i for i in compatibility.issues if i.field == "Firmware authorship")
    assert (issue.baseline, issue.current) == ("human", "ai_assisted (Cursor)")


# -- insights --------------------------------------------------------------


def test_ai_firmware_validated_only_in_simulation_gets_a_finding():
    insights = generate_insights(_report("ai_generated", tool="Copilot"))
    finding = next(i for i in insights if i.id == "ai-firmware-not-on-device")
    assert finding.severity is Severity.MEDIUM
    assert not finding.severity.blocks_release
    labels = {e.label: e.value for e in finding.evidence}
    assert labels["Declared authorship"] == "ai_generated"
    assert labels["Tool"] == "Copilot"
    assert labels["Firmware suite evidence"] == "simulated/simulator"
    # Half declaration, half recorded provenance: not a measurement.
    assert finding.confidence is Confidence.DERIVED
    assert "physical target" in finding.action.summary
    assert "HIL" not in finding.action.summary


def test_ai_firmware_without_a_firmware_suite_is_flagged():
    insights = generate_insights(_report("ai_assisted", with_firmware_suite=False))
    finding = next(i for i in insights if i.id == "ai-firmware-not-on-device")
    labels = {e.label: e.value for e in finding.evidence}
    assert labels["Firmware suite evidence"] == "firmware suite did not run"


def test_firmware_suite_without_numeric_metrics_is_not_device_evidence():
    report = _report("ai_generated", provenance="measured", source="device", kind="serial")
    report["suites"][0]["metrics"] = {"target": "board"}
    assert firmware_device_evidence(report) == (
        False,
        "firmware suite recorded no numeric metrics",
    )
    assert "ai-firmware-not-on-device" in _ids(report)


def test_measured_on_the_host_is_not_device_evidence():
    finding = next(
        i
        for i in generate_insights(_report("ai_assisted", provenance="measured", source="host"))
        if i.id == "ai-firmware-not-on-device"
    )
    labels = {e.label: e.value for e in finding.evidence}
    assert labels["Firmware suite evidence"] == "measured/host"


def test_ai_firmware_measured_on_device_gets_no_finding():
    report = _report("ai_generated", provenance="measured", source="device", kind="serial")
    assert "ai-firmware-not-on-device" not in _ids(report)


def test_human_or_unknown_firmware_gets_no_finding():
    for origin in ("human", "unknown", None):
        assert "ai-firmware-not-on-device" not in _ids(_report(origin))


# -- release verdict -------------------------------------------------------


def _device_report_without_firmware_suite(origin: str | None) -> dict[str, Any]:
    report = _report(origin, kind="serial", with_firmware_suite=False)
    report["suites"] = [
        {
            "name": "tinyml",
            "passed": True,
            "metrics": {"latency_p99_ms": 4.0},
            "notes": "",
            "metric_meta": {"latency_p99_ms": {"provenance": "measured", "source": "device"}},
        }
    ]
    return report


def test_authorship_never_blocks_a_release_by_itself():
    for origin in ("human", "ai_assisted", "ai_generated"):
        for report in (_report(origin), _device_report_without_firmware_suite(origin)):
            assert decide(report).verdict is not Verdict.DO_NOT_SHIP


def test_ai_declaration_holds_a_device_run_at_further_validation():
    # The firmware itself was never exercised, so the open finding keeps
    # the verdict amber; the same run declared human-written ships.
    assert decide(_device_report_without_firmware_suite("human")).verdict is Verdict.SHIP
    assert decide(_device_report_without_firmware_suite(None)).verdict is Verdict.SHIP
    decision = decide(_device_report_without_firmware_suite("ai_generated"))
    assert decision.verdict is Verdict.SHIP_WITH_RISK
    assert [i.id for i in decision.risks] == ["ai-firmware-not-on-device"]


def test_verdict_names_the_missing_device_evidence():
    decision = decide(_report("ai_generated", tool="Copilot"))
    assert (
        "Firmware declared ai_generated (Copilot) has no on-device evidence: "
        "simulated/simulator." in decision.reasons
    )
    no_suite = decide(_device_report_without_firmware_suite("ai_assisted"))
    assert (
        "Firmware declared ai_assisted has no on-device evidence: firmware suite did not run."
        in no_suite.reasons
    )


def test_verdict_adds_no_authorship_line_when_there_is_nothing_missing():
    on_device = _report("ai_generated", provenance="measured", source="device", kind="serial")
    for report in (on_device, _report("human"), _report(None)):
        assert not any("Firmware declared" in r for r in decide(report).reasons)


def test_authorship_reason_never_changes_the_verdict():
    # Same insights in, same verdict out: only the reasons differ.
    for build in (_report, _device_report_without_firmware_suite):
        human, ai = build("human"), build("ai_generated")
        insights = generate_insights(human)
        assert decide(ai, insights).verdict is decide(human, insights).verdict
    failed = _report("ai_generated")
    failed["suites"][0]["passed"] = False
    failed["all_passed"] = False
    assert decide(failed).verdict is Verdict.DO_NOT_SHIP
    assert any("Firmware declared" in r for r in decide(failed).reasons)
