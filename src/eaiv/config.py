"""Configuration loader with YAML inheritance.

A config file may set an `inherit: other.yaml` key (path relative to the
file itself). The parent is loaded first and deep-merged with the child,
so child values override parent values key-by-key rather than wholesale.

Loading is deliberately strict about *how* it fails: a malformed file, a
missing parent, or an inheritance cycle each produce a
:class:`ConfigError` naming the file and the problem, because these
messages are surfaced verbatim in the CLI and the mission builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """A configuration file could not be loaded."""


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)
    #: Files that contributed to this config, parents first. Empty for
    #: configs built in memory.
    sources: list[str] = field(default_factory=list)

    def __getitem__(self, k: str) -> Any:
        return self.raw[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self.raw.get(k, default)

    def __contains__(self, k: str) -> bool:
        return k in self.raw

    def section(self, name: str) -> dict[str, Any]:
        """A top-level mapping section, or ``{}`` if absent/not a mapping."""
        value = self.raw.get(name)
        return dict(value) if isinstance(value, dict) else {}

    def to_yaml(self) -> str:
        """Serialize the resolved configuration back to valid YAML."""
        return str(yaml.safe_dump(self.raw, sort_keys=False, default_flow_style=False))


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def deep_merge(base: dict, overlay: dict) -> dict:
    """Public deep merge with the same semantics as ``inherit:``."""
    return _deep_merge(base, overlay)


def _load_raw(path: Path, seen: tuple[Path, ...]) -> tuple[dict[str, Any], list[str]]:
    resolved = path.resolve()
    if resolved in seen:
        chain = " -> ".join(p.name for p in (*seen, resolved))
        raise ConfigError(f"Configuration inheritance cycle: {chain}")
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration {path} must be a mapping, got {type(data).__name__}")

    sources = [str(path)]
    if "inherit" in data:
        parent_name = data.pop("inherit")
        if not isinstance(parent_name, str):
            raise ConfigError(f"'inherit' in {path} must be a filename, got {parent_name!r}")
        parent_path = (path.parent / parent_name).resolve()
        parent, parent_sources = _load_raw(parent_path, (*seen, resolved))
        data = _deep_merge(parent, data)
        sources = [*parent_sources, str(path)]
    return data, sources


def load_config(path: str | Path) -> Config:
    """Load a config file, resolving ``inherit:`` chains."""
    data, sources = _load_raw(Path(path), ())
    return Config(data, sources=sources)


def config_from_dict(raw: dict[str, Any]) -> Config:
    """Wrap an in-memory mapping (already resolved) as a Config."""
    return Config(dict(raw))


__all__ = ["Config", "ConfigError", "config_from_dict", "deep_merge", "load_config"]
