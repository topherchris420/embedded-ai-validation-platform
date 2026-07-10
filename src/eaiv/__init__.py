"""eaiv — Embedded AI Validation Platform."""
from __future__ import annotations

__version__ = "0.1.0"

from eaiv.config import load_config              # noqa: E402
from eaiv.core.orchestrator import Orchestrator  # noqa: E402

__all__ = ["Orchestrator", "load_config", "__version__"]
