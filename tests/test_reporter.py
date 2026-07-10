"""Tests for the multi-format reporter artifacts."""

from __future__ import annotations

import csv
import json

from eaiv.core.reporter import Reporter
from eaiv.core.results import AggregateResult, SuiteResult


def _results() -> AggregateResult:
    agg = AggregateResult()
    agg.add(SuiteResult(name="tinyml", passed=True, metrics={"mean_ms": 1.5, "fps": 660.0}))
    agg.add(SuiteResult(name="memory", passed=False, metrics={"rom_kb": 900}, notes="over budget"))
    return agg


def test_reporter_writes_all_formats(tmp_path):
    Reporter(str(tmp_path)).publish(_results())
    for name in ("latest.json", "report.csv", "report.md", "report.html"):
        assert (tmp_path / name).exists(), name


def test_json_artifact_round_trips(tmp_path):
    Reporter(str(tmp_path)).publish(_results())
    payload = json.loads((tmp_path / "latest.json").read_text())
    assert payload["all_passed"] is False
    assert {s["name"] for s in payload["suites"]} == {"tinyml", "memory"}


def test_csv_is_long_format(tmp_path):
    Reporter(str(tmp_path)).publish(_results())
    with (tmp_path / "report.csv").open() as f:
        rows = list(csv.DictReader(f))
    by_key = {(r["suite"], r["metric"]): r["value"] for r in rows}
    assert by_key[("tinyml", "mean_ms")] == "1.5"
    assert by_key[("memory", "rom_kb")] == "900"
    assert by_key[("memory", "_passed")] == "False"


def test_markdown_summary_contains_status_and_metrics(tmp_path):
    Reporter(str(tmp_path)).publish(_results())
    md = (tmp_path / "report.md").read_text()
    assert "Overall: **FAIL**" in md
    assert "| tinyml | ✅ PASS |" in md
    assert "| memory | ❌ FAIL | over budget |" in md
    assert "| mean_ms | 1.5 |" in md
