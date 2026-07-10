"""Target backends for hardware communication.

This module provides target implementations for flashing, testing, and
profiling firmware on embedded devices. Targets can be real hardware
or emulators.

Plugin Architecture:
    Targets are registered plugins. Use register_plugin() to add new targets.

    @register_plugin("esp32", "target", "ESP32 board support")
    def create_esp32(config: dict) -> Target:
        return ESP32Target(config)

Built-in Targets:
    - qemu: QEMU ARM emulator
    - serial: Serial connection
    - jlink: J-Link debugger
"""
from __future__ import annotations

from eaiv.plugins.targets import Target, TargetInfo
from eaiv.plugins import get_registry

# Import implementations
from eaiv.targets.qemu import QEMUTarget
from eaiv.targets.serial import SerialTarget
from eaiv.targets.jlink import JLinkTarget


def build_target(spec: dict) -> Target:
    """Build a target from configuration.

    Args:
        spec: Target configuration dict with 'kind' key

    Returns:
        Target instance

    Raises:
        ValueError: If target kind is unknown
    """
    kind = spec.get("kind", "qemu")
    registry = get_registry()

    # Try plugin registry first
    try:
        return registry.create("target", kind, spec)
    except ValueError:
        pass  # Fall through to built-in targets

    # Built-in target factory
    factories = {
        "qemu": lambda cfg: QEMUTarget(cfg),
        "serial": lambda cfg: SerialTarget(cfg),
        "jlink": lambda cfg: JLinkTarget(cfg),
    }

    if kind not in factories:
        raise ValueError(
            f"Unknown target kind: {kind}. Available: {list(factories.keys())}"
        )

    return factories[kind](spec)


# Register built-in targets with plugin registry
from eaiv.plugins import register_plugin


def _register_targets() -> None:
    """Register built-in targets with the plugin registry."""
    register_plugin(
        "qemu",
        "target",
        "QEMU ARM emulator target",
        version="1.0.0",
        supported_hardware=["qemu"],
    )(lambda cfg: QEMUTarget(cfg))

    register_plugin(
        "serial",
        "target",
        "Serial connection target",
        version="1.0.0",
        supported_hardware=["*"],
    )(lambda cfg: SerialTarget(cfg))

    register_plugin(
        "jlink",
        "target",
        "J-Link debugger target",
        version="1.0.0",
        dependencies=["pylink-square"],
    )(lambda cfg: JLinkTarget(cfg))


# Auto-register on import
_register_targets()


__all__ = [
    "Target",
    "TargetInfo",
    "build_target",
    "QEMUTarget",
    "SerialTarget",
    "JLinkTarget",
]
