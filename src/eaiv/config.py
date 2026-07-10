"""Configuration loader with YAML inheritance.

A config file may set an `inherit: other.yaml` key (path relative to the
file itself). The parent is loaded first and deep-merged with the child,
so child values override parent values key-by-key rather than wholesale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, k: str) -> Any:
        return self.raw[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self.raw.get(k, default)

    def __contains__(self, k: str) -> bool:
        return k in self.raw


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> Config:
    p = Path(path)
    data = yaml.safe_load(p.read_text()) or {}
    if "inherit" in data:
        parent_name = data.pop("inherit")
        parent_path = p.parent / parent_name
        parent = load_config(parent_path).raw
        data = _deep_merge(parent, data)
    return Config(data)
