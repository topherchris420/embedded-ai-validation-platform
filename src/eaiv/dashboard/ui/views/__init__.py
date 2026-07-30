"""Mission Control views.

Each module exposes a single ``render(workspace)`` function and holds no
business logic: loading, diagnosis, comparison, and validation all live in
``eaiv.core``, ``eaiv.insights``, ``eaiv.configspec``, and
``eaiv.dashboard`` so they can be tested without a browser.
"""

from __future__ import annotations

__all__ = [
    "baselines",
    "compare",
    "inventory",
    "live_run",
    "mission_control",
    "new_run",
    "results",
    "telemetry_lab",
]
