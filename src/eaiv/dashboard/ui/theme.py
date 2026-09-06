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
  --eaiv-accent: #1677a6;
  --eaiv-accent-soft: rgba(22, 119, 166, 0.10);
  --eaiv-pass: #16854b;
  --eaiv-fail: #c23b32;
  --eaiv-warn: #9a6500;
  --eaiv-muted: #657383;
  --eaiv-ink: #172632;
  --eaiv-line: rgba(92, 112, 128, 0.24);
  --eaiv-surface: rgba(248, 250, 252, 0.84);
  --eaiv-raised: rgba(255, 255, 255, 0.94);
  --eaiv-shadow: 0 1px 2px rgba(18, 38, 52, 0.04), 0 10px 28px rgba(18, 38, 52, 0.055);
}
@media (prefers-color-scheme: dark) {
  :root {
    --eaiv-accent: #55b9e8;
    --eaiv-accent-soft: rgba(85, 185, 232, 0.10);
    --eaiv-pass: #5fce8b;
    --eaiv-fail: #ff8a80;
    --eaiv-warn: #e3b341;
    --eaiv-muted: #96a3b3;
    --eaiv-ink: #edf5fa;
    --eaiv-line: rgba(150, 171, 188, 0.22);
    --eaiv-surface: rgba(23, 36, 47, 0.72);
    --eaiv-raised: rgba(27, 42, 54, 0.92);
    --eaiv-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  }
}
/* App shell ------------------------------------------------------------ */
[data-testid="stAppViewContainer"] {
  background-image:
    linear-gradient(rgba(80, 112, 132, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(80, 112, 132, 0.035) 1px, transparent 1px);
  background-size: 32px 32px;
}
[data-testid="stMainBlockContainer"] { max-width: 1500px; padding-top: 2rem; }
[data-testid="stSidebar"] {
  border-right: 1px solid var(--eaiv-line);
  background: var(--eaiv-raised);
}
.eaiv-brand { display: flex; align-items: center; gap: .7rem; margin: .15rem 0 .6rem; }
.eaiv-brand strong { display: block; color: var(--eaiv-ink); font-size: 1.15rem; letter-spacing: .16em; line-height: 1; }
.eaiv-brand small { color: var(--eaiv-muted); font-size: .61rem; letter-spacing: .18em; }
.eaiv-brand-mark {
  position: relative; width: 2.15rem; height: 2.15rem; border: 1px solid var(--eaiv-accent);
  border-radius: 50%; box-shadow: inset 0 0 0 5px var(--eaiv-accent-soft);
}
.eaiv-brand-mark::before, .eaiv-brand-mark::after { content: ""; position: absolute; background: var(--eaiv-accent); }
.eaiv-brand-mark::before { width: 1px; height: 2.65rem; left: 1.04rem; top: -.25rem; opacity: .45; }
.eaiv-brand-mark::after { height: 1px; width: 2.65rem; top: 1.04rem; left: -.25rem; opacity: .45; }
.eaiv-brand-mark span { position: absolute; width: .38rem; height: .38rem; border-radius: 50%; background: var(--eaiv-accent); inset: .83rem; }
.eaiv-system-state { color: var(--eaiv-muted); font-size: .62rem; letter-spacing: .1em; margin-bottom: 1.2rem; }
.eaiv-system-state span, .eaiv-topline-status i { display: inline-block; width: .42rem; height: .42rem; border-radius: 50%; background: var(--eaiv-pass); margin-right: .32rem; box-shadow: 0 0 0 3px color-mix(in srgb, var(--eaiv-pass) 15%, transparent); }
[data-testid="stSidebar"] [role="radiogroup"] { gap: .18rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  border-radius: 5px; padding: .46rem .55rem; transition: background-color 120ms ease, color 120ms ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: var(--eaiv-accent-soft); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background: var(--eaiv-accent-soft); color: var(--eaiv-accent); font-weight: 650; }
.eaiv-trust-note { border: 1px solid var(--eaiv-line); border-radius: 6px; padding: .7rem .75rem; color: var(--eaiv-muted); }
.eaiv-trust-note strong { color: var(--eaiv-ink); font-size: .63rem; letter-spacing: .1em; }
.eaiv-trust-note p { font-size: .72rem; line-height: 1.45; margin: .28rem 0 0; }
.eaiv-topline { display: flex; justify-content: space-between; padding-bottom: .55rem; border-bottom: 1px solid var(--eaiv-line); color: var(--eaiv-muted); font-size: .64rem; font-weight: 600; letter-spacing: .11em; margin-bottom: 1.25rem; }
.eaiv-topline-status i { width: .36rem; height: .36rem; margin-right: .25rem; }
.eaiv-mono, .eaiv-metric-value, .eaiv-chip {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum";
}
.eaiv-banner {
  border: 1px solid var(--eaiv-line);
  border-left: 4px solid var(--eaiv-accent);
  border-radius: 7px;
  padding: 1.05rem 1.25rem;
  background: linear-gradient(115deg, var(--eaiv-surface), var(--eaiv-raised));
  margin-bottom: 1rem;
  box-shadow: var(--eaiv-shadow);
}
.eaiv-banner.pass { border-left-color: var(--eaiv-pass); }
.eaiv-banner.fail { border-left-color: var(--eaiv-fail); }
.eaiv-banner.warn { border-left-color: var(--eaiv-warn); }
.eaiv-banner h2 {
  font-size: 1.28rem;
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
  border-radius: 7px;
  padding: 1rem 1.05rem;
  margin-bottom: 0.7rem;
  background: var(--eaiv-raised);
  box-shadow: var(--eaiv-shadow);
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
  border-radius: 7px;
  padding: 0.78rem 0.9rem;
  height: 100%;
  background: var(--eaiv-raised);
  box-shadow: var(--eaiv-shadow);
  transition: border-color 140ms ease, transform 140ms ease;
}
.eaiv-tile:hover { border-color: color-mix(in srgb, var(--eaiv-accent) 45%, var(--eaiv-line)); transform: translateY(-1px); }
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
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: .25rem; border-bottom: 1px solid var(--eaiv-line); }
[data-testid="stTabs"] button[role="tab"] { font-size: .82rem; letter-spacing: .015em; }
[data-testid="stDataFrame"] { border: 1px solid var(--eaiv-line); border-radius: 7px; overflow: hidden; }
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
  [data-testid="stMainBlockContainer"] { padding-top: 1.2rem; }
  .eaiv-topline-status { display: none; }
  .eaiv-stage { grid-template-columns: 1.2rem 1fr; }
  .eaiv-stage .dur, .eaiv-stage .detail { grid-column: 2; }
}
@media (prefers-reduced-motion: reduce) {
  .eaiv-tile, [data-testid="stSidebar"] [role="radiogroup"] label { transition: none; }
  .eaiv-tile:hover { transform: none; }
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
