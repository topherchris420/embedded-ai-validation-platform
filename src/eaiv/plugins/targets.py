"""Target plugin base classes and registry.

Hardware targets are the interfaces used to communicate with embedded devices
for flashing, testing, and profiling. This module provides the plugin interface
for target backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from eaiv.plugins import register_plugin

if TYPE_CHECKING:
    from eaiv.plugins import PluginMetadata


@dataclass
class TargetInfo:
    """Information about a target device."""

    name: str
    arch: str
    clock_hz: int
    flash_size_kb: int = 0
    ram_size_kb: int = 0


class Target(ABC):
    """Abstract hardware target interface.

    A target represents a device (real or emulated) that firmware can be
    flashed to and communicated with over some transport.

    Implementations must provide:
    - flash(): Write firmware to device
    - reset(): Reboot the device
    - run_command(): Execute a command and get response
    - read_serial(): Read serial output
    - info(): Get device information
    """

    def __init__(self, spec: dict) -> None:
        self.spec = spec

    @abstractmethod
    def flash(self, binary: str) -> None:
        """Flash firmware to the device.

        Args:
            binary: Path to firmware binary/ELF file

        Raises:
            FlashError: If flashing fails
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset the device."""
        ...

    @abstractmethod
    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        """Run a command on the device and return the response.

        Args:
            cmd: Command string to execute
            timeout_s: Timeout in seconds

        Returns:
            Command response string
        """
        ...

    @abstractmethod
    def read_serial(self, duration_s: float) -> str:
        """Read serial output for a duration.

        Args:
            duration_s: Duration to read in seconds

        Returns:
            Serial output string
        """
        ...

    @abstractmethod
    def info(self) -> TargetInfo:
        """Get device information.

        Returns:
            TargetInfo with device details
        """
        ...

    def close(self) -> None:
        """Clean up resources. Override if needed."""
        pass

    def __enter__(self) -> Target:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class TargetPluginMixin:
    """Mixin to provide plugin metadata for targets.

    Usage:
        class ESP32Target(Target, TargetPluginMixin):
            PLUGIN_METADATA = PluginMetadata(
                name="esp32",
                plugin_type="target",
                description="ESP32 board support",
                version="1.0.0",
                supported_hardware=["esp32", "esp32-s3"],
            )
    """

    PLUGIN_METADATA: PluginMetadata = None  # type: ignore[assignment]


__all__ = [
    "Target",
    "TargetInfo",
    "TargetPluginMixin",
    "register_plugin",
]
