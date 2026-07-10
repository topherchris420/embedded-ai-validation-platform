"""Baseline storage for regression gating.

A baseline is a validation report payload promoted to a named reference.
Baselines live in a plain directory (default ``baselines/``) as JSON —
commit them to the repo, stash them as CI artifacts, or point the store
anywhere else; there is deliberately no database.

    store = BaselineStore("baselines")
    store.save("reports/latest.json", "v0.4-esp32")
    report = compare_reports(store.load("v0.4-esp32"), current)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from eaiv.core.regression import load_report


@dataclass(frozen=True)
class BaselineInfo:
    """Summary row for one stored baseline."""

    name: str
    path: Path
    saved_at: str
    target: str
    eaiv_version: str
    all_passed: bool


class BaselineStore:
    """Named report snapshots on disk."""

    def __init__(self, root: str | Path = "baselines") -> None:
        self.root = Path(root)

    def path(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"Invalid baseline name: {name!r}")
        return self.root / f"{name}.json"

    def save(self, report: dict | str | Path, name: str) -> Path:
        """Promote a report (payload or path to one) to a named baseline."""
        payload = dict(report) if isinstance(report, dict) else load_report(report)
        if "suites" not in payload:
            raise ValueError("Not a report payload: missing 'suites'")
        payload["_baseline"] = {
            "name": name,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2))
        return path

    def load(self, name: str) -> dict:
        path = self.path(name)
        if not path.exists():
            available = [b.name for b in self.list()]
            raise FileNotFoundError(f"No baseline {name!r} in {self.root} (have: {available})")
        return load_report(path)

    def list(self) -> list[BaselineInfo]:
        """All stored baselines, newest first."""
        infos: list[BaselineInfo] = []
        if not self.root.exists():
            return infos
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = load_report(path)
            except (ValueError, json.JSONDecodeError):
                continue
            if "suites" not in payload:
                continue
            meta = payload.get("meta", {})
            infos.append(
                BaselineInfo(
                    name=path.stem,
                    path=path,
                    saved_at=payload.get("_baseline", {}).get("saved_at", ""),
                    target=meta.get("target", {}).get("name")
                    or meta.get("target", {}).get("kind", "?"),
                    eaiv_version=meta.get("eaiv_version", "?"),
                    all_passed=bool(payload.get("all_passed")),
                )
            )
        infos.sort(key=lambda b: b.saved_at, reverse=True)
        return infos
