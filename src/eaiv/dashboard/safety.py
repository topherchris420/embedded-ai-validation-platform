"""Path and upload guards for browser-supplied input.

The dashboard runs on an engineer's machine, but its inputs still arrive
from a browser: a directory typed into a text box, a CSV dropped onto an
uploader, a run id in a query string. None of those may be allowed to
address arbitrary files. Everything a page opens goes through
:func:`resolve_within`, which resolves symlinks and then proves the
result is inside an allowed root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Uploaded files above this size are rejected rather than parsed.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

#: Telemetry CSVs larger than this are read in a bounded preview instead
#: of being loaded whole.
LARGE_CSV_BYTES = 16 * 1024 * 1024


class UnsafePathError(ValueError):
    """A user-supplied path resolved outside every allowed root."""


@dataclass(frozen=True)
class PathPolicy:
    """The directories a dashboard session is allowed to read."""

    roots: tuple[Path, ...]

    @classmethod
    def build(cls, *candidates: str | Path) -> PathPolicy:
        resolved: list[Path] = []
        for candidate in candidates:
            if not candidate:
                continue
            try:
                path = Path(candidate).resolve()
            except OSError:
                continue
            resolved.append(path)
        if not resolved:
            resolved.append(Path.cwd().resolve())
        return cls(tuple(dict.fromkeys(resolved)))

    def describe(self) -> str:
        return ", ".join(str(r) for r in self.roots)


def is_within(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or lives under it."""
    return path == root or root in path.parents


def resolve_within(policy: PathPolicy, user_path: str | Path) -> Path:
    """Resolve a user-supplied path, refusing anything outside the policy.

    Relative paths are interpreted against the first allowed root, which
    makes ``reports`` mean "the report directory" rather than "whatever
    the process happens to have as its cwd".
    """
    raw = Path(user_path)
    base = policy.roots[0]
    candidate = raw if raw.is_absolute() else base / raw
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise UnsafePathError(f"Cannot resolve {user_path!r}: {exc}") from exc
    if not any(is_within(resolved, root) for root in policy.roots):
        raise UnsafePathError(
            f"{user_path!r} is outside the directories this dashboard may read "
            f"({policy.describe()})."
        )
    return resolved


def check_upload(name: str, size_bytes: int) -> None:
    """Reject uploads that are too large to parse safely."""
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"{name} is {size_bytes / 1024 / 1024:.1f} MB; the limit is "
            f"{MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB. Downsample it or point the "
            "Telemetry Lab at the file on disk instead."
        )


def is_large(path: Path) -> bool:
    try:
        return path.stat().st_size > LARGE_CSV_BYTES
    except OSError:
        return False


__all__ = [
    "LARGE_CSV_BYTES",
    "MAX_UPLOAD_BYTES",
    "PathPolicy",
    "UnsafePathError",
    "check_upload",
    "is_large",
    "is_within",
    "resolve_within",
]
