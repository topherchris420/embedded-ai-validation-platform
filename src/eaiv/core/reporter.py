"""Multi-format reporting: console, JSON, CSV, Markdown, and HTML artifacts.

The JSON payload is the canonical artifact and carries a
``schema_version`` (see :mod:`eaiv.core.report_schema`) plus enough
context — resolved config, target identity, host, git revision, input
hashes, thresholds, metric provenance — to reproduce and compare the run
later. The other formats are renderings of the same payload.

Legacy consumers are unaffected: ``report_<timestamp>.json`` and
``latest.json`` are still written to the same locations with the same
top-level keys.
"""

from __future__ import annotations

import csv
import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from eaiv.core.metrics import MetricProvenance, format_value
from eaiv.core.report_schema import (
    REPORT_SCHEMA_VERSION,
    metric_info,
    normalize_report,
    overall_provenance,
)
from eaiv.core.results import AggregateResult


class PublishedReport:
    """Paths and payload produced by one :meth:`Reporter.publish` call."""

    def __init__(self, payload: dict[str, Any], paths: dict[str, Path]) -> None:
        self.payload = payload
        self.paths = paths

    @property
    def json_path(self) -> Path:
        return self.paths["json"]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PublishedReport({self.paths['json']})"


class Reporter:
    def __init__(self, out_dir: str | Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()

    def publish(
        self,
        results: AggregateResult,
        metadata: dict | None = None,
        run: dict | None = None,
        mirror_dir: str | Path | None = None,
        quiet: bool = False,
    ) -> PublishedReport:
        """Write all report artifacts.

        ``metadata`` (target identity, host, git, thresholds, input
        hashes) is embedded in the JSON payload and summarised in the
        Markdown/HTML headers so results stay comparable across boards and
        releases. ``mirror_dir`` additionally writes the same four
        artifacts into a run directory under stable names.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = self._payload(results, metadata, run, timestamp)
        normalized = normalize_report(payload)

        if not quiet:
            self._console(results)

        paths: dict[str, Path] = {}
        json_text = json.dumps(payload, indent=2, default=str)
        stamped = self.out_dir / f"report_{timestamp.replace(':', '-')}.json"
        stamped.write_text(json_text, encoding="utf-8")
        (self.out_dir / "latest.json").write_text(json_text, encoding="utf-8")
        paths["json"] = stamped
        paths["latest"] = self.out_dir / "latest.json"
        paths["csv"] = self._csv(results, self.out_dir / "report.csv")
        paths["md"] = self._markdown(normalized, self.out_dir / "report.md")
        paths["html"] = self._html(normalized, self.out_dir / "report.html")

        if mirror_dir is not None:
            target = Path(mirror_dir)
            target.mkdir(parents=True, exist_ok=True)
            (target / "report.json").write_text(json_text, encoding="utf-8")
            paths["run_json"] = target / "report.json"
            paths["run_csv"] = self._csv(results, target / "report.csv")
            paths["run_md"] = self._markdown(normalized, target / "report.md")
            paths["run_html"] = self._html(normalized, target / "report.html")

        return PublishedReport(payload, paths)

    # -- payload -----------------------------------------------------------

    def _payload(
        self,
        results: AggregateResult,
        metadata: dict | None,
        run: dict | None,
        timestamp: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "timestamp": timestamp,
            "run": run or {},
            "meta": metadata or {},
            "suites": [asdict(s) for s in results],
            "all_passed": results.all_passed(),
        }

    # -- renderings --------------------------------------------------------

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
                json.dumps(s.metrics, default=str),
                s.notes,
            )
        self.console.print(t)

    def _csv(self, results: AggregateResult, path: Path) -> Path:
        """Long-format CSV (suite, metric, value, unit, provenance, passed) —
        trivially ingestible by spreadsheets, pandas, or a time-series store.
        The two leading columns are unchanged from the original format."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["suite", "metric", "value", "passed", "unit", "provenance"])
            for s in results:
                writer.writerow([s.name, "_passed", s.passed, s.passed, "", ""])
                for key, value in s.metrics.items():
                    declared = s.metric_meta.get(key, {}) if isinstance(s.metric_meta, dict) else {}
                    writer.writerow(
                        [
                            s.name,
                            key,
                            value,
                            s.passed,
                            declared.get("unit", ""),
                            declared.get("provenance", ""),
                        ]
                    )
        return path

    def _markdown(self, report: dict[str, Any], path: Path) -> Path:
        """Markdown summary — renders directly in PRs and CI job summaries."""
        ts = str(report.get("timestamp", ""))[:19]
        meta = report.get("meta", {})
        target = meta.get("target", {}) or {}
        target_line = ""
        if target:
            desc = target.get("name") or target.get("kind", "")
            arch = f" ({target['arch']})" if target.get("arch") else ""
            target_line = f"Target: {desc}{arch}  \n"
        provenance = overall_provenance(report)
        lines = [
            "# eaiv validation report",
            "",
            f"Generated: {ts}  ",
            target_line + f"Overall: {'**PASS**' if report.get('all_passed') else '**FAIL**'}",
            "",
            f"Measurement provenance: **{provenance}**"
            + (
                "  \n> Values in this report were produced without physical hardware."
                if provenance == "simulated"
                else ""
            ),
            "",
            "| Suite | Status | Notes |",
            "|-------|--------|-------|",
        ]
        for s in report.get("suites", []):
            status = "PASS" if s.get("passed") else "FAIL"
            notes = str(s.get("notes", "")).replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(f"| {s.get('name')} | {status} | {notes} |")
        for s in report.get("suites", []):
            metrics = s.get("metrics") or {}
            if not metrics:
                continue
            name = str(s.get("name"))
            lines += ["", f"## {name}", "", "| Metric | Value | Origin |", "|--------|-------|--------|"]
            for key, value in metrics.items():
                info = metric_info(report, name, key)
                origin = "—" if info.provenance is MetricProvenance.UNKNOWN else info.provenance.label
                lines.append(f"| {key} | {format_value(value, info)} | {origin} |")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _html(self, report: dict[str, Any], path: Path) -> Path:
        """Standalone HTML report.

        Every interpolated value is HTML-escaped: notes carry raw device
        output and metric keys can come from third-party suite plugins, so
        neither may be trusted as markup.
        """
        esc = html.escape
        rows = []
        for s in report.get("suites", []):
            name = esc(str(s.get("name", "?")))
            passed = bool(s.get("passed"))
            metrics = json.dumps(s.get("metrics") or {}, indent=2, default=str)
            rows.append(
                f"<tr><td>{name}</td>"
                f"<td class='{'pass' if passed else 'fail'}'>"
                f"{'PASS' if passed else 'FAIL'}</td>"
                f"<td><pre>{esc(metrics)}</pre></td>"
                f"<td>{esc(str(s.get('notes', '')))}</td></tr>"
            )
        meta = report.get("meta", {})
        target = meta.get("target", {}) or {}
        provenance = overall_provenance(report)
        banner = (
            "<p class='banner'>Values in this report were produced without physical "
            "hardware (provenance: simulated).</p>"
            if provenance == "simulated"
            else ""
        )
        html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>eaiv report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #12161c; background: #fff; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; vertical-align: top; }}
.pass {{ color: #0a6b1c; font-weight: 600; }}
.fail {{ color: #a3221b; font-weight: 600; }}
.banner {{ border-left: 4px solid #8a6100; background: #fdf6e3; padding: 0.6rem 0.9rem; }}
dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 0.2rem 1rem; }}
dt {{ font-weight: 600; }}
pre {{ margin: 0; white-space: pre-wrap; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #0f1216; color: #e6e9ef; }}
  td, th {{ border-color: #333b46; }}
  .pass {{ color: #6fdc8c; }} .fail {{ color: #ff8a80; }}
  .banner {{ background: #241d0c; border-color: #b98900; }}
}}
</style></head>
<body>
<h1>eaiv validation report</h1>
{banner}
<dl>
<dt>Generated</dt><dd>{esc(str(report.get("timestamp", "")))}</dd>
<dt>Overall</dt><dd>{"PASS" if report.get("all_passed") else "FAIL"}</dd>
<dt>Target</dt><dd>{esc(str(target.get("name") or target.get("kind", "unknown")))}</dd>
<dt>eaiv version</dt><dd>{esc(str(meta.get("eaiv_version", "unknown")))}</dd>
<dt>Provenance</dt><dd>{esc(provenance)}</dd>
</dl>
<table>
<tr><th>Suite</th><th>Status</th><th>Metrics</th><th>Notes</th></tr>
{"".join(rows)}
</table>
</body></html>"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_doc, encoding="utf-8")
        return path


__all__ = ["PublishedReport", "Reporter"]
