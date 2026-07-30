"""Compatibility entry point for the bundled dashboard.

The application now lives inside the package at
``eaiv.dashboard.ui.app`` so it can be split into pages, imported by
tests, and launched by ``eaiv dashboard``. This file stays because the
documented command

    streamlit run dashboard/python/app.py

should keep working.
"""

from __future__ import annotations

from eaiv.dashboard.ui.app import main

main()
