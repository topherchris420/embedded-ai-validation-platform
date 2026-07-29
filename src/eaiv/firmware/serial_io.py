"""Line-buffered serial reader with timeout-aware pattern matching."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable


def wait_for(
    stream_reader: Callable[[float], str],
    patterns: Iterable[str],
    timeout_s: float,
    poll_interval_s: float = 0.2,
) -> re.Match | None:
    """Poll `stream_reader(poll_interval_s)` until any pattern matches or
    the overall timeout elapses. Returns the match object, or None."""
    end = time.time() + timeout_s
    combined = re.compile("|".join(re.escape(p) for p in patterns))
    while time.time() < end:
        chunk = stream_reader(poll_interval_s)
        if chunk:
            m = combined.search(chunk)
            if m:
                return m
    return None
