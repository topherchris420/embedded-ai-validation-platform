"""Multi-format reporting: console table, JSON artifact, static HTML page."""
from __future__ import annotations

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

    def publish(self, results: AggregateResult) -> None:
        self._console(results)
        self._json(results)
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

    def _json(self, results: AggregateResult) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        payload = {
            "timestamp": ts,
            "suites": [asdict(s) for s in results],
            "all_passed": results.all_passed(),
        }
        fname = f"report_{ts.replace(':', '-')}.json"
        (self.out_dir / fname).write_text(json.dumps(payload, indent=2))
        # Also write/overwrite a stable "latest" pointer for CI artifacts.
        (self.out_dir / "latest.json").write_text(json.dumps(payload, indent=2))

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
