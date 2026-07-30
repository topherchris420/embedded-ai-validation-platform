"""Command-line entry point.

Command groups:
    run       — execute validation suites against a target
    pipeline  — build, validate, capture telemetry, gate, promote — as one run
    runs      — list, inspect, and compare recorded validation runs
    config    — validate and resolve configuration files
    doctor    — diagnose the environment and say how to fix it
    demo      — produce a complete simulated validation history
    dashboard — launch EAIV Mission Control
    show      — print the resolved configuration
    plugins   — list registered plugins (targets, filters, faults, ...)
    targets   — shorthand for ``plugins --type target``
    flash     — flash a firmware binary to the configured target
    monitor   — stream serial output from the configured target
    datasets  — dataset tools (generate synthetic replay logs)
    baseline  — manage named baselines
    compare   — regression-gate two report JSON artifacts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from eaiv.config import ConfigError, load_config
from eaiv.core.orchestrator import Orchestrator


@click.group()
@click.version_option(package_name="eaiv")
def main() -> None:
    """eaiv — Embedded AI Validation Platform."""


def _load_config_or_fail(config_path: str) -> object:
    """Load a config, turning loader errors into clean CLI failures."""
    try:
        return load_config(config_path)
    except ConfigError as e:
        raise click.ClickException(str(e)) from None


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
    cfg = _load_config_or_fail(config_path)
    orch = Orchestrator(cfg, report_dir=report_dir)  # type: ignore[arg-type]
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
    """Import modules whose side effect is registering built-in plugins.

    Every built-in plugin type is imported here, not only the ones a given
    command happens to need: ``eaiv plugins``, ``eaiv doctor``, and the
    dashboard's inventory all answer "what can this installation do?", and
    that answer must not depend on which import ran first.
    """
    import eaiv.hil
    import eaiv.power
    import eaiv.sensor_fusion.fusion
    import eaiv.targets
    import eaiv.telemetry  # noqa: F401  (telemetry_adapter plugins)
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
@click.option("--run-name", default="", help="Human-readable name recorded in the run manifest.")
@click.option(
    "--record/--no-record",
    default=True,
    help="Record the run under <report-dir>/runs/ (manifest, events, artifacts).",
)
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
    run_name: str,
    record: bool,
) -> None:
    """Run the full validation pipeline: build, validate, telemetry, compare.

    Exit code 0 only if every stage, every suite, and the regression gate
    pass — designed as a single CI entry point. The run is recorded under
    ``<report-dir>/runs/<run-id>/`` so it survives the process and can be
    inspected later with ``eaiv runs show``.
    """
    from eaiv.core.baseline import BaselineStore
    from eaiv.core.pipeline import ValidationPipeline
    from eaiv.runs import RunStore

    _load_all_plugins()
    cfg = _load_config_or_fail(config_path)
    pipe = ValidationPipeline(
        cfg,  # type: ignore[arg-type]
        report_dir=report_dir,
        baseline_store=BaselineStore(baseline_dir),
        run_store=RunStore(report_dir) if record else None,
        config_path=config_path,
    )
    result = pipe.run(
        suite=suite,
        build_env=build_env,
        baseline=baseline_name,
        save_baseline=save_baseline,
        telemetry_s=telemetry_duration,
        max_regression_pct=max_regression_pct,
        run_name=run_name,
    )
    for stage in result.stages:
        click.echo(
            f"[{stage.status:>7}] {stage.name:<14} {stage.duration_s:>8.3f}s  {stage.detail}"
        )
    if result.manifest is not None and record:
        click.echo(f"run: {result.manifest.run_id}  ({Path(report_dir) / 'runs'})")
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


# -- runs ------------------------------------------------------------------


@main.group()
def runs() -> None:
    """List, inspect, and compare recorded validation runs."""


@runs.command("list")
@click.option("--report-dir", default="reports", type=click.Path())
@click.option("--limit", default=20, help="Maximum runs to show.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def runs_list(report_dir: str, limit: int, as_json: bool) -> None:
    """List recorded runs, newest first."""
    from eaiv.runs import RunStore

    store = RunStore(report_dir)
    manifests = store.list(limit=limit)
    if as_json:
        click.echo(json.dumps([m.to_dict() for m in manifests], indent=2, default=str))
        return
    if not manifests:
        click.echo(f"no recorded runs in {Path(report_dir) / 'runs'}")
        click.echo("Run one with: eaiv pipeline --config configs/sim.yaml  (or: eaiv demo)")
        return
    click.echo(f"{'RUN ID':<44} {'STATUS':<12} {'TARGET':<10} {'SUITES':<8} NAME")
    for m in manifests:
        suites = f"{m.summary.passed_suites}/{m.summary.total_suites}"
        click.echo(f"{m.run_id:<44} {m.status!s:<12} {m.target_label:<10} {suites:<8} {m.name}")


@runs.command("show")
@click.argument("run_id")
@click.option("--report-dir", default="reports", type=click.Path())
@click.option("--logs", is_flag=True, help="Include the run's event log.")
@click.option("--json", "as_json", is_flag=True, help="Emit the manifest as JSON.")
def runs_show(run_id: str, report_dir: str, logs: bool, as_json: bool) -> None:
    """Show one run: status, stages, artifacts, and its diagnosis."""
    from eaiv.insights import decide, generate_insights
    from eaiv.runs import RunStore

    store = RunStore(report_dir)
    try:
        manifest = store.load(run_id)
    except (OSError, ValueError) as e:
        raise click.ClickException(f"Cannot read run {run_id!r}: {e}") from None

    if as_json:
        click.echo(json.dumps(manifest.to_dict(), indent=2, default=str))
        return

    click.echo(f"run        {manifest.run_id}")
    click.echo(f"name       {manifest.name}")
    click.echo(f"status     {manifest.status.label}")
    click.echo(f"target     {manifest.target_label} ({manifest.target.get('kind', '?')})")
    click.echo(f"suites     {manifest.suite_selection} -> {', '.join(manifest.suites) or '—'}")
    click.echo(f"started    {manifest.started_at or '—'}")
    click.echo(f"duration   {manifest.duration_s:.3f}s")
    click.echo(f"provenance {manifest.provenance}")
    if manifest.git.get("short_commit"):
        dirty = " (dirty)" if manifest.git.get("dirty") else ""
        click.echo(
            f"git        {manifest.git['short_commit']} on {manifest.git.get('branch')}{dirty}"
        )
    click.echo("")
    for stage in manifest.stages:
        click.echo(
            f"[{stage.status!s:>9}] {stage.name:<14} {stage.duration_s:>8.3f}s  {stage.detail}"
        )
    if manifest.artifacts:
        click.echo("\nartifacts:")
        for artifact in manifest.artifacts:
            click.echo(f"  {artifact.name:<24} {artifact.path} ({artifact.size_bytes} bytes)")

    report_path = store.run_dir(run_id) / "report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Run report is not valid JSON: {e}") from None
        insights = generate_insights(report, manifest=manifest, baseline_name=manifest.baseline)
        decision = decide(report, insights)
        click.echo(f"\nverdict: {decision.verdict.short} — {decision.headline}")
        for insight in insights[:5]:
            click.echo(f"  [{insight.severity!s:>13}] {insight.title}")
            if insight.action is not None:
                click.echo(f"       -> {insight.action.summary}")

    if logs:
        click.echo("\nevents:")
        for event in store.events(run_id):
            click.echo(f"  {event.timestamp} [{event.kind}] {event.stage or '-'}: {event.message}")


@runs.command("compare")
@click.argument("baseline_run")
@click.argument("current_run")
@click.option("--report-dir", default="reports", type=click.Path())
@click.option("--max-regression-pct", default=10.0)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["text", "markdown", "json"]),
    default="text",
)
def runs_compare(
    baseline_run: str, current_run: str, report_dir: str, max_regression_pct: float, fmt: str
) -> None:
    """Compare two recorded runs and exit non-zero on gated regressions."""
    from eaiv.core.comparison import compare_runs, to_json, to_markdown
    from eaiv.runs import RunStore

    store = RunStore(report_dir)

    def _load(run_id: str) -> dict[str, object]:
        path = store.run_dir(run_id) / "report.json"
        if not path.exists():
            raise click.ClickException(f"Run {run_id!r} has no report.json (did it finish?)")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Run {run_id!r} has an unreadable report: {e}") from None
        if not isinstance(payload, dict):
            raise click.ClickException(f"Run {run_id!r} report is not a JSON object")
        return payload

    comparison = compare_runs(
        _load(baseline_run),
        _load(current_run),
        max_regression_pct=max_regression_pct,
        baseline_label=baseline_run,
        current_label=current_run,
    )
    if fmt == "markdown":
        click.echo(to_markdown(comparison))
    elif fmt == "json":
        click.echo(to_json(comparison))
    else:
        click.echo(f"compatibility: {comparison.compatibility.level.label}")
        for issue in comparison.compatibility.issues:
            click.echo(f"  ! {issue.field}: {issue.baseline} -> {issue.current}")
            click.echo(f"    {issue.explanation}")
        counts = comparison.counts
        click.echo(
            f"regressed={counts['regressed']} improved={counts['improved']} "
            f"unchanged={counts['unchanged']} new={counts['added']} missing={counts['removed']}"
        )
        for change in comparison.regressions:
            click.echo(
                f"  [REGRESSED] {change.suite}.{change.metric}: "
                f"{change.baseline:g} -> {change.current:g} ({change.change_pct:+.2f}%)"
            )
        click.echo(f"\n{comparison.recommendation}")
    sys.exit(1 if comparison.regressions or not comparison.compatibility.ok else 0)


# -- config ----------------------------------------------------------------


@main.group("config")
def config_group() -> None:
    """Inspect and validate configuration files."""


@config_group.command("validate")
@click.argument("config_path", type=click.Path(exists=True))
@click.option("--suite", default="all", help="Validate only what this suite needs.")
@click.option("--no-paths", is_flag=True, help="Skip filesystem checks on path fields.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def config_validate(config_path: str, suite: str, no_paths: bool, as_json: bool) -> None:
    """Validate a configuration file field by field."""
    from eaiv.configspec import validate_for_suite

    _load_all_plugins()
    cfg = _load_config_or_fail(config_path)
    result = validate_for_suite(cfg.raw, suite, check_paths=not no_paths)  # type: ignore[attr-defined]

    if as_json:
        click.echo(
            json.dumps(
                {
                    "ok": result.ok,
                    "issues": [
                        {
                            "path": i.path,
                            "severity": str(i.severity),
                            "message": i.message,
                            "hint": i.hint,
                        }
                        for i in result.issues
                    ],
                },
                indent=2,
            )
        )
        sys.exit(0 if result.ok else 1)

    for issue in result.issues:
        click.echo(str(issue))
    click.echo(f"{config_path}: {len(result.errors)} error(s), {len(result.warnings)} warning(s)")
    sys.exit(0 if result.ok else 1)


@config_group.command("resolve")
@click.argument("config_path", type=click.Path(exists=True))
@click.option(
    "--format", "fmt", type=click.Choice(["yaml", "json"]), default="yaml", help="Output format."
)
@click.option("--output", "-o", default=None, type=click.Path(), help="Write to a file.")
def config_resolve(config_path: str, fmt: str, output: str | None) -> None:
    """Print the configuration after ``inherit:`` merging."""
    cfg = _load_config_or_fail(config_path)
    text = (
        json.dumps(cfg.raw, indent=2)  # type: ignore[attr-defined]
        if fmt == "json"
        else cfg.to_yaml()  # type: ignore[attr-defined]
    )
    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.echo(f"wrote resolved configuration to {output}")
        return
    for source in cfg.sources:  # type: ignore[attr-defined]
        click.echo(f"# source: {source}")
    click.echo(text)


@config_group.command("presets")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def config_presets(as_json: bool) -> None:
    """List the built-in mission presets."""
    from eaiv.configspec import PRESETS

    if as_json:
        click.echo(
            json.dumps(
                [
                    {
                        "id": p.id,
                        "title": p.title,
                        "summary": p.summary,
                        "suite": p.suite,
                        "target_kind": p.target_kind,
                        "requires_hardware": p.requires_hardware,
                    }
                    for p in PRESETS
                ],
                indent=2,
            )
        )
        return
    for preset in PRESETS:
        hardware = "hardware" if preset.requires_hardware else "no hardware"
        click.echo(f"{preset.id:<20} {preset.suite:<9} {hardware:<12} {preset.title}")
        click.echo(f"{'':<20} {preset.summary}")


# -- doctor ----------------------------------------------------------------


@main.command()
@click.option(
    "--config", "config_path", default=None, type=click.Path(), help="Also validate this config."
)
@click.option("--report-dir", default="reports", type=click.Path())
@click.option("--dataset-dir", default="datasets", type=click.Path())
@click.option("--no-hardware", is_flag=True, help="Skip probes that enumerate hardware.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def doctor(
    config_path: str | None,
    report_dir: str,
    dataset_dir: str,
    no_hardware: bool,
    as_json: bool,
) -> None:
    """Diagnose the environment and report actionable fixes.

    Exit code 0 when everything required works (warnings are fine), 1 when
    something is broken.
    """
    from eaiv.diagnostics import run_diagnostics

    diagnosis = run_diagnostics(
        config_path=config_path,
        report_dir=report_dir,
        dataset_dir=dataset_dir,
        include_hardware=not no_hardware,
    )
    if as_json:
        click.echo(json.dumps(diagnosis.to_dict(), indent=2))
        sys.exit(diagnosis.exit_code)

    for category, checks in diagnosis.by_category().items():
        click.echo(f"\n{category.upper()}")
        for check in checks:
            click.echo(f"  [{check.status.label:>4}] {check.name:<36} {check.detail}")
            if check.fix:
                click.echo(f"         fix: {check.fix}")
    click.echo(
        f"\n{len(diagnosis.checks)} check(s): {len(diagnosis.failures)} failure(s), "
        f"{len(diagnosis.warnings)} warning(s)"
    )
    if diagnosis.ok:
        click.echo("Environment is ready. Try: eaiv demo")
    sys.exit(diagnosis.exit_code)


# -- demo ------------------------------------------------------------------


@main.command()
@click.option("--report-dir", default="reports", type=click.Path())
@click.option("--baseline-dir", default="baselines", type=click.Path())
@click.option("--dataset-dir", default="datasets", type=click.Path())
@click.option("--mission-dir", default="missions", type=click.Path())
def demo(report_dir: str, baseline_dir: str, dataset_dir: str, mission_dir: str) -> None:
    """Produce a complete simulated validation history — no hardware needed.

    Runs three real validations against the simulated target: a reference
    run promoted to a baseline, a candidate gated against it, and a run
    whose sensor stream is degraded until the fusion filter genuinely
    leaves its error envelope. Every metric is labelled as simulated.
    """
    from eaiv.diagnostics import run_demo

    _load_all_plugins()
    click.echo("Running three simulated validations (no hardware required)...")
    result = run_demo(
        report_dir=report_dir,
        baseline_dir=baseline_dir,
        dataset_dir=dataset_dir,
        mission_dir=mission_dir,
    )
    click.echo("")
    for run_info in result.runs:
        verdict = "PASS" if run_info.passed else "FAIL"
        click.echo(f"[{verdict}] {run_info.name:<28} {run_info.run_id}")
        click.echo(f"         {run_info.summary}")
    click.echo(f"\nbaseline saved: {result.baseline}")
    if result.mission_path:
        click.echo(f"mission saved:  {result.mission_path}")
    click.echo(f"reports:        {Path(report_dir) / 'runs'}")
    click.echo(
        "\nThe third run fails on purpose: its sensor stream is degraded until the fusion "
        "filter genuinely leaves its error envelope, so there is a real failure to diagnose."
    )
    click.echo("Every metric above is simulated — none of it was measured on hardware.")
    click.echo("Next: eaiv dashboard      (or: eaiv runs list)")
    # Exit 0 means "the demo ran as designed" — this is a demonstration,
    # not a release gate, so the intentional third failure is a success.
    sys.exit(0 if result.ok else 1)


# -- dashboard -------------------------------------------------------------


@main.command()
@click.option("--report-dir", default="reports", type=click.Path())
@click.option("--baseline-dir", default="baselines", type=click.Path())
@click.option("--mission-dir", default="missions", type=click.Path())
@click.option("--port", default=8501, help="Port to serve on.")
@click.option("--address", default="localhost", help="Address to bind.")
@click.option("--headless", is_flag=True, help="Do not open a browser.")
def dashboard(
    report_dir: str,
    baseline_dir: str,
    mission_dir: str,
    port: int,
    address: str,
    headless: bool,
) -> None:
    """Launch EAIV Mission Control (the Streamlit dashboard)."""
    import os
    import subprocess

    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise click.ClickException(
            'The dashboard needs the optional extras: pip install -e ".[dashboard]"'
        ) from None

    from eaiv.dashboard.ui import app as app_module

    app_path = Path(app_module.__file__).resolve()
    env = dict(os.environ)
    env.update(
        {
            "EAIV_REPORT_DIR": str(report_dir),
            "EAIV_BASELINE_DIR": str(baseline_dir),
            "EAIV_MISSION_DIR": str(mission_dir),
            # Streamlit's default accent is red, which on a validation
            # console reads as "failure". Set the instrument accent so the
            # theme matches regardless of the working directory.
            "STREAMLIT_THEME_PRIMARY_COLOR": env.get("STREAMLIT_THEME_PRIMARY_COLOR", "#2f6f9f"),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": env.get(
                "STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false"
            ),
        }
    )
    argv = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(int(port)),
        "--server.address",
        str(address),
        "--server.headless",
        "true" if headless else "false",
    ]
    click.echo(f"Starting EAIV Mission Control on http://{address}:{port}")
    try:
        # Fixed argv built from validated options; no shell involved.
        completed = subprocess.run(argv, env=env, check=False)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        sys.exit(0)
    sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
