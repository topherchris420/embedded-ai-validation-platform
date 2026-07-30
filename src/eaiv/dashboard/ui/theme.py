"""Visual language for Mission Control.

The aesthetic target is a flight-test console, not a marketing dashboard:
tabular numerals, quiet surfaces, one accent, and status that is legible
without colour. Every status chip carries a glyph and a word as well as a
hue, so the display works in greyscale, in high-contrast mode, and for
readers who cannot distinguish red from green.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from eaiv.insights.models import Severity
from eaiv.insights.verdict import Verdict
from eaiv.runs.models import RunStatus, StageStatus

# Glyphs are geometric, not emoji: they render in any terminal-ish font
# and never carry a tone the data does not have.
STATUS_GLYPHS: dict[str, str] = {
    "passed": "●",
    "ok": "●",
    "failed": "▲",
    "error": "▲",
    "cancelled": "■",
    "interrupted": "■",
    "running": "◐",
    "pending": "○",
    "skipped": "–",
    "warning": "▲",
}

CSS = """
<style>
:root {
  --eaiv-accent: #2f6f9f;
  --eaiv-pass: #1a7f45;
  --eaiv-fail: #b3261e;
  --eaiv-warn: #8a5a00;
  --eaiv-muted: #5f6b7a;
  --eaiv-line: rgba(128, 140, 155, 0.32);
  --eaiv-surface: rgba(128, 140, 155, 0.07);
}
@media (prefers-color-scheme: dark) {
  :root {
    --eaiv-accent: #6fb3e0;
    --eaiv-pass: #5fce8b;
    --eaiv-fail: #ff8a80;
    --eaiv-warn: #e3b341;
    --eaiv-muted: #96a3b3;
  }
}
.eaiv-mono, .eaiv-metric-value, .eaiv-chip {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum";
}
.eaiv-banner {
  border: 1px solid var(--eaiv-line);
  border-left: 4px solid var(--eaiv-accent);
  border-radius: 6px;
  padding: 0.9rem 1.1rem;
  background: var(--eaiv-surface);
  margin-bottom: 0.9rem;
}
.eaiv-banner.pass { border-left-color: var(--eaiv-pass); }
.eaiv-banner.fail { border-left-color: var(--eaiv-fail); }
.eaiv-banner.warn { border-left-color: var(--eaiv-warn); }
.eaiv-banner h2 {
  font-size: 1.15rem;
  margin: 0 0 0.25rem 0;
  letter-spacing: 0.01em;
}
.eaiv-banner p { margin: 0.15rem 0; color: var(--eaiv-muted); font-size: 0.9rem; }
.eaiv-chip {
  display: inline-block;
  border: 1px solid var(--eaiv-line);
  border-radius: 999px;
  padding: 0.08rem 0.6rem;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.eaiv-chip.pass { color: var(--eaiv-pass); border-color: var(--eaiv-pass); }
.eaiv-chip.fail { color: var(--eaiv-fail); border-color: var(--eaiv-fail); }
.eaiv-chip.warn { color: var(--eaiv-warn); border-color: var(--eaiv-warn); }
.eaiv-chip.muted { color: var(--eaiv-muted); }
.eaiv-card {
  border: 1px solid var(--eaiv-line);
  border-radius: 6px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.7rem;
  background: var(--eaiv-surface);
}
.eaiv-card h4 { margin: 0 0 0.35rem 0; font-size: 1rem; }
.eaiv-card .eaiv-impact { color: var(--eaiv-muted); font-size: 0.88rem; margin: 0.2rem 0 0.5rem 0; }
.eaiv-evidence {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.1rem 0.9rem;
  font-size: 0.85rem;
  margin: 0.35rem 0;
}
.eaiv-evidence dt { color: var(--eaiv-muted); }
.eaiv-evidence dd { margin: 0; font-variant-numeric: tabular-nums; }
.eaiv-action {
  border-top: 1px dashed var(--eaiv-line);
  padding-top: 0.45rem;
  margin-top: 0.5rem;
  font-size: 0.88rem;
}
.eaiv-action code { font-size: 0.82rem; }
.eaiv-label {
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-size: 0.68rem;
  color: var(--eaiv-muted);
  margin-bottom: 0.15rem;
}
.eaiv-metric-value { font-size: 1.35rem; font-weight: 600; line-height: 1.2; }
.eaiv-metric-sub { font-size: 0.78rem; color: var(--eaiv-muted); }
.eaiv-tile {
  border: 1px solid var(--eaiv-line);
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
  height: 100%;
}
.eaiv-stage {
  display: grid;
  grid-template-columns: 1.2rem 8rem 5rem 1fr;
  gap: 0.5rem;
  align-items: baseline;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--eaiv-line);
  font-size: 0.88rem;
}
.eaiv-stage .name { font-weight: 600; }
.eaiv-stage .dur { color: var(--eaiv-muted); font-variant-numeric: tabular-nums; }
.eaiv-log {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  line-height: 1.45;
  max-height: 22rem;
  overflow: auto;
  border: 1px solid var(--eaiv-line);
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
  white-space: pre-wrap;
}
div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
/* Streamlit's default primary is red, which reads as "danger" on a console
   whose whole job is to distinguish safe from unsafe. Recolour the primary
   action to the instrument accent and leave red for real failures. */
