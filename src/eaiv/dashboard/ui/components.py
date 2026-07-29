"""Reusable Mission Control widgets.

Presentation only: each function takes already-computed domain objects and
renders them. Nothing here loads a file, runs a suite, or decides a
verdict — that all belongs to the core packages, which is what keeps the
pages thin and the logic testable.
"""

from __future__ import annotations

import html
from typing import Any, Sequence

import streamlit as st

from eaiv.core.metrics import MetricInfo, MetricProvenance, format_value
from eaiv.dashboard.ui.theme import (
    chip,
    provenance_tone,
    severity_tone,
    stage_status_tone,
    status_tone,
    verdict_tone,
)
from eaiv.insights.models import ValidationInsight
from eaiv.insights.verdict import ReleaseDecision
from eaiv.runs.models import RunManifest


def esc(value: Any) -> str:
    """Escape anything before it reaches an HTML block."""
    return html.escape(str(value))


def verdict_banner(decision: ReleaseDecision, subtitle: str = "") -> None:
    """The single most important line on the landing page."""
    tone = verdict_tone(decision.verdict)
    reasons = "".join(f"<p>{esc(r)}</p>" for r in decision.reasons)
    st.markdown(
        f"""<div class="eaiv-banner {tone.css}">
  <div class="eaiv-label">Release verdict</div>
  <h2>{tone.glyph} {esc(tone.label)} — {esc(decision.headline)}</h2>
  {f'<p>{esc(subtitle)}</p>' if subtitle else ''}
  {reasons}
</div>""",
        unsafe_allow_html=True,
    )


def tile(label: str, value: str, sub: str = "", tone_css: str = "") -> None:
    """One dense metric tile."""
    st.markdown(
        f"""<div class="eaiv-tile">
  <div class="eaiv-label">{esc(label)}</div>
  <div class="eaiv-metric-value {tone_css}">{esc(value)}</div>
  <div class="eaiv-metric-sub">{esc(sub)}</div>
</div>""",
        unsafe_allow_html=True,
    )


def status_chip(status: str) -> None:
    st.markdown(chip(status_tone(status)), unsafe_allow_html=True)


def provenance_note(provenance: str, inline: bool = False) -> None:
    """Say plainly where a run's numbers came from."""
    tone = provenance_tone(provenance)
    explanation = {
        "simulated": "No value in this run was measured on physical hardware.",
        "mixed": "Some values are hardware measurements and some are not.",
        "unknown": "This report predates provenance tracking.",
        "measured": "Values were measured, not simulated.",
    }.get(provenance, "")
    if inline:
        st.markdown(chip(tone), unsafe_allow_html=True)
        return
    st.markdown(
        f'{chip(tone)} <span class="eaiv-metric-sub">{esc(explanation)}</span>',
        unsafe_allow_html=True,
    )


def insight_card(insight: ValidationInsight, index: int = 0) -> None:
    """Render one diagnosis: what, the evidence, and what to do."""
    tone = severity_tone(insight.severity)
    evidence = "".join(
        f"<dt>{esc(e.label)}</dt><dd>{esc(e.value)}"
        + (f' <span class="eaiv-metric-sub">{esc(e.detail)}</span>' if e.detail else "")
        + "</dd>"
        for e in insight.evidence
    )
    confidence_note = (
        f'<span class="eaiv-chip muted">INFERRED</span> '
        if insight.is_inferred
        else ""
    )
    provenance_chip = (
        chip(provenance_tone(insight.provenance)) if insight.provenance else ""
    )
    action_html = ""
    if insight.action is not None:
        parts = [f"<strong>Next:</strong> {esc(insight.action.summary)}"]
        if insight.action.command:
            parts.append(f"<code>{esc(insight.action.command)}</code>")
        if insight.action.config_path:
            parts.append(f"Configuration: <code>{esc(insight.action.config_path)}</code>")
        action_html = f'<div class="eaiv-action">{"<br>".join(parts)}</div>'

    st.markdown(
        f"""<div class="eaiv-card">
  <div>{chip(tone)} {confidence_note}{provenance_chip}
    <span class="eaiv-metric-sub">{esc(insight.category.label)}
    {f"· {esc(insight.suite)}" if insight.suite else ""}</span></div>
  <h4>{esc(insight.title)}</h4>
  <p class="eaiv-impact">{esc(insight.impact)}</p>
  <dl class="eaiv-evidence">{evidence}</dl>
  {action_html}
</div>""",
        unsafe_allow_html=True,
    )
    del index


