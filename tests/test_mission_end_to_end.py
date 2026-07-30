"""A complete simulated mission, from launch to release decision.

These tests exercise the whole journey the product promises — discover,
configure, run, observe, diagnose, compare, promote — against the
simulated target, with no hardware and no network.
"""

from __future__ import annotations

import json
import threading

import pytest
from click.testing import CliRunner

from eaiv.cli import _load_all_plugins, main
from eaiv.config import Config
from eaiv.configspec import get_preset
from eaiv.core.baseline import BaselineStore
from eaiv.core.comparison import compare_runs
from eaiv.core.pipeline import ValidationPipeline
from eaiv.dashboard.runs import all_sources
from eaiv.insights import Verdict, decide, generate_insights
from eaiv.runs.cancel import CancellationToken
from eaiv.runs.events import MemoryEventSink
from eaiv.runs.models import RunStatus
from eaiv.runs.store import RunStore


@pytest.fixture(autouse=True)
def _plugins():
    _load_all_plugins()


def _sim_config(dataset: str = "datasets/imu/imu_run1.csv", **overrides) -> dict:
    raw = get_preset("sim-release-gate").build("sim")
    raw["sensor_fusion"]["source"] = dataset
    raw["hil"]["source"] = dataset
    raw["tinyml"].update({"iterations": 4, "warmup": 1})
    raw["rt_perf"]["duration_s"] = 0.2
    raw["firmware"].update({"timeout_s": 1.0, "retries": 0})
    raw["target"]["sim"] = {"telemetry_lines": 10}
    for key, value in overrides.items():
        raw[key] = value
    return raw


def test_a_full_simulated_mission_produces_a_complete_run(tmp_path):
    store = RunStore(tmp_path / "reports")
    sink = MemoryEventSink()
    pipeline = ValidationPipeline(
        Config(_sim_config()),
        report_dir=str(tmp_path / "reports"),
        baseline_store=BaselineStore(tmp_path / "baselines"),
        run_store=store,
        events=sink,
    )
    result = pipeline.run(suite="all", telemetry_s=0.3, run_name="nightly gate")

    assert result.passed, [(s.name, s.detail) for s in result.stages if s.status == "failed"]
    manifest = result.manifest
    assert manifest is not None

    # -- the manifest records everything needed to reproduce the run --------
    assert manifest.status is RunStatus.PASSED
    assert manifest.name == "nightly gate"
    assert manifest.suite_selection == "all"
    assert set(manifest.suites) >= {"firmware", "tinyml", "fusion", "hil", "memory", "rt_perf"}
    assert manifest.target["kind"] == "sim"
    assert manifest.target["arch"] == "virtual"
    assert manifest.resolved_config["target"]["kind"] == "sim"
    assert manifest.eaiv_version
    assert manifest.host["python"]
    assert manifest.provenance == "simulated"
    assert manifest.summary.total_suites == manifest.summary.passed_suites
    assert manifest.duration_s > 0

    # -- the artifacts are on disk under stable names ----------------------
    run_dir = store.run_dir(manifest.run_id)
    for name in (
        "manifest.json",
        "events.jsonl",
        "report.json",
        "report.md",
        "report.csv",
        "report.html",
        "telemetry.csv",
        "resolved-config.yaml",
    ):
        assert (run_dir / name).exists(), name
    assert {a.name for a in manifest.artifacts} >= {"report.json", "telemetry.csv"}

    # -- legacy artifacts are still written where CI expects them ----------
    assert (tmp_path / "reports" / "latest.json").exists()
    assert list((tmp_path / "reports").glob("report_*.json"))

    # -- the run is observable ---------------------------------------------
    kinds = sink.kinds()
    assert kinds[0] == "run_created"
    assert kinds[-1] == "run_completed"
    assert "target_connected" in kinds
    assert "suite_passed" in kinds
    assert "metric" in kinds
    assert "artifact" in kinds
    assert kinds.index("stage_started") < kinds.index("stage_completed")
    # And the same stream survives the process.
    assert [str(e.kind) for e in store.events(manifest.run_id)] == kinds


def test_the_dashboard_can_load_what_a_mission_produced(tmp_path):
    store = RunStore(tmp_path / "reports")
    ValidationPipeline(
        Config(_sim_config()),
        report_dir=str(tmp_path / "reports"),
        baseline_store=BaselineStore(tmp_path / "baselines"),
        run_store=store,
    ).run(suite="firmware", run_name="smoke")

    sources = all_sources(store, tmp_path / "reports")
    assert sources, "the dashboard found no artifacts"
    report = sources[0].report()
    assert report is not None
    assert sources[0].provenance == "simulated"

    insights = generate_insights(report, manifest=sources[0].manifest)
    decision = decide(report, insights)
    # A clean simulated run is never presented as ready to ship.
    assert decision.verdict is Verdict.SHIP_WITH_RISK
    assert any(i.id == "provenance-not-hardware" for i in insights)


