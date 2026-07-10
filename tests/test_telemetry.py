"""Tests for the telemetry protocol parser, adapter, and collector."""

from __future__ import annotations

from click.testing import CliRunner

from eaiv.cli import main
from eaiv.targets import build_target
from eaiv.telemetry import (
    BenchRecord,
    BootRecord,
    TelemetryCollector,
    TelemetryRecord,
    VerdictRecord,
    build_adapter,
    parse_line,
)


def test_parse_boot_line():
    r = parse_line("BOOT eaiv-fw board=esp32 cpu_hz=240000000 heap=294976")
    assert isinstance(r, BootRecord)
    assert r.firmware == "eaiv-fw"
    assert r.board == "esp32"
    assert r.fields["cpu_hz"] == "240000000"


def test_parse_telemetry_line():
    r = parse_line("T t=0.0100 gx=0.18850 az=1.00000 roll=0.135")
    assert isinstance(r, TelemetryRecord)
    assert r.t_s == 0.01
    assert r.values == {"gx": 0.1885, "az": 1.0, "roll": 0.135}


def test_parse_bench_and_verdict_lines():
    b = parse_line("B iters=1000 us_per_update=3.412 max_us=18")
    assert isinstance(b, BenchRecord)
    assert b.values["iters"] == 1000

    ok = parse_line("ALL_TESTS_OK")
    assert isinstance(ok, VerdictRecord) and ok.passed

    fail = parse_line("FAIL self-test-clock")
    assert isinstance(fail, VerdictRecord) and not fail.passed
    assert fail.reason == "self-test-clock"


def test_parser_tolerates_garbage():
    assert parse_line("") is None
    assert parse_line("ets Jul 29 2019 12:21:46") is None  # ESP32 boot ROM noise
    assert parse_line("T gx=1.0") is None  # missing timestamp
    assert parse_line("random text with = signs a=b") is None


def test_adapter_buffers_partial_lines():
    adapter = build_adapter()
    first = list(adapter.feed("T t=0.01 gx=1.0\nT t=0.02 g"))
    assert len(first) == 1
    second = list(adapter.feed("x=2.0\n"))
    assert len(second) == 1
    assert isinstance(second[0], TelemetryRecord)
    assert second[0].values["gx"] == 2.0


def test_collector_end_to_end_with_simulated_target():
    target = build_target({"kind": "sim", "sim": {"telemetry_lines": 20}})
    target.flash("fake.elf")
    collector = TelemetryCollector()
    collector.collect(target, duration_s=0.1)

    assert len(collector.boots) == 1
    assert len(collector.telemetry) == 20
    assert collector.verdict is not None and collector.verdict.passed

    stats = collector.summary()
    assert stats.samples == 20
    assert stats.rate_hz > 0
    assert "az" in stats.fields
    assert 0.9 < stats.fields["az"]["mean"] <= 1.01


def test_collector_csv_export(tmp_path):
    collector = TelemetryCollector()
    collector.feed("T t=0.0 gx=1.0 az=0.5\nT t=0.1 gx=2.0\n")
    path = collector.to_csv(tmp_path / "telemetry.csv")
    lines = path.read_text().strip().splitlines()
    assert lines[0] == "t_s,az,gx"
    assert lines[1] == "0.0,0.5,1.0"
    assert lines[2] == "0.1,,2.0"  # missing fields stay blank, column set is stable


def test_monitor_cli_summary_and_csv(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("target:\n  kind: sim\n  binary: fw.elf\n  sim: {telemetry_lines: 10}\n")
    out = tmp_path / "t.csv"
    runner = CliRunner()
    result = runner.invoke(main, ["monitor", "--config", str(cfg), "--summary", "--csv", str(out)])
    assert result.exit_code == 0, result.output
    assert "samples=10" in result.output
    assert "verdict: PASS" in result.output
    assert out.exists()


def test_parse_stat_lines():
    from eaiv.telemetry import StatRecord

    m = parse_line("M heap=294976")
    assert isinstance(m, StatRecord) and m.kind == "mem"
    assert m.values["heap"] == 294976

    u = parse_line("U boot_ms=612")
    assert isinstance(u, StatRecord) and u.kind == "uptime"
    assert u.values["boot_ms"] == 612


def test_simulated_target_emits_boot_stats():
    target = build_target({"kind": "sim", "sim": {"telemetry_lines": 1}})
    target.flash("fw.elf")
    collector = TelemetryCollector()
    collector.collect(target, duration_s=0.1)
    kinds = {s.kind for s in collector.stats}
    assert kinds == {"mem", "uptime"}


def test_parse_status_line():
    from eaiv.telemetry import StatRecord

    r = parse_line("S heap=294976 uptime_ms=5210 cpu_hz=240000000 temp_c=41.3")
    assert isinstance(r, StatRecord) and r.kind == "status"
    assert r.values["temp_c"] == 41.3
    assert r.values["cpu_hz"] == 240000000


def test_live_provider_with_status_poll():
    from eaiv.telemetry import LiveTelemetryProvider

    target = build_target({"kind": "sim", "sim": {"telemetry_lines": 5}})
    target.flash("fw.elf")
    collector = TelemetryCollector()
    collector.ingest(LiveTelemetryProvider(target, duration_s=0.1, poll_status=True))
    assert len(collector.telemetry) == 5
    status = [s for s in collector.stats if s.kind == "status"]
    assert status and status[0].values["temp_c"] == 42.0


def test_replay_provider_reads_dataset():
    from eaiv.telemetry import ReplayTelemetryProvider

    collector = TelemetryCollector()
    collector.ingest(ReplayTelemetryProvider("datasets/imu/imu_run1.csv"))
    assert len(collector.telemetry) == 2000
    assert "gx" in collector.telemetry[0].values


def test_simulated_provider_is_deterministic():
    from eaiv.telemetry import SimulatedTelemetryProvider

    a = list(SimulatedTelemetryProvider(duration_s=0.2, seed=3).records())
    b = list(SimulatedTelemetryProvider(duration_s=0.2, seed=3).records())
    assert a == b
    assert len(a) == 20
