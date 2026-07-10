"""Tests for the baseline store and CLI."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from eaiv.cli import main
from eaiv.core.baseline import BaselineStore


def _report(mean_ms: float = 1.0, passed: bool = True) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "meta": {"eaiv_version": "0.3.0", "target": {"kind": "sim", "name": "sim"}},
        "suites": [{"name": "tinyml", "passed": passed, "metrics": {"mean_ms": mean_ms}}],
        "all_passed": passed,
    }


def test_save_load_round_trip(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_report(1.5), "release-1")
    loaded = store.load("release-1")
    assert loaded["suites"][0]["metrics"]["mean_ms"] == 1.5
    assert loaded["_baseline"]["name"] == "release-1"
    assert loaded["_baseline"]["saved_at"]


def test_save_accepts_path(tmp_path):
    report_file = tmp_path / "r.json"
    report_file.write_text(json.dumps(_report(2.0)))
    store = BaselineStore(tmp_path / "baselines")
    path = store.save(report_file, "from-file")
    assert path.exists()


def test_list_newest_first_with_metadata(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_report(1.0), "a")
    store.save(_report(2.0, passed=False), "b")
    infos = store.list()
    assert {i.name for i in infos} == {"a", "b"}
    assert infos[0].target == "sim"
    assert any(not i.all_passed for i in infos)


def test_invalid_names_rejected(tmp_path):
    store = BaselineStore(tmp_path)
    for bad in ("", "../x", "a/b", ".hidden"):
        with pytest.raises(ValueError):
            store.path(bad)


def test_missing_baseline_lists_alternatives(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_report(), "only")
    with pytest.raises(FileNotFoundError, match="only"):
        store.load("nope")


def test_non_report_rejected(tmp_path):
    with pytest.raises(ValueError, match="suites"):
        BaselineStore(tmp_path).save({"not": "a report"}, "x")


def test_baseline_cli_save_list_show_and_gate(tmp_path):
    runner = CliRunner()
    report_file = tmp_path / "latest.json"
    report_file.write_text(json.dumps(_report(10.0)))
    root = str(tmp_path / "baselines")

    result = runner.invoke(
        main, ["baseline", "save", str(report_file), "--name", "rel", "--dir", root]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["baseline", "list", "--dir", root])
    assert result.exit_code == 0 and "rel" in result.output

    result = runner.invoke(main, ["baseline", "show", "rel", "--dir", root])
    assert result.exit_code == 0 and '"mean_ms": 10.0' in result.output

    # The stored baseline file gates a regressed current report via eaiv compare.
    current = tmp_path / "current.json"
    current.write_text(json.dumps(_report(20.0)))
    result = runner.invoke(main, ["compare", f"{root}/rel.json", str(current)])
    assert result.exit_code == 1
    assert "REGRESSED" in result.output
