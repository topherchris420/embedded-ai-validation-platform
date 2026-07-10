"""Plugin system for Embedded AI Validation Platform.

This module provides a unified plugin architecture allowing easy extension
without modifying core code. Plugins can add:
- New hardware targets (boards)
- New sensors
- New benchmarks
- New ML model backends
- New dashboard widgets
- New HIL simulators

Architecture:
- Plugin base classes define interfaces
- PluginRegistry tracks all registered plugins
- Factory functions create plugin instances from config
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TypeVar

# Type variable for plugin classes
T = TypeVar("T")


@dataclass
class PluginMetadata:
    """Metadata for a registered plugin."""

    name: str
    version: str
    description: str
    author: str = ""
    plugin_type: str = ""  # "target", "sensor", "benchmark", "model", "widget", "simulator"
    supported_hardware: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


class PluginRegistry:
    """Registry mapping (plugin_type, name) to metadata and a factory.

    A module-level default instance backs the ``register_plugin`` decorator
    and ``get_registry()``; components that want isolation (e.g. tests) can
    construct and pass around their own instance instead.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginMetadata] = {}
        self._factories: dict[str, Callable[[dict], object]] = {}

    def register(self, metadata: PluginMetadata, factory: Callable[[dict], object]) -> None:
        """Register a plugin with its metadata and factory function.

        Args:
            metadata: Plugin metadata including name, version, type
            factory: Function that creates plugin instance from config dict
        """
        key = f"{metadata.plugin_type}:{metadata.name}"
        if key in self._plugins:
            raise ValueError(f"Plugin already registered: {key}")
        self._plugins[key] = metadata
        self._factories[key] = factory

    def get(self, plugin_type: str, name: str) -> PluginMetadata | None:
        """Get metadata for a specific plugin."""
        key = f"{plugin_type}:{name}"
        return self._plugins.get(key)

    def list_plugins(self, plugin_type: str | None = None) -> list[PluginMetadata]:
        """List all registered plugins, optionally filtered by type."""
        if plugin_type is None:
            return list(self._plugins.values())
        return [p for p in self._plugins.values() if p.plugin_type == plugin_type]

    def create(self, plugin_type: str, name: str, config: dict) -> object:
        """Create a plugin instance from config.

        Args:
            plugin_type: Type of plugin (e.g., "target", "sensor")
            name: Plugin name (e.g., "esp32", "stm32")
            config: Configuration dict for the plugin

        Returns:
            Plugin instance

        Raises:
            ValueError: If plugin not found
        """
        key = f"{plugin_type}:{name}"
        factory = self._factories.get(key)
        if factory is None:
            available = [k for k in self._plugins.keys() if k.startswith(f"{plugin_type}:")]
            raise ValueError(
                f"Plugin not found: {key}. Available {plugin_type} plugins: {available}"
            )
        return factory(config)

    def unregister(self, plugin_type: str, name: str) -> None:
        """Unregister a plugin."""
        key = f"{plugin_type}:{name}"
        self._plugins.pop(key, None)
        self._factories.pop(key, None)


def register_plugin(
    name: str,
    plugin_type: str,
    description: str = "",
    version: str = "0.1.0",
    author: str = "",
    supported_hardware: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> Callable[[Callable[[dict], T]], Callable[[dict], T]]:
    """Decorator to register a plugin with the global registry.

    Usage:
        @register_plugin("esp32", "target", "ESP32 board support", version="1.0.0")
        def create_esp32(config: dict) -> Target:
            return ESP32Target(config)

    Args:
        name: Plugin name (e.g., "esp32", "stm32")
        plugin_type: Plugin category (target, sensor, benchmark, etc.)
        description: Human-readable description
        version: Plugin version
        author: Plugin author
        supported_hardware: List of supported hardware identifiers
        dependencies: Required dependencies

    Returns:
        Decorator function
    """

    def decorator(factory: Callable[[dict], T]) -> Callable[[dict], T]:
        metadata = PluginMetadata(
            name=name,
            version=version,
            description=description,
            author=author,
            plugin_type=plugin_type,
            supported_hardware=supported_hardware or [],
            dependencies=dependencies or [],
        )
        _default_registry.register(metadata, factory)
        return factory

    return decorator


_default_registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    """Get the default (process-wide) plugin registry instance."""
    return _default_registry


def load_entry_point_plugins(group: str = "eaiv.plugins") -> int:
    """Import third-party plugin modules advertised via entry points.

    External packages contribute plugins by exposing a module in the
    ``eaiv.plugins`` entry-point group; importing the module runs its
    ``register_plugin`` decorators against the default registry.

    Returns the number of entry points loaded.
    """
    from importlib.metadata import entry_points

    count = 0
    for ep in entry_points(group=group):
        ep.load()
        count += 1
    return count
