"""Comma-separated suite selections: ``eaiv run --suite firmware,rt``."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from eaiv.cli import _load_all_plugins, main
from eaiv.config import Config
from eaiv.configspec import validate_for_suite
from eaiv.core.orchestrator import Orchestrator
from eaiv.core.selection import selection_includes, split_suite_selection


def test_split_trims_and_drops_duplicates():
    assert split_suite_selection("firmware") == ["firmware"]
    assert split_suite_selection(" rt, firmware ,rt") == ["rt", "firmware"]
    assert split_suite_selection("all") == ["all"]


@pytest.mark.parametrize("selection", ["", " , ", "all,firmware", "firmware,all"])
def test_empty_or_ambiguous_selections_are_refused(selection):
    with pytest.raises(ValueError):
        split_suite_selection(selection)


def test_selection_includes():
    assert selection_includes("all", "hil")
    assert selection_includes("firmware,rt", "rt")
    assert not selection_includes("firmware,rt", "hil")


def _config(**extra: Any) -> Config:
    return Config(
        {
            "target": {"kind": "sim", "sim": {"telemetry_lines": 3}},
            "firmware": {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]},
            "rt_perf": {
                "task_set": [
                    {"name": "loop", "period_ms": 5, "deadline_ms": 5, "wcet_budget_ms": 4}
                ],
                "duration_s": 0.2,
            },
            **extra,
        }
    )


def test_selected_suites_follow_the_orchestrator_order():
    orchestrator = Orchestrator(_config())
    assert orchestrator.selected_suites("rt,firmware") == ["firmware", "rt"]
    assert orchestrator.selected_suites("hil") == ["hil"]


def test_run_executes_exactly_the_listed_suites(tmp_path):
    Orchestrator(_config(), report_dir=str(tmp_path), quiet=True).run("rt,firmware")
    payload = json.loads((tmp_path / "latest.json").read_text())
    assert [s["name"] for s in payload["suites"]] == ["firmware", "rt_perf"]


@pytest.mark.parametrize("selection", ["firmware,nope", "all,rt"])
def test_run_refuses_unknown_or_ambiguous_selections(tmp_path, selection):
    with pytest.raises(ValueError):
        Orchestrator(_config(), report_dir=str(tmp_path)).run(selection)


def test_validation_covers_every_listed_suite_and_only_those():
    _load_all_plugins()
    raw = {
        "target": {"kind": "sim"},
        "firmware": {"timeout_s": "slow"},
        "rt_perf": {"duration_s": "long"},
        "sensor_fusion": {"algorithm": "nope"},
    }
    paths = {i.path for i in validate_for_suite(raw, "firmware,rt", check_paths=False).errors}
    assert "firmware.timeout_s" in paths
    assert "rt_perf.duration_s" in paths
    assert not any(p.startswith("sensor_fusion") for p in paths)


def test_cli_reports_a_bad_selection_as_a_usage_error(tmp_path):
    path = tmp_path / "eaiv.yaml"
    path.write_text("target:\n  kind: sim\n")
    runner = CliRunner()
    for args in (
        ["run", "--config", str(path), "--suite", "firmware,nope"],
        ["config", "validate", str(path), "--suite", "all,rt"],
    ):
        result = runner.invoke(main, args)
        assert result.exit_code == 2, result.output
        assert "--suite" in result.output