button[kind="primary"], button[data-testid="stBaseButton-primary"] {
  background-color: var(--eaiv-accent) !important;
  border-color: var(--eaiv-accent) !important;
  color: #fff !important;
}
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {
  filter: brightness(1.08);
}
button[kind="primary"]:focus-visible,
button[data-testid="stBaseButton-primary"]:focus-visible {
  outline: 2px solid var(--eaiv-accent);
  outline-offset: 2px;
}
@media (max-width: 720px) {
  .eaiv-stage { grid-template-columns: 1.2rem 1fr; }
  .eaiv-stage .dur, .eaiv-stage .detail { grid-column: 2; }
}
</style>
"""


def inject() -> None:
    """Install the stylesheet once per page render."""
    st.markdown(CSS, unsafe_allow_html=True)


@dataclass(frozen=True)
class Tone:
    """A status rendered three ways: word, glyph, and CSS class."""

    label: str
    glyph: str
    css: str


def status_tone(status: str) -> Tone:
    """Tone for a run or stage status string."""
    normalized = str(status).lower()
    glyph = STATUS_GLYPHS.get(normalized, "○")
    if normalized in ("passed", "ok"):
        return Tone("PASS", glyph, "pass")
    if normalized in ("failed", "error"):
        return Tone("FAIL", glyph, "fail")
    if normalized in ("cancelled", "interrupted"):
        return Tone(normalized.upper(), glyph, "warn")
    if normalized == "running":
        return Tone("RUNNING", glyph, "muted")
    if normalized == "skipped":
        return Tone("SKIPPED", glyph, "muted")
    return Tone(normalized.upper() or "UNKNOWN", glyph, "muted")


def run_status_tone(status: RunStatus) -> Tone:
    return status_tone(str(status))


def stage_status_tone(status: StageStatus | str) -> Tone:
    return status_tone(str(status))


def verdict_tone(verdict: Verdict) -> Tone:
    return {
        Verdict.SHIP: Tone("READY TO SHIP", "●", "pass"),
        Verdict.SHIP_WITH_RISK: Tone("SHIP WITH RISK", "▲", "warn"),
        Verdict.DO_NOT_SHIP: Tone("NOT READY", "▲", "fail"),
        Verdict.UNKNOWN: Tone("NO DATA", "○", "muted"),
    }[verdict]


def severity_tone(severity: Severity) -> Tone:
    return {
        Severity.CRITICAL: Tone("CRITICAL", "▲", "fail"),
        Severity.HIGH: Tone("HIGH", "▲", "fail"),
        Severity.MEDIUM: Tone("MEDIUM", "■", "warn"),
        Severity.INFO: Tone("INFO", "●", "muted"),
    }[severity]


def provenance_tone(provenance: str) -> Tone:
    return {
        "measured": Tone("MEASURED", "●", "pass"),
        "simulated": Tone("SIMULATED", "◐", "warn"),
        "mixed": Tone("MIXED ORIGIN", "◐", "warn"),
        "unknown": Tone("ORIGIN UNRECORDED", "○", "muted"),
    }.get(provenance, Tone(provenance.upper(), "○", "muted"))


def chip(tone: Tone) -> str:
    """Inline HTML for a status chip (glyph + word + colour)."""
    return f'<span class="eaiv-chip {tone.css}">{tone.glyph} {tone.label}</span>'


__all__ = [
    "CSS",
    "STATUS_GLYPHS",
    "Tone",
    "chip",
    "inject",
    "provenance_tone",
    "run_status_tone",
    "severity_tone",
    "stage_status_tone",
    "status_tone",
    "verdict_tone",
]