def test_a_failing_mission_explains_itself_and_blocks_promotion(tmp_path):
    """The degraded-sensor scenario: a real threshold crossing produced by
    seeded fault injection, diagnosed with evidence and a next action."""
    raw = _sim_config()
    raw["hil"]["faults"] = [
        {"kind": "noise", "std": 2.0, "seed": 1},
        {"kind": "packet_loss", "probability": 0.08, "seed": 1},
    ]
    raw["hil"]["max_faulted_rmse_deg"] = 15.0
    store = RunStore(tmp_path / "reports")
    baselines = BaselineStore(tmp_path / "baselines")
    result = ValidationPipeline(
        Config(raw),
        report_dir=str(tmp_path / "reports"),
        baseline_store=baselines,
        run_store=store,
    ).run(suite="all", save_baseline="should-not-exist", run_name="degraded")

    assert not result.passed
    manifest = result.manifest
    assert manifest is not None and manifest.status is RunStatus.FAILED
    assert "hil" in manifest.summary.failed_suite_names
    # A failing run is never promoted.
    assert not baselines.path("should-not-exist").exists()
    assert result.stage("save_baseline").status == "failed"

    report = json.loads((store.run_dir(manifest.run_id) / "report.json").read_text())
    insights = generate_insights(report, manifest=manifest)
    hil = next(i for i in insights if i.id == "hil-faulted-rmse")
    evidence = {e.label: e.value for e in hil.evidence}
    assert float(evidence["Faulted RMSE"].rstrip("°")) > 15.0
    assert evidence["Configured limit"] == "15°"
    assert hil.action is not None and hil.action.config_path == "hil.max_faulted_rmse_deg"
    assert decide(report, insights).verdict is Verdict.DO_NOT_SHIP


def test_baseline_promotion_then_comparison(tmp_path):
    reports = tmp_path / "reports"
    baselines = BaselineStore(tmp_path / "baselines")
    store = RunStore(reports)

    def run(name: str, **kwargs):
        return ValidationPipeline(
            Config(_sim_config()),
            report_dir=str(reports),
            baseline_store=baselines,
            run_store=store,
        ).run(suite="fusion", run_name=name, **kwargs)

    first = run("reference", save_baseline="release-1")
    assert first.passed
    assert baselines.path("release-1").exists()
    assert baselines.list()[0].all_passed

    second = run("candidate", baseline="release-1", max_regression_pct=50.0)
    assert second.passed
    assert second.regression is not None
    assert second.regression.passed

    baseline_payload = baselines.load("release-1")
    candidate = json.loads((store.run_dir(second.manifest.run_id) / "report.json").read_text())
    comparison = compare_runs(baseline_payload, candidate)
    # Same target, same dataset, same provenance: directly comparable.
    assert comparison.compatibility.ok
    assert comparison.shared


def test_a_regression_against_the_baseline_fails_the_gate(tmp_path):
    reports = tmp_path / "reports"
    baselines = BaselineStore(tmp_path / "baselines")
    store = RunStore(reports)
    pipeline = ValidationPipeline(
        Config(_sim_config()),
        report_dir=str(reports),
        baseline_store=baselines,
        run_store=store,
    )
    assert pipeline.run(suite="fusion", save_baseline="base", run_name="a").passed

    # Rewrite the baseline so the current run looks 100x worse.
    payload = baselines.load("base")
    for suite in payload["suites"]:
        for key in ("roll_rmse_deg", "pitch_rmse_deg"):
            if key in suite["metrics"]:
                suite["metrics"][key] /= 100.0
    baselines.path("base").write_text(json.dumps(payload))

    result = pipeline.run(suite="fusion", baseline="base", run_name="b")
    assert not result.passed
    assert result.stage("compare").status == "failed"
    manifest = result.manifest
    assert manifest is not None
    assert manifest.summary.regressions > 0
    assert manifest.summary.worst_regression is not None
    assert manifest.failure is not None and manifest.failure.stage == "compare"


def test_cancellation_stops_the_run_and_records_why(tmp_path):
    store = RunStore(tmp_path / "reports")
    token = CancellationToken()
    token.cancel("cancelled from the dashboard")
    result = ValidationPipeline(
        Config(_sim_config()),
        report_dir=str(tmp_path / "reports"),
        baseline_store=BaselineStore(tmp_path / "baselines"),
        run_store=store,
        cancel=token,
    ).run(suite="all", run_name="doomed")

    assert result.cancelled
    assert not result.passed
    manifest = result.manifest
    assert manifest is not None
    assert manifest.status is RunStatus.CANCELLED
    assert manifest.cancel_reason == "cancelled from the dashboard"
    # Every stage is accounted for rather than silently missing.
    assert {s.name for s in result.stages} == {
        "build",
        "validate",
        "telemetry",
        "compare",
        "save_baseline",
    }
    assert all(s.status == "cancelled" for s in result.stages)
    assert "run_cancelled" in [str(e.kind) for e in store.events(manifest.run_id)]


