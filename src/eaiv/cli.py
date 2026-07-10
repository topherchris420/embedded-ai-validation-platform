"""Command-line entry point.

Command groups:
    run       — execute validation suites against a target
    show      — print the resolved configuration
    plugins   — list registered plugins (targets, filters, faults, ...)
    targets   — shorthand for ``plugins --type target``
    flash     — flash a firmware binary to the configured target
    monitor   — stream serial output from the configured target
    datasets  — dataset tools (generate synthetic replay logs)
    compare   — regression-gate two report JSON artifacts
"""

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
    type=click.Choice(["firmware", "tinyml", "fusion", "hil", "rt", "all"]),
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


def _load_all_plugins() -> None:
    """Import modules whose side effect is registering built-in plugins."""
    import eaiv.hil  # noqa: F401  (fault + sim-target plugins)
    import eaiv.sensor_fusion.fusion  # noqa: F401  (fusion_filter plugins)
    import eaiv.targets  # noqa: F401  (target plugins)

    from eaiv.plugins import load_entry_point_plugins

    load_entry_point_plugins()


@main.command()
@click.option("--type", "plugin_type", default=None, help="Filter by plugin type.")
def plugins(plugin_type: str | None) -> None:
    """List registered plugins."""
    from eaiv.plugins import get_registry

    _load_all_plugins()
    for meta in get_registry().list_plugins(plugin_type):
        click.echo(f"{meta.plugin_type:<14} {meta.name:<14} {meta.version:<8} {meta.description}")


@main.command()
def targets() -> None:
    """List registered target backends."""
    from eaiv.plugins import get_registry

    _load_all_plugins()
    for meta in get_registry().list_plugins("target"):
        click.echo(f"{meta.name:<12} {meta.version:<8} {meta.description}")


@main.command()
@click.argument("binary", type=click.Path(exists=True))
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
def flash(binary: str, config_path: str) -> None:
    """Flash a firmware BINARY to the configured target."""
    from eaiv.targets import build_target

    _load_all_plugins()
    cfg = load_config(config_path)
    with build_target(cfg["target"]) as target:
        target.flash(binary)
        click.echo(f"flashed {binary} to {target.info().name}")


@main.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--duration", "duration_s", default=10.0, help="Seconds to read serial output.")
def monitor(config_path: str, duration_s: float) -> None:
    """Stream serial output from the configured target."""
    from eaiv.targets import build_target

    _load_all_plugins()
    cfg = load_config(config_path)
    with build_target(cfg["target"]) as target:
        binary = cfg["target"].get("binary")
        if binary:
            target.flash(binary)
        click.echo(target.read_serial(duration_s), nl=False)


@main.group()
def datasets() -> None:
    """Dataset tools."""


@datasets.command("generate")
@click.option(
    "--profile",
    type=click.Choice(["static", "gentle", "aggressive"]),
    default="gentle",
    help="Motion profile.",
)
@click.option("--duration", "duration_s", default=20.0, help="Log duration in seconds.")
@click.option("--rate", "rate_hz", default=100.0, help="Sample rate in Hz.")
@click.option("--seed", default=0, help="RNG seed (same seed => identical log).")
@click.option("--gyro-noise", "gyro_noise_std", default=0.005, help="Gyro noise std (rad/s).")
@click.option("--accel-noise", "accel_noise_std", default=0.01, help="Accel noise std (g).")
@click.option("-o", "--output", required=True, type=click.Path(), help="Output CSV path.")
def datasets_generate(
    profile: str,
    duration_s: float,
    rate_hz: float,
    seed: int,
    gyro_noise_std: float,
    accel_noise_std: float,
    output: str,
) -> None:
    """Generate a deterministic synthetic IMU replay log."""
    from eaiv.datasets import generate_imu_trajectory, write_imu_csv

    samples = generate_imu_trajectory(
        duration_s=duration_s,
        rate_hz=rate_hz,
        profile=profile,
        seed=seed,
        gyro_noise_std=gyro_noise_std,
        accel_noise_std=accel_noise_std,
    )
    path = write_imu_csv(samples, output)
    click.echo(f"wrote {len(samples)} samples to {path}")


@main.command()
@click.argument("baseline", type=click.Path(exists=True))
@click.argument("current", type=click.Path(exists=True))
@click.option(
    "--max-regression-pct",
    default=10.0,
    help="Allowed worsening per metric before the gate fails.",
)
@click.option("--verbose", is_flag=True, help="Print every compared metric, not just regressions.")
def compare(baseline: str, current: str, max_regression_pct: float, verbose: bool) -> None:
    """Compare two report JSONs and exit non-zero on metric regressions."""
    from eaiv.core.regression import compare_reports, load_report

    report = compare_reports(
        load_report(baseline), load_report(current), max_regression_pct=max_regression_pct
    )
    shown = report.deltas if verbose else report.regressions
    for d in shown:
        arrow = {1: "higher-is-better", -1: "lower-is-better", 0: "informational"}[d.direction]
        flag = "REGRESSED" if d.regressed else "ok"
        click.echo(
            f"[{flag:>9}] {d.suite}.{d.metric}: {d.baseline:g} -> {d.current:g} "
            f"({d.change_pct:+.2f}%, {arrow})"
        )
    if report.passed:
        click.echo(f"no regressions across {len(report.deltas)} shared metrics")
        sys.exit(0)
    click.echo(f"{len(report.regressions)} regression(s) beyond {max_regression_pct}%")
    sys.exit(1)


if __name__ == "__main__":
    main()
