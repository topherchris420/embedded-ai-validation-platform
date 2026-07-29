"""Render the CLI command equivalent to a configured mission.

Showing the exact command before launching does two useful things: it
tells the engineer what the UI is about to do, and it gives them a line
they can paste into CI. The command is built from an argument list and
quoted with :func:`shlex.quote`, so it is copy-pasteable and never
concatenates unescaped user input.
"""

from __future__ import annotations

import shlex


def _quote(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) if p != "eaiv" else p for p in parts)


def preview_command(
    config_path: str,
    suite: str = "all",
    report_dir: str = "reports",
    baseline: str = "",
    save_baseline: str = "",
    telemetry_s: float = 0.0,
    max_regression_pct: float = 10.0,
    build_env: str = "",
    baseline_dir: str = "baselines",
    run_name: str = "",
) -> str:
    """The ``eaiv pipeline`` invocation matching a mission configuration."""
    parts = ["eaiv", "pipeline", "--config", config_path or "<config.yaml>"]
    if suite and suite != "all":
        parts += ["--suite", suite]
    if report_dir and report_dir != "reports":
        parts += ["--report-dir", report_dir]
    if build_env:
        parts += ["--build-env", build_env]
    if baseline:
        parts += ["--baseline", baseline]
    if save_baseline:
        parts += ["--save-baseline", save_baseline]
    if baseline and baseline_dir and baseline_dir != "baselines":
        parts += ["--baseline-dir", baseline_dir]
    if telemetry_s > 0:
        parts += ["--telemetry-duration", f"{telemetry_s:g}"]
    if baseline and max_regression_pct != 10.0:
        parts += ["--max-regression-pct", f"{max_regression_pct:g}"]
    if run_name:
        parts += ["--run-name", run_name]
    return _quote(parts)


def run_command_preview(config_path: str, suite: str = "all", report_dir: str = "reports") -> str:
    """The simpler ``eaiv run`` invocation, for suite-only executions."""
    parts = ["eaiv", "run", "--config", config_path or "<config.yaml>", "--suite", suite]
    if report_dir and report_dir != "reports":
        parts += ["--report-dir", report_dir]
    return _quote(parts)


__all__ = ["preview_command", "run_command_preview"]
