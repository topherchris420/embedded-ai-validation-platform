"""Suite selections: ``all``, one suite, or a comma-separated list.

``eaiv run --suite firmware,rt`` runs exactly those suites, in the
orchestrator's usual order. ``all`` stands alone; combining it with
named suites is an error rather than a guess at what was meant.
"""

from __future__ import annotations


def split_suite_selection(selection: str) -> list[str]:
    """``"firmware, rt"`` → ``["firmware", "rt"]``, duplicates dropped."""
    parts: list[str] = []
    for part in str(selection).split(","):
        name = part.strip()
        if name and name not in parts:
            parts.append(name)
    if not parts:
        raise ValueError("Empty suite selection.")
    if "all" in parts and len(parts) > 1:
        raise ValueError(f"'all' cannot be combined with other suites: {selection!r}")
    return parts


def selection_includes(selection: str, suite: str) -> bool:
    """Whether a selection runs ``suite`` (``all`` runs every suite)."""
    parts = split_suite_selection(selection)
    return parts == ["all"] or suite in parts


__all__ = ["selection_includes", "split_suite_selection"]
