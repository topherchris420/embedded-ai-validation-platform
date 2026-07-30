"""Streamlit presentation layer for EAIV Mission Control.

Everything that imports Streamlit lives under this package; the data layer
in ``eaiv.dashboard`` stays import-light so the core package never depends
on a UI toolkit.

Launch it with ``eaiv dashboard``, or point Streamlit at ``app.py``.
"""

from __future__ import annotations

__all__ = ["app", "components", "runner", "state", "theme"]
