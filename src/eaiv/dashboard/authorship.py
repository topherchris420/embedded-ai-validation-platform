"""Declared firmware authorship, shaped for Mission Control.

Authorship is the engineer's declaration (``target.binary_origin``),
recorded with the firmware identity. These helpers turn it into table
cells and captions; they never infer it and never judge a run by it.
Reports without a declaration read as ``unknown``.

No Streamlit import lives in this module: it is typed, unit-tested, and
reusable by any front end.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from eaiv.core.report_schema import (
    AI_FIRMWARE_ORIGINS,
    describe_firmware_authorship,
    firmware_authorship,
    firmware_device_evidence,
)
from eaiv.dashboard.runs import ReportSource


@dataclass(frozen=True)
class AuthorshipSummary:
    """One report's declared firmware authorship, ready to render."""

    origin: str
    tool: str
    #: ``ai_assisted (Cursor)``, ``human``, or ``unknown``.
    label: str
    #: One plain sentence for a caption.
    note: str

    @property
    def declared(self) -> bool:
        return self.origin != "unknown"


def authorship_summary(report: dict[str, Any] | None) -> AuthorshipSummary:
    """Declared authorship of a report's firmware, with a caption."""
    authorship = firmware_authorship(report or {})
    label = describe_firmware_authorship(authorship)
    if authorship["origin"] == "unknown":
        note = "Firmware authorship: unknown. No declaration was recorded; no claim is made."
    else:
        note = (
            f"Firmware authorship: declared {label}. "
            "This is the engineer's declaration, not a detected property."
        )
    if authorship["origin"] in AI_FIRMWARE_ORIGINS and report is not None:
        on_device, evidence = firmware_device_evidence(report)
        note += f" Firmware suite evidence: {evidence}" + (
            "." if on_device else ", not measured on the device."
        )
    return AuthorshipSummary(authorship["origin"], authorship["tool"], label, note)


def authorship_comparison_caption(
    baseline: dict[str, Any] | None, current: dict[str, Any] | None
) -> str:
    """Both sides' declared authorship on one line, for the Compare view."""
    return (
        "Declared firmware authorship: baseline "
        f"{authorship_summary(baseline).label} · current {authorship_summary(current).label}"
    )


def input_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows of the Inputs table; the firmware row carries its declared authorship."""
    inputs = (report.get("meta") or {}).get("inputs") or {}
    if not isinstance(inputs, dict):
        return []
    authorship = authorship_summary(report).label
    return [
        {
            "Input": key,
            "Path": value.get("path", ""),
            "Present": "yes" if value.get("exists") else "no",
            "SHA-256": (value.get("sha256") or "")[:16],
            "Size": value.get("size_bytes", ""),
            "Authorship": authorship if key == "firmware" else "",
        }
        for key, value in inputs.items()
        if isinstance(value, dict)
    ]


def authorship_by_run(sources: Iterable[ReportSource]) -> dict[str, str]:
    """Declared authorship label per recorded run id, from already-listed sources."""
    return {
        source.manifest.run_id: authorship_summary(source.report()).label
        for source in sources
        if source.manifest is not None
    }


__all__ = [
    "AuthorshipSummary",
    "authorship_by_run",
    "authorship_comparison_caption",
    "authorship_summary",
    "input_rows",
]
