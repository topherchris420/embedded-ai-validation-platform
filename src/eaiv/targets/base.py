"""Abstract hardware target interface shared by qemu/serial/jlink backends.

This module re-exports the plugin base class for backward compatibility.
New code should use eaiv.plugins.targets.Target directly.
"""
from __future__ import annotations

from eaiv.plugins.targets import Target, TargetInfo  # noqa: F401

__all__ = ["Target", "TargetInfo"]
