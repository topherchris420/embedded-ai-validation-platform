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

from eaiv.plugins import get_registry, register_plugin
from eaiv.plugins.targets import Target, TargetInfo
from eaiv.targets.jlink import JLinkTarget
from eaiv.targets.qemu import QEMUTarget
from eaiv.targets.serial import SerialTarget


def build_target(spec: dict) -> Target:
    """Build a target from configuration.

    The plugin registry is the single construction path: built-in targets
    are registered on import, and third-party targets registered via
    ``register_plugin`` (or the ``eaiv.plugins`` entry-point group) are
    picked up automatically.

    Args:
        spec: Target configuration dict with 'kind' key

    Returns:
        Target instance

    Raises:
        ValueError: If target kind is unknown
    """
    kind = spec.get("kind", "qemu")
    target = get_registry().create("target", kind, spec)
    if not isinstance(target, Target):
        raise TypeError(f"Plugin 'target:{kind}' did not produce a Target: {type(target)!r}")
    return target


register_plugin(
    "qemu",
    "target",
    "QEMU ARM emulator target",
    version="1.0.0",
    supported_hardware=["qemu"],
)(QEMUTarget)

register_plugin(
    "serial",
    "target",
    "Serial connection target",
    version="1.0.0",
    supported_hardware=["*"],
)(SerialTarget)

register_plugin(
    "jlink",
    "target",
    "J-Link debugger target",
    version="1.0.0",
    dependencies=["pylink-square"],
)(JLinkTarget)


__all__ = [
    "Target",
    "TargetInfo",
    "build_target",
    "QEMUTarget",
    "SerialTarget",
    "JLinkTarget",
]