def stage_timeline(rows: Sequence[dict[str, Any]]) -> None:
    """Pipeline stages with status, duration, and detail."""
    lines = []
    for row in rows:
        tone = stage_status_tone(row["status"])
        detail = row.get("failure") or row.get("detail") or ""
        lines.append(
            f'<div class="eaiv-stage">'
            f'<span class="{tone.css}">{tone.glyph}</span>'
            f'<span class="name">{esc(row["stage"])}</span>'
            f'<span class="dur">{row["duration_s"]:.3f}s</span>'
            f'<span class="detail">{esc(detail)}</span>'
            f"</div>"
        )
    st.markdown("".join(lines), unsafe_allow_html=True)


def log_block(lines: Sequence[str], empty_message: str = "No log output yet.") -> None:
    if not lines:
        st.caption(empty_message)
        return
    body = "\n".join(esc(line) for line in lines)
    st.markdown(f'<div class="eaiv-log">{body}</div>', unsafe_allow_html=True)


def metric_row(
    name: str, value: Any, info: MetricInfo, baseline: float | None = None
) -> dict[str, Any]:
    """One row for a metric table, formatted consistently."""
    row: dict[str, Any] = {
        "Metric": name,
        "Value": format_value(value, info),
        "Direction": info.direction_label,
        "Origin": (
            "—" if info.provenance is MetricProvenance.UNKNOWN else info.provenance.label
        ),
    }
    if baseline is not None:
        row["Baseline"] = format_value(baseline, info)
    return row


def run_header(manifest: RunManifest) -> None:
    """Identity strip shown above any single-run view."""
    tone = status_tone(str(manifest.status))
    st.markdown(
        f"""<div class="eaiv-banner {tone.css}">
  <div class="eaiv-label">Run</div>
  <h2>{esc(manifest.display_name)}</h2>
  <p>{chip(tone)} {chip(provenance_tone(manifest.provenance))}
     <span class="eaiv-mono">{esc(manifest.run_id)}</span></p>
  <p>Target {esc(manifest.target_label)} · suites {esc(manifest.suite_selection)} ·
     started {esc(manifest.started_at[:19] or "—")} · {manifest.duration_s:.2f}s</p>
</div>""",
        unsafe_allow_html=True,
    )


def empty_state(title: str, body: str, action_label: str = "", action_key: str = "") -> bool:
    """An empty state that offers a way forward, not just an explanation."""
    st.markdown(
        f"""<div class="eaiv-card">
  <h4>{esc(title)}</h4>
  <p class="eaiv-impact">{esc(body)}</p>
</div>""",
        unsafe_allow_html=True,
    )
    if action_label:
        return bool(st.button(action_label, key=action_key, type="primary"))
    return False


def issue_list(issues: Sequence[Any]) -> None:
    """Render configuration issues inline, errors first."""
    for issue in issues:
        text = f"**{issue.path}** — {issue.message}"
        if issue.hint:
            text += f"  \n{issue.hint}"
        if issue.is_error:
            st.error(text, icon=None)
        else:
            st.warning(text, icon=None)


__all__ = [
    "empty_state",
    "esc",
    "insight_card",
    "issue_list",
    "log_block",
    "metric_row",
    "provenance_note",
    "run_header",
    "stage_timeline",
    "status_chip",
    "tile",
    "verdict_banner",
]