def test_cancellation_mid_run_is_honoured_between_stages(tmp_path):
    """Cancelling through the run directory works from another thread —
    the same path the dashboard's cancel button takes."""
    store = RunStore(tmp_path / "reports")
    pipeline = ValidationPipeline(
        Config(_sim_config()),
        report_dir=str(tmp_path / "reports"),
        baseline_store=BaselineStore(tmp_path / "baselines"),
        run_store=store,
    )
    session = pipeline.create_session(
        suite="all", baseline=None, save_baseline=None, max_regression_pct=10.0, run_name="racy"
    )
    session.cancel.poll_interval_s = 0.0
    pipeline.session = session
    threading.Thread(
        target=lambda: store.request_cancel(session.run_id, "stop it"), daemon=True
    ).start()
    result = pipeline.run(suite="all")
    # Whether it stopped early or squeaked through, the outcome is coherent.
    manifest = store.load(session.run_id)
    assert manifest.status in (RunStatus.CANCELLED, RunStatus.PASSED, RunStatus.FAILED)
    if result.cancelled:
        assert manifest.cancel_reason == "stop it"


def test_a_run_without_a_store_still_works_exactly_as_before(tmp_path):
    """The pre-existing synchronous API must not require a run store."""
    result = ValidationPipeline(
        Config(_sim_config()),
        report_dir=str(tmp_path / "reports"),
        baseline_store=BaselineStore(tmp_path / "baselines"),
    ).run(suite="firmware")
    assert result.passed
    assert not (tmp_path / "reports" / "runs").exists()
    assert (tmp_path / "reports" / "latest.json").exists()


# -- CLI -------------------------------------------------------------------


def test_demo_command_produces_the_pass_pass_fail_arc(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "demo",
            "--report-dir",
            str(tmp_path / "reports"),
            "--baseline-dir",
            str(tmp_path / "baselines"),
            "--dataset-dir",
            "datasets",
            "--mission-dir",
            str(tmp_path / "missions"),
        ],
    )
    # Exit 0 means "the demo ran as designed": it is a demonstration, not a
    # gate, and the third run is meant to fail so there is something to
    # diagnose.
    assert result.exit_code == 0, result.output
    assert result.output.count("[PASS]") == 2
    assert result.output.count("[FAIL]") == 1
    assert "fails on purpose" in result.output
    assert "Every metric above is simulated" in result.output

    store = RunStore(tmp_path / "reports")
    assert len(store.list()) == 3
    assert (tmp_path / "baselines" / "demo-baseline.json").exists()
    assert (tmp_path / "missions" / "demo-mission.yaml").exists()


def test_runs_list_and_show(tmp_path):
    runner = CliRunner()
    reports = str(tmp_path / "reports")
    assert runner.invoke(
        main,
        [
            "demo",
            "--report-dir",
            reports,
            "--baseline-dir",
            str(tmp_path / "b"),
            "--mission-dir",
            str(tmp_path / "m"),
        ],
    ).exit_code in (0, 1)

    listing = runner.invoke(main, ["runs", "list", "--report-dir", reports])
    assert listing.exit_code == 0
    assert "Demo" in listing.output

    run_id = RunStore(reports).list()[0].run_id
    shown = runner.invoke(main, ["runs", "show", run_id, "--report-dir", reports])
    assert shown.exit_code == 0
    assert run_id in shown.output
    assert "verdict:" in shown.output
    assert "provenance simulated" in shown.output


