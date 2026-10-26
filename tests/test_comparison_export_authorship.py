"""Snapshot-style checks: the authorship caveat in Markdown and JSON exports."""

from __future__ import annotations

import json
from typing import Any

from eaiv.core.comparison import compare_runs, to_json, to_markdown


def _report(origin: str | None, tool: str = "") -> dict[str, Any]:
    firmware: dict[str, Any] = {"name": "fw.elf", "sha256": "ab" * 32}
    if origin is not None:
        firmware["authorship"] = {"origin": origin, "tool": tool}
    return {
        "schema_version": 2,
        "timestamp": "2026-10-26T00:00:00+00:00",
        "meta": {
            "eaiv_version": "0.4.0",
            "target": {"kind": "sim", "name": "sim"},
            "inputs": {"firmware": firmware},
        },
        "suites": [
            {
                "name": "firmware",
                "passed": True,
                "metrics": {"boot_ms": 120.0},
                "metric_meta": {
                    "boot_ms": {
                        "provenance": "simulated",
                        "source": "simulator",
                        "unit": "ms",
                        "direction": -1,
                    }
                },
            }
        ],
        "all_passed": True,
    }


def _compare(base: dict[str, Any], curr: dict[str, Any]) -> Any:
    return compare_runs(base, curr, baseline_label="base", current_label="cand")


# Two trailing spaces are Markdown hard line breaks, kept explicit here.
EXPECTED_MARKDOWN = "\n".join(
    [
        "# Validation comparison",
        "",
        "Baseline: `base`  ",
        "Current: `cand`  ",
        "Compatibility: **Comparable with caveats**  ",
        "Declared firmware authorship: baseline human · current ai_generated (Copilot \\| Chat)",
        "",
        "**Recommendation:** No gated regressions, but the runs differ in setup — confirm the "
        "caveats above before treating this as a clean comparison.",
        "",
        "## Compatibility notes",
        "",
        "| Field | Baseline | Current | Why it matters |",
        "|-------|----------|---------|----------------|",
        "| Firmware authorship | human | ai_generated (Copilot \\| Chat) | The declared authorship "
        "of the firmware changed. The gate treats both runs alike; review whether the new code's "
        "failure modes are covered by the suites that ran. |",
        "",
        "## Summary",
        "",
        "- Regressed: 0",
        "- Improved: 0",
        "- Unchanged: 1",
        "- Informational: 0",
        "- New metrics: 0",
        "- Missing metrics: 0",
        "",
        "## firmware",
        "",
        "| Metric | Baseline | Current | Change | % | Verdict |",
        "|--------|----------|---------|--------|---|---------|",
        "| boot_ms | 120.0 ms | 120.0 ms | 0 ms | +0.00% | unchanged |",
    ]
)


def test_markdown_snapshot_for_a_changed_declaration():
    comparison = _compare(_report("human"), _report("ai_generated", "Copilot | Chat"))
    assert to_markdown(comparison).rstrip("\n") == EXPECTED_MARKDOWN.rstrip("\n")


def test_markdown_table_rows_keep_four_cells_whatever_the_tool_name():
    comparison = _compare(_report("human"), _report("ai_assisted", "a|b\nc"))
    row = next(
        line for line in to_markdown(comparison).splitlines() if line.startswith("| Firmware")
    )
    assert row.replace("\\|", "").count("|") == 5
    assert "ai_assisted (a\\|b c)" in row


def test_json_snapshot_for_a_changed_declaration():
    payload = json.loads(
        to_json(_compare(_report("human"), _report("ai_generated", "Copilot | Chat")))
    )
    assert payload["passed"] is True
    assert payload["compatibility"] == {
        "level": "caveated",
        "issues": [
            {
                "field": "Firmware authorship",
                "baseline": "human",
                "current": "ai_generated (Copilot | Chat)",
                "explanation": (
                    "The declared authorship of the firmware changed. The gate treats both runs "
                    "alike; review whether the new code's failure modes are covered by the "
                    "suites that ran."
                ),
                "blocking": False,
            }
        ],
    }
    assert payload["firmware_authorship"] == {
        "baseline": {"origin": "human", "tool": ""},
        "current": {"origin": "ai_generated", "tool": "Copilot | Chat"},
    }


def test_one_sided_declaration_renders_in_both_exports():
    comparison = _compare(_report(None), _report("ai_assisted"))
    markdown = to_markdown(comparison)
    assert "Declared firmware authorship: baseline unknown · current ai_assisted" in markdown
    assert (
        "| Firmware authorship | unknown | ai_assisted | Firmware authorship is declared for only "
        "one of the runs, so whether it changed is not known. The gate treats both runs alike. |"
    ) in markdown
    payload = json.loads(to_json(comparison))
    assert payload["firmware_authorship"]["baseline"] == {"origin": "unknown", "tool": ""}
    issue = payload["compatibility"]["issues"][0]
    assert (issue["field"], issue["blocking"]) == ("Firmware authorship", False)


def test_legacy_pair_adds_no_authorship_text_but_json_still_says_unknown():
    comparison = _compare(_report(None), _report(None))
    markdown = to_markdown(comparison)
    assert "authorship" not in markdown.lower()
    assert "Compatibility: **Directly comparable**\n" in markdown
    payload = json.loads(to_json(comparison))
    assert payload["compatibility"]["issues"] == []
    assert payload["firmware_authorship"] == {
        "baseline": {"origin": "unknown", "tool": ""},
        "current": {"origin": "unknown", "tool": ""},
    }


def test_same_declaration_on_both_sides_is_shown_without_a_caveat():
    comparison = _compare(_report("ai_generated"), _report("ai_generated"))
    markdown = to_markdown(comparison)
    assert "Declared firmware authorship: baseline ai_generated · current ai_generated" in markdown
    assert "## Compatibility notes" not in markdown
    assert json.loads(to_json(comparison))["passed"] is True
