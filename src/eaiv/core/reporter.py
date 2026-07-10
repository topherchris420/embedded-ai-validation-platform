"""Multi-format reporting: console, JSON, CSV, Markdown, and HTML artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from eaiv.core.results import AggregateResult


class Reporter:
    def __init__(self, out_dir: str) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()

    def publish(self, results: AggregateResult, metadata: dict | None = None) -> None:
        """Write all report artifacts.

        ``metadata`` (target identity, platform version) is embedded in the
        JSON payload and shown in the Markdown header so results stay
        comparable across boards and releases.
        """
        self._console(results)
        self._json(results, metadata)
        self._csv(results)
        self._markdown(results, metadata)
        self._html(results)

    def _console(self, results: AggregateResult) -> None:
        t = Table(title="eaiv validation report", show_lines=True)
        t.add_column("Suite")
        t.add_column("Status")
        t.add_column("Metrics")
        t.add_column("Notes")
        for s in results:
            t.add_row(
                s.name,
                "[green]PASS[/green]" if s.passed else "[red]FAIL[/red]",
                json.dumps(s.metrics),
                s.notes,
            )
        self.console.print(t)

    def _json(self, results: AggregateResult, metadata: dict | None = None) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        payload = {
            "timestamp": ts,
            "meta": metadata or {},
            "suites": [asdict(s) for s in results],
            "all_passed": results.all_passed(),
        }
        fname = f"report_{ts.replace(':', '-')}.json"
        (self.out_dir / fname).write_text(json.dumps(payload, indent=2))
        # Also write/overwrite a stable "latest" pointer for CI artifacts.
        (self.out_dir / "latest.json").write_text(json.dumps(payload, indent=2))

    def _csv(self, results: AggregateResult) -> None:
        """Long-format CSV (suite, metric, value, passed) — trivially
        ingestible by spreadsheets, pandas, or a time-series store."""
        with (self.out_dir / "report.csv").open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["suite", "metric", "value", "passed"])
            for s in results:
                writer.writerow([s.name, "_passed", s.passed, s.passed])
                for key, value in s.metrics.items():
                    writer.writerow([s.name, key, value, s.passed])

    def _markdown(self, results: AggregateResult, metadata: dict | None = None) -> None:
        """Markdown summary — renders directly in PRs and CI job summaries."""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        target = (metadata or {}).get("target", {})
        target_line = ""
        if target:
            desc = target.get("name") or target.get("kind", "")
            arch = f" ({target['arch']})" if target.get("arch") else ""
            target_line = f"Target: {desc}{arch}  \n"
        lines = [
            "# eaiv validation report",
            "",
            f"Generated: {ts}  ",
            target_line + f"Overall: {'**PASS**' if results.all_passed() else '**FAIL**'}",
            "",
            "| Suite | Status | Notes |",
            "|-------|--------|-------|",
        ]
        for s in results:
            status = "✅ PASS" if s.passed else "❌ FAIL"
            notes = s.notes.replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(f"| {s.name} | {status} | {notes} |")
        for s in results:
            if not s.metrics:
                continue
            lines += ["", f"## {s.name}", "", "| Metric | Value |", "|--------|-------|"]
            for key, value in s.metrics.items():
                lines.append(f"| {key} | {value} |")
        (self.out_dir / "report.md").write_text("\n".join(lines) + "\n")

    def _html(self, results: AggregateResult) -> None:
        rows = "".join(
            f"<tr><td>{s.name}</td>"
            f"<td class='{'pass' if s.passed else 'fail'}'>"
            f"{'PASS' if s.passed else 'FAIL'}</td>"
            f"<td><pre>{json.dumps(s.metrics, indent=2)}</pre></td>"
            f"<td>{s.notes}</td></tr>"
            for s in results
        )
        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>eaiv report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; vertical-align: top; }}
.pass {{ color: #0a7d1f; font-weight: 600; }}
.fail {{ color: #b3261e; font-weight: 600; }}
pre {{ margin: 0; white-space: pre-wrap; }}
</style></head>
<body>
<h1>eaiv report</h1>
<table>
<tr><th>Suite</th><th>Status</th><th>Metrics</th><th>Notes</th></tr>
{rows}
</table>
</body></html>"""
        (self.out_dir / "report.html").write_text(html)