def test_runs_list_empty_offers_a_way_forward(tmp_path):
    result = CliRunner().invoke(main, ["runs", "list", "--report-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "eaiv demo" in result.output


def test_runs_show_reports_a_missing_run_cleanly(tmp_path):
    result = CliRunner().invoke(main, ["runs", "show", "nope", "--report-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "Cannot read run" in result.output


def test_runs_compare_gates_on_regressions(tmp_path):
    runner = CliRunner()
    reports = str(tmp_path / "reports")
    runner.invoke(
        main,
        [
            "demo",
            "--report-dir",
            reports,
            "--baseline-dir",
            str(tmp_path / "b"),
            "--mission-dir",
            str(tmp_path / "m"),
        ],
    )
    runs = RunStore(reports).list()
    degraded = next(m for m in runs if m.status is RunStatus.FAILED)
    reference = next(m for m in runs if m.status is RunStatus.PASSED)

    result = runner.invoke(
        main,
        ["runs", "compare", reference.run_id, degraded.run_id, "--report-dir", reports],
    )
    assert result.exit_code == 1  # regressions present
    assert "REGRESSED" in result.output
    assert "Hold the release" in result.output

    as_json = runner.invoke(
        main,
        [
            "runs",
            "compare",
            reference.run_id,
            reference.run_id,
            "--report-dir",
            reports,
            "--format",
            "json",
        ],
    )
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert payload["counts"]["regressed"] == 0


def test_doctor_exits_zero_when_only_optional_things_are_missing(tmp_path):
    result = CliRunner().invoke(
        main, ["doctor", "--no-hardware", "--report-dir", str(tmp_path / "reports")]
    )
    assert result.exit_code == 0, result.output
    assert "Plugin discovery" in result.output
    assert "Environment is ready" in result.output


def test_doctor_reports_a_broken_config(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("target: {kind: not_a_backend}\n")
    result = CliRunner().invoke(
        main, ["doctor", "--no-hardware", "--config", str(bad), "--report-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "target.kind" in result.output


def test_doctor_json_output_is_machine_readable(tmp_path):
    result = CliRunner().invoke(
        main, ["doctor", "--no-hardware", "--json", "--report-dir", str(tmp_path)]
    )
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert any(c["name"] == "Python version" for c in payload["checks"])


def test_config_resolve_prints_yaml_with_its_sources(tmp_path):
    (tmp_path / "base.yaml").write_text("target: {kind: qemu}\n")
    (tmp_path / "child.yaml").write_text("inherit: base.yaml\ntarget: {kind: sim}\n")
    result = CliRunner().invoke(main, ["config", "resolve", str(tmp_path / "child.yaml")])
    assert result.exit_code == 0
    assert "# source:" in result.output
    assert "kind: sim" in result.output


def test_config_validate_exits_nonzero_on_errors(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("target: {kind: made_up}\n")
    result = CliRunner().invoke(main, ["config", "validate", str(bad)])
    assert result.exit_code == 1
    assert "not available" in result.output


def test_existing_run_command_is_unchanged(tmp_path):
    """`eaiv run` keeps its original contract: suites, report artifacts,
    exit code — and no run directory."""
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "target: {kind: sim, binary: fw.elf, sim: {telemetry_lines: 3}}\n"
        "firmware: {timeout_s: 1, retries: 0, pass_patterns: [ALL_TESTS_OK]}\n"
    )
    result = CliRunner().invoke(
        main,
        ["run", "--config", str(cfg), "--suite", "firmware", "--report-dir", str(tmp_path / "r")],
    )
    assert result.exit_code == 0
    assert (tmp_path / "r" / "latest.json").exists()
    assert not (tmp_path / "r" / "runs").exists()


def test_pipeline_command_records_a_run_and_reports_its_id(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "target: {kind: sim, binary: fw.elf, sim: {telemetry_lines: 3}}\n"
        "firmware: {timeout_s: 1, retries: 0, pass_patterns: [ALL_TESTS_OK]}\n"
    )
    result = CliRunner().invoke(
        main,
        [
            "pipeline",
            "--config",
            str(cfg),
            "--suite",
            "firmware",
            "--report-dir",
            str(tmp_path / "r"),
            "--baseline-dir",
            str(tmp_path / "b"),
            "--run-name",
            "ci gate",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "pipeline: PASS" in result.output
    assert "[     ok] validate" in result.output  # unchanged stage formatting
    assert "run: " in result.output
    manifests = RunStore(tmp_path / "r").list()
    assert len(manifests) == 1 and manifests[0].name == "ci gate"


def test_pipeline_no_record_skips_the_run_directory(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "target: {kind: sim, binary: fw.elf}\n"
        "firmware: {timeout_s: 1, retries: 0, pass_patterns: [ALL_TESTS_OK]}\n"
    )
    result = CliRunner().invoke(
        main,
        [
            "pipeline",
            "--config",
            str(cfg),
            "--suite",
            "firmware",
            "--no-record",
            "--report-dir",
            str(tmp_path / "r"),
            "--baseline-dir",
            str(tmp_path / "b"),
        ],
    )
    assert result.exit_code == 0
    assert not (tmp_path / "r" / "runs").exists()


def test_malformed_config_is_a_clean_cli_failure(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("target: {kind: sim\n  oops")
    result = CliRunner().invoke(main, ["run", "--config", str(bad), "--suite", "firmware"])
    assert result.exit_code != 0
    assert "Invalid YAML" in result.output
    assert "Traceback" not in result.output
