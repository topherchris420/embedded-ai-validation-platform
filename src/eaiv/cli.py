"""Command-line entry point."""
from __future__ import annotations

import json
import sys

import click

from eaiv.config import load_config
from eaiv.core.orchestrator import Orchestrator


@click.group()
@click.version_option(package_name="eaiv")
def main() -> None:
    """eaiv — Embedded AI Validation Platform."""


@main.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option(
    "--suite",
    type=click.Choice(["firmware", "tinyml", "fusion", "rt", "all"]),
    default="all",
    help="Which validation suite to run.",
)
@click.option("--report-dir", default="reports", type=click.Path())
def run(config_path: str, suite: str, report_dir: str) -> None:
    """Run a validation suite and exit non-zero on any failure."""
    cfg = load_config(config_path)
    orch = Orchestrator(cfg, report_dir=report_dir)
    results = orch.run(suite)
    sys.exit(0 if results.all_passed() else 1)


@main.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
def show(config_path: str) -> None:
    """Print the fully resolved configuration (after `inherit` merging)."""
    cfg = load_config(config_path)
    click.echo(json.dumps(cfg.raw, indent=2))


@main.command()
def targets() -> None:
    """List supported target backends."""
    for name in ("qemu", "serial", "jlink"):
        click.echo(name)


if __name__ == "__main__":
    main()
