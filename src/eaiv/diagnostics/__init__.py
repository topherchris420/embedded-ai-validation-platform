"""Environment diagnosis and the guided demo.

    from eaiv.diagnostics import run_diagnostics, run_demo

``run_diagnostics`` inspects the machine; ``run_demo`` produces a
complete, honestly-labelled simulated validation history so the platform
has something real to show before any hardware exists.
"""

from __future__ import annotations

from eaiv.diagnostics.demo import DEMO_BASELINE_NAME, DemoResult, run_demo
from eaiv.diagnostics.doctor import (
    Check,
    CheckStatus,
    Diagnosis,
    run_diagnostics,
)

__all__ = [
    "DEMO_BASELINE_NAME",
    "Check",
    "CheckStatus",
    "DemoResult",
    "Diagnosis",
    "run_demo",
    "run_diagnostics",
]
