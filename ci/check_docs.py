#!/usr/bin/env python3
"""Validate documentation: every relative Markdown link must resolve.

Scans all tracked .md files for [text](target) links, skips absolute
URLs and pure anchors, and fails (exit 1) listing every link whose target
file does not exist. Run locally or in CI from the repository root:

    python ci/check_docs.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def tracked_markdown_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md", "**/*.md"], capture_output=True, text=True, check=True
    )
    return [Path(line) for line in out.stdout.splitlines() if line]


def check_file(md: Path) -> list[str]:
    errors: list[str] = []
    for match in LINK_RE.finditer(md.read_text(encoding="utf-8")):
        target = match.group(1)
        if target.startswith(SKIP_PREFIXES):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        resolved = (md.parent / path_part).resolve()
        if not resolved.exists():
            errors.append(f"{md}: broken link -> {target}")
    return errors


def main() -> int:
    errors: list[str] = []
    files = tracked_markdown_files()
    for md in files:
        errors.extend(check_file(md))
    for e in errors:
        print(e)
    print(f"checked {len(files)} markdown files: {len(errors)} broken link(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
