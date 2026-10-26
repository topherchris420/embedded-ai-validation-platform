"""Declared firmware authorship in the Mission Control data layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eaiv.dashboard.authorship import (
    authorship_by_run,
    authorship_comparison_caption,
    authorship_summary,
    input_rows,
)
from eaiv.dashboard.runs import all_sources, legacy_sources
from eaiv.runs.models import RunManifest, RunStatus
from eaiv.runs.store import RunStore


def _report(
    authorship: dict[str, Any] | None,
    *,
    provenance: str = "simulated",
    source: str = "simulator",
) -> dict[str, Any]:
    firmware: dict[str, Any] = {"path": "fw.elf", "exists": True, "sha256": "ab" * 32}
    if authorship is not None:
        firmware["authorship"] = authorship
    return {
        "schema_version": 2,
        "timestamp": "2026-10-26T00:00:00+00:00",
        "meta": {
            "target": {"kind": "sim", "name": "sim"},
            "inputs": {"firmware": firmware, "dataset": {"path": "imu.csv", "exists": True}},
        },
        "suites": [
            {
                "name": "firmware",
                "passed": True,
                "metrics": {"attempts": 1},
                "metric_meta": {"attempts": {"provenance": provenance, "source": source}},
            }
        ],
        "all_passed": True,
    }


def test_summary_shows_the_declared_origin_and_tool():
    summary = authorship_summary(_report({"origin": "ai_assisted", "tool": "Cursor"}))
    assert summary.declared
    assert summary.label == "ai_assisted (Cursor)"
    assert "declared ai_assisted (Cursor)" in summary.note
    assert "not a detected property" in summary.note


def test_summary_without_a_tool_shows_the_origin_only():
    assert authorship_summary(_report({"origin": "human", "tool": ""})).label == "human"


def test_ai_summary_names_missing_device_evidence():
    note = authorship_summary(_report({"origin": "ai_generated", "tool": ""})).note
    assert "simulated/simulator, not measured on the device" in note


def test_ai_summary_on_device_states_the_evidence_plainly():
    report = _report({"origin": "ai_generated", "tool": ""}, provenance="measured", source="device")
    note = authorship_summary(report).note
    assert note.endswith("Firmware suite evidence: measured/device.")


def test_legacy_or_missing_reports_read_as_unknown():
    for report in (_report(None), {}, None):
        summary = authorship_summary(report)
        assert not summary.declared
        assert summary.label == "unknown"
        assert "no claim is made" in summary.note


def test_comparison_caption_shows_both_sides():
    caption = authorship_comparison_caption(
        _report(None), _report({"origin": "ai_generated", "tool": "Copilot"})
    )
    assert caption == (
        "Declared firmware authorship: baseline unknown · current ai_generated (Copilot)"
    )


def test_input_rows_put_authorship_on_the_firmware_row_only():
    rows = {r["Input"]: r for r in input_rows(_report({"origin": "human", "tool": ""}))}
    assert rows["firmware"]["Authorship"] == "human"
    assert rows["firmware"]["SHA-256"] == "ab" * 8
    assert rows["dataset"]["Authorship"] == ""


def test_input_rows_tolerate_malformed_inputs():
    report = _report(None)
    report["meta"]["inputs"]["model"] = "not-an-object"
    assert [r["Input"] for r in input_rows(report)] == ["firmware", "dataset"]
    assert input_rows({"meta": {"inputs": []}}) == []


def _record_run(store: RunStore, run_id: str, created: str, report: dict[str, Any]) -> None:
    manifest = RunManifest(run_id=run_id, name=run_id, status=RunStatus.PASSED, created_at=created)
    store.create(manifest)
    (store.run_dir(run_id) / "report.json").write_text(json.dumps({**report, "timestamp": created}))


def test_run_inventory_labels_each_recorded_run(tmp_path):
    store = RunStore(tmp_path)
    _record_run(
        store,
        "20260101T000000-a",
        "2026-01-01T00:00:00+00:00",
        _report({"origin": "ai_generated", "tool": "Copilot"}),
    )
    _record_run(store, "20260102T000000-b", "2026-01-02T00:00:00+00:00", _report(None))
    (tmp_path / "report_legacy.json").write_text(json.dumps(_report({"origin": "human"})))
    sources = all_sources(store, tmp_path)
    assert authorship_by_run(sources) == {
        "20260101T000000-a": "ai_generated (Copilot)",
        "20260102T000000-b": "unknown",
    }
    # Legacy files have no run id, so they are not part of the run inventory.
    assert len(legacy_sources(tmp_path)) == 1


# -- rendering -------------------------------------------------------------


def test_views_render_declared_authorship(tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    report_dir = tmp_path / "reports"
    store = RunStore(report_dir)
    _record_run(store, "20260101T000000-a", "2026-01-01T00:00:00+00:00", _report(None))
    _record_run(
        store,
        "20260102T000000-b",
        "2026-01-02T00:00:00+00:00",
        _report({"origin": "ai_generated", "tool": "Copilot"}),
    )
    app_path = str(Path("src/eaiv/dashboard/ui/app.py").resolve())

    def page(name: str) -> Any:
        app = AppTest.from_file(app_path, default_timeout=20)
        app.session_state["page"] = name
        app.session_state["report_dir"] = str(report_dir)
        app.session_state["baseline_dir"] = str(tmp_path / "baselines")
        app.session_state["mission_dir"] = str(tmp_path / "missions")
        app.run()
        assert not app.exception
        return app

    results = page("Results")
    assert any("declared ai_generated (Copilot)" in c.value for c in results.caption)
    assert any("ai_generated (Copilot)" in str(f.value) for f in results.dataframe)

    compare = page("Compare")
    assert any(
        "baseline unknown · current ai_generated (Copilot)" in c.value for c in compare.caption
    )

    mission_control = page("Mission Control")
    inventory = next(
        f.value for f in mission_control.dataframe if "Firmware authorship" in f.value.columns
    )
    assert list(inventory["Firmware authorship"]) == ["ai_generated (Copilot)", "unknown"]
