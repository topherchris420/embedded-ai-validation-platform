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
    default="all",
    help="Suite to run: firmware | tinyml | fusion | hil | memory | rt | all, "
    "or any 'suite' plugin listed under extra_suites in the config.",
)
@click.option("--report-dir", default="reports", type=click.Path())
def run(config_path: str, suite: str, report_dir: str) -> None:
    """Run a validation suite and exit non-zero on any failure."""
    _load_all_plugins()
    cfg = load_config(config_path)
    orch = Orchestrator(cfg, report_dir=report_dir)
    try:
        results = orch.run(suite)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="--suite") from None
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
@click.option("--adapter", default="eaiv-line", help="Telemetry adapter plugin to parse with.")
@click.option("--csv", "csv_path", default=None, type=click.Path(), help="Export telemetry CSV.")
@click.option("--summary", is_flag=True, help="Print per-field statistics instead of raw output.")
def monitor(
    config_path: str, duration_s: float, adapter: str, csv_path: str | None, summary: bool
) -> None:
    """Stream serial output from the configured target.

    With --csv/--summary the output is parsed through the telemetry
    adapter into structured records instead of echoed raw.
    """
    from eaiv.targets import build_target
    from eaiv.telemetry import TelemetryCollector, build_adapter

    _load_all_plugins()
    cfg = load_config(config_path)
    with build_target(cfg["target"]) as target:
        binary = cfg["target"].get("binary")
        if binary:
            target.flash(binary)
        raw = target.read_serial(duration_s)

    if not csv_path and not summary:
        click.echo(raw, nl=False)
        return

    collector = TelemetryCollector(build_adapter(adapter))
    collector.feed(raw)
    if csv_path:
        path = collector.to_csv(csv_path)
        click.echo(f"wrote {len(collector.telemetry)} samples to {path}")
    if summary:
        stats = collector.summary()
        click.echo(f"samples={stats.samples} duration_s={stats.duration_s} rate_hz={stats.rate_hz}")
        for name, st in stats.fields.items():
            click.echo(
                f"  {name:<12} min={st['min']:+.5f} max={st['max']:+.5f} "
                f"mean={st['mean']:+.5f} std={st['std']:.5f}"
            )
        verdict = collector.verdict
        if verdict is not None:
            click.echo(f"verdict: {'PASS' if verdict.passed else 'FAIL ' + verdict.reason}")


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
    from eaiv.datasets import imu_metadata, write_metadata

    meta = imu_metadata(
        name=path.stem,
        description=f"Synthetic IMU log ({profile} profile, seed {seed})",
        sampling_rate_hz=rate_hz,
        generator={
            "profile": profile,
            "seed": seed,
            "duration_s": duration_s,
            "rate_hz": rate_hz,
            "gyro_noise_std": gyro_noise_std,
            "accel_noise_std": accel_noise_std,
        },
    )
    meta_path = write_metadata(meta, path)
    click.echo(f"wrote {len(samples)} samples to {path} (+ {meta_path.name})")


@main.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--suite", default="all", help="Suite selection, as in 'eaiv run'.")
@click.option("--build-env", default=None, help="PlatformIO env to build first (e.g. esp32).")
@click.option("--baseline", "baseline_name", default=None, help="Baseline name to gate against.")
@click.option("--save-baseline", default=None, help="Promote this run to a named baseline.")
@click.option("--baseline-dir", default="baselines", type=click.Path())
@click.option("--telemetry-duration", default=0.0, help="Seconds of telemetry to capture (0=skip).")
@click.option("--max-regression-pct", default=10.0)
@click.option("--report-dir", default="reports", type=click.Path())
def pipeline(
    config_path: str,
    suite: str,
    build_env: str | None,
    baseline_name: str | None,
    save_baseline: str | None,
    baseline_dir: str,
    telemetry_duration: float,
    max_regression_pct: float,
    report_dir: str,
) -> None:
    """Run the full validation pipeline: build, validate, telemetry, compare.

    Exit code 0 only if every stage, every suite, and the regression gate
    pass — designed as a single CI entry point.
    """
    from eaiv.core.baseline import BaselineStore
    from eaiv.core.pipeline import ValidationPipeline

    _load_all_plugins()
    cfg = load_config(config_path)
    pipe = ValidationPipeline(
        cfg, report_dir=report_dir, baseline_store=BaselineStore(baseline_dir)
    )
    result = pipe.run(
        suite=suite,
        build_env=build_env,
        baseline=baseline_name,
        save_baseline=save_baseline,
        telemetry_s=telemetry_duration,
        max_regression_pct=max_regression_pct,
    )
    for stage in result.stages:
        click.echo(
            f"[{stage.status:>7}] {stage.name:<14} {stage.duration_s:>8.3f}s  {stage.detail}"
        )
    click.echo("pipeline: PASS" if result.passed else "pipeline: FAIL")
    sys.exit(0 if result.passed else 1)


@main.group()
def baseline() -> None:
    """Manage named baseline reports for regression gating."""


@baseline.command("save")
@click.argument("report", type=click.Path(exists=True))
@click.option("--name", required=True, help="Baseline name (filename-safe).")
@click.option("--dir", "root", default="baselines", type=click.Path(), help="Baseline directory.")
def baseline_save(report: str, name: str, root: str) -> None:
    """Promote a report JSON to a named baseline."""
    from eaiv.core.baseline import BaselineStore

    path = BaselineStore(root).save(report, name)
    click.echo(f"saved baseline {name!r} -> {path}")


@baseline.command("list")
@click.option("--dir", "root", default="baselines", type=click.Path(), help="Baseline directory.")
def baseline_list(root: str) -> None:
    """List stored baselines."""
    from eaiv.core.baseline import BaselineStore

    infos = BaselineStore(root).list()
    if not infos:
        click.echo(f"no baselines in {root}")
        return
    for b in infos:
        flag = "PASS" if b.all_passed else "FAIL"
        click.echo(f"{b.name:<24} {b.saved_at:<26} {b.target:<12} eaiv={b.eaiv_version} {flag}")


@baseline.command("show")
@click.argument("name")
@click.option("--dir", "root", default="baselines", type=click.Path(), help="Baseline directory.")
def baseline_show(name: str, root: str) -> None:
    """Print a stored baseline payload."""
    from eaiv.core.baseline import BaselineStore

    click.echo(json.dumps(BaselineStore(root).load(name), indent=2))


@datasets.command("validate")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
def datasets_validate(paths: tuple[str, ...]) -> None:
    """Validate dataset CSVs against their metadata sidecars.

    PATHS are CSV files or directories (scanned recursively). Exits
    non-zero if any dataset is invalid.
    """
    from pathlib import Path

    from eaiv.datasets import validate_dataset

    csvs: list[Path] = []
    for raw in paths:
        p = Path(raw)
        csvs.extend(sorted(p.glob("**/*.csv")) if p.is_dir() else [p])

    problems: list[str] = []
    for csv_path in csvs:
        issues = validate_dataset(csv_path)
        problems.extend(issues)
        click.echo(f"{'FAIL' if issues else 'OK  '} {csv_path}")
    for issue in problems:
        click.echo(f"  {issue}")
    click.echo(f"validated {len(csvs)} dataset(s): {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


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
