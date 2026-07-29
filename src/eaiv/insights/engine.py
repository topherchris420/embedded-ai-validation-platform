"""Turn validation evidence into prioritized engineering information.

The engine is a set of small, independent rules over data the run already
recorded: suite verdicts, metric values, configured thresholds, and the
regression report. Nothing is generated, guessed, or phrased as certainty
it does not have — a rule that reasons rather than reads marks its output
``Confidence.INFERRED`` and says so in the text.

Because every rule is a pure function of ``(report, regression, manifest)``
it is possible to unit-test exactly why an insight appeared, which is the
whole point: an explanation a reviewer cannot audit is worse than no
explanation.
"""

from __future__ import annotations

from typing import Any

from eaiv.core.metrics import MetricProvenance, format_value
from eaiv.core.regression import RegressionReport
from eaiv.core.report_schema import metric_info, normalize_report, overall_provenance
from eaiv.insights.models import (
    Confidence,
    Evidence,
    InsightCategory,
    RecommendedAction,
    Severity,
    ValidationInsight,
    sort_insights,
)
from eaiv.runs.models import RunManifest, RunStatus

#: Below this fraction of a configured budget remaining, headroom is
#: called out as a risk rather than left implicit.
HEADROOM_WARNING_FRACTION = 0.10

#: Percentage change past which an improvement is worth reporting.
IMPROVEMENT_REPORT_PCT = 5.0


def _metrics(report: dict[str, Any], suite: str) -> dict[str, Any]:
    for entry in report.get("suites") or []:
        if isinstance(entry, dict) and entry.get("name") == suite:
            metrics = entry.get("metrics")
            return metrics if isinstance(metrics, dict) else {}
    return {}


def _numeric(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _suite_entry(report: dict[str, Any], suite: str) -> dict[str, Any] | None:
    for entry in report.get("suites") or []:
        if isinstance(entry, dict) and entry.get("name") == suite:
            return entry
    return None


def _threshold(report: dict[str, Any], key: str) -> float | None:
    thresholds = (report.get("meta") or {}).get("thresholds") or {}
    value = thresholds.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _provenance_of(report: dict[str, Any], suite: str, metric: str) -> str:
    info = metric_info(report, suite, metric)
    return "" if info.provenance is MetricProvenance.UNKNOWN else str(info.provenance)


# -- rules -----------------------------------------------------------------


#: Stage failures that merely restate a suite verdict or a gate result.
#: Each is diagnosed properly by a dedicated rule, so the generic
#: "stage X failed" insight is suppressed for them.
_EXPECTED_STAGE_FAILURES: dict[str, tuple[str, ...]] = {
    "validate": ("suites failed",),
    "compare": ("regression(s) vs",),
    "save_baseline": ("refusing to promote",),
}


def _is_expected_stage_failure(stage: str, message: str) -> bool:
    return any(marker in message for marker in _EXPECTED_STAGE_FAILURES.get(stage, ()))


def _execution_insights(manifest: RunManifest | None) -> list[ValidationInsight]:
    """Crashes, interruptions, cancellations, and stage-level failures."""
    if manifest is None:
        return []
    out: list[ValidationInsight] = []

    if manifest.status is RunStatus.INTERRUPTED:
        out.append(
            ValidationInsight(
                id="run-interrupted",
                severity=Severity.CRITICAL,
                category=InsightCategory.EXECUTION,
                title="The run was interrupted before it finished",
                impact=(
                    "Results are partial. Any suite after the interruption never executed, so "
                    "this run cannot be used as a release decision."
                ),
                evidence=(
                    Evidence("Status", manifest.status.label),
                    Evidence("Last heartbeat", manifest.heartbeat or "unknown"),
                    Evidence(
                        "Failure",
                        manifest.failure.message if manifest.failure else "process disappeared",
                    ),
                ),
                action=RecommendedAction(
                    summary="Re-run the mission; artifacts from the partial run are kept.",
                    command="eaiv runs show " + manifest.run_id,
                ),
                magnitude=100.0,
            )
        )
    elif manifest.status is RunStatus.CANCELLED:
        out.append(
            ValidationInsight(
                id="run-cancelled",
                severity=Severity.MEDIUM,
                category=InsightCategory.EXECUTION,
                title="The run was cancelled",
                impact="Only the stages that completed before cancellation produced results.",
                evidence=(
                    Evidence("Reason", manifest.cancel_reason or "cancelled by user"),
                    Evidence(
                        "Stages completed",
                        str(sum(1 for s in manifest.stages if s.status == "ok")),
                    ),
                ),
                action=RecommendedAction(summary="Re-run the mission when you are ready."),
            )
        )

    for stage in manifest.stages:
        if stage.status != "failed" or stage.failure is None:
            continue
        failure = stage.failure
        if _is_expected_stage_failure(stage.name, failure.message):
            # The stage "failed" because a suite or gate it aggregates
            # failed. That is already diagnosed in detail by the suite and
            # regression rules; repeating it here as a crash would bury
            # the real finding under a generic one.
            continue
        connection = failure.type in ("SerialException", "ConnectionError", "TimeoutError") or (
            "port" in failure.message.lower() or "connect" in failure.message.lower()
        )
        out.append(
            ValidationInsight(
                id=f"stage-failed-{stage.name}",
                severity=Severity.CRITICAL,
                category=InsightCategory.EXECUTION,
                title=(
                    f"Could not reach the target during '{stage.name}'"
                    if connection
                    else f"Stage '{stage.name}' failed: {failure.type}"
                ),
                impact=(
                    "Downstream stages ran without the data this stage was supposed to produce."
                    if stage.name in ("build", "validate")
                    else "This stage produced no result."
                ),
                evidence=(
                    Evidence("Exception", failure.type),
                    Evidence("Message", failure.message[:400]),
                    Evidence("Duration", f"{stage.duration_s:.3f} s"),
                ),
                action=RecommendedAction(
                    summary=failure.hint or "Inspect the stage log for the full traceback.",
                    command=f"eaiv runs show {manifest.run_id} --logs",
                ),
                magnitude=90.0,
            )
        )
    return out


def _report_integrity_insights(report: dict[str, Any]) -> list[ValidationInsight]:
    if report.get("suites"):
        return []
    return [
        ValidationInsight(
            id="report-empty",
            severity=Severity.CRITICAL,
            category=InsightCategory.EXECUTION,
            title="The report contains no suite results",
            impact="There is nothing to judge this build on.",
            evidence=(Evidence("Suites recorded", "0"),),
            action=RecommendedAction(
                summary="Check the suite selection and the configuration.",
                command="eaiv config validate <config>",
            ),
            magnitude=95.0,
        )
    ]


def _deadline_insights(report: dict[str, Any]) -> list[ValidationInsight]:
    """Real-time deadline misses — always release-blocking."""
    entry = _suite_entry(report, "rt_perf")
    if entry is None:
        return []
    metrics = entry.get("metrics") or {}
    out: list[ValidationInsight] = []
    for key, value in metrics.items():
        if not isinstance(value, dict):
            continue
        task = key
        misses = value.get("deadline_misses")
        overruns = value.get("budget_overruns")
        if isinstance(misses, int) and misses > 0:
            deadline = value.get("deadline_ms")
            observed = value.get("wcet_observed_ms")
            samples = value.get("samples", 0)
            out.append(
                ValidationInsight(
                    id=f"deadline-miss-{task}",
                    severity=Severity.CRITICAL,
                    category=InsightCategory.DEADLINE,
                    title=f"The {task} task exceeded its deadline in {misses} sample(s)",
                    impact=(
                        "A missed hard deadline is a functional failure, not a slow path: "
                        "the control loop produced its output too late to be used."
                    ),
                    evidence=(
                        Evidence("Deadline", f"{deadline} ms"),
                        Evidence("Worst observed execution", f"{observed} ms"),
                        Evidence("Misses", f"{misses} of {samples} executions"),
                    ),
                    action=RecommendedAction(
                        summary=(
                            f"Reduce work in {task} or raise its deadline if the system "
                            "genuinely tolerates it."
                        ),
                        config_path=f"rt_perf.task_set[{task}].deadline_ms",
                    ),
                    suite="rt_perf",
                    metrics=(f"{task}.deadline_misses", f"{task}.wcet_observed_ms"),
                    provenance=_provenance_of(report, "rt_perf", f"{task}.deadline_misses"),
                    magnitude=float(misses),
                )
            )
        elif isinstance(overruns, int) and overruns > 0:
            out.append(
                ValidationInsight(
                    id=f"wcet-overrun-{task}",
                    severity=Severity.MEDIUM,
                    category=InsightCategory.HEADROOM,
                    title=f"The {task} task exceeded its WCET budget {overruns} time(s)",
                    impact=(
                        "The deadline was still met, but the task is using more time than it "
                        "was budgeted — the margin absorbing future work is gone."
                    ),
                    evidence=(
                        Evidence("WCET budget", f"{value.get('wcet_budget_ms')} ms"),
                        Evidence("Worst observed", f"{value.get('wcet_observed_ms')} ms"),
                        Evidence("Overruns", f"{overruns} of {value.get('samples', 0)}"),
                    ),
                    action=RecommendedAction(
                        summary=f"Profile {task} or re-budget it deliberately.",
                        config_path=f"rt_perf.task_set[{task}].wcet_budget_ms",
                    ),
                    suite="rt_perf",
                    metrics=(f"{task}.budget_overruns",),
                    provenance=_provenance_of(report, "rt_perf", f"{task}.budget_overruns"),
                    magnitude=float(overruns),
                )
            )
    return out


def _budget_insights(report: dict[str, Any]) -> list[ValidationInsight]:
    """Memory budget violations and thin remaining headroom."""
    metrics = _metrics(report, "memory")
    if not metrics or metrics.get("skipped"):
        return []
    out: list[ValidationInsight] = []
    checks = (
        ("rom_kb", "memory.max_rom_kb", "Flash (ROM)", "memory.max_rom_kb"),
        ("ram_static_kb", "memory.max_ram_kb", "Static RAM", "memory.max_ram_kb"),
    )
    for metric, threshold_key, label, config_path in checks:
        used = _numeric(metrics, metric)
        budget = _threshold(report, threshold_key)
        if used is None or budget is None or budget <= 0:
            continue
        remaining = budget - used
        provenance = _provenance_of(report, "memory", metric)
        if remaining < 0:
            out.append(
                ValidationInsight(
                    id=f"budget-exceeded-{metric}",
                    severity=Severity.CRITICAL,
                    category=InsightCategory.BUDGET,
                    title=f"{label} is {abs(remaining):.1f} KB over its budget",
                    impact=(
                        "The image does not fit the budget this board was sized for; it will "
                        "either fail to link, fail to flash, or leave nothing for the heap."
                    ),
                    evidence=(
                        Evidence("Used", f"{used:.2f} KB"),
                        Evidence("Budget", f"{budget:.2f} KB"),
                        Evidence("Over by", f"{abs(remaining):.2f} KB"),
                    ),
                    action=RecommendedAction(
                        summary=(
                            "Cut the footprint (smaller model, fewer static buffers) or raise "
                            "the budget if the hardware really has the space."
                        ),
                        config_path=config_path,
                    ),
                    suite="memory",
                    metrics=(metric,),
                    confidence=Confidence.MEASURED,
                    provenance=provenance,
                    magnitude=abs(remaining),
                )
            )
        elif remaining < budget * HEADROOM_WARNING_FRACTION:
            out.append(
                ValidationInsight(
                    id=f"budget-headroom-{metric}",
                    severity=Severity.MEDIUM,
                    category=InsightCategory.HEADROOM,
                    title=f"{label} has only {remaining:.1f} KB of remaining budget",
                    impact=(
                        f"Less than {HEADROOM_WARNING_FRACTION:.0%} of the budget is left. The "
                        "next feature is likely to break the build rather than degrade it."
                    ),
                    evidence=(
                        Evidence("Used", f"{used:.2f} KB"),
                        Evidence("Budget", f"{budget:.2f} KB"),
                        Evidence("Remaining", f"{remaining:.2f} KB ({remaining / budget:.1%})"),
                    ),
                    action=RecommendedAction(
                        summary="Plan footprint work now, before the budget is spent.",
                        config_path=config_path,
                    ),
                    suite="memory",
                    metrics=(metric,),
                    confidence=Confidence.DERIVED,
                    provenance=provenance,
                    magnitude=budget - remaining,
                )
            )
    return out


def _regression_insights(
    report: dict[str, Any], regression: RegressionReport | None, baseline_name: str = ""
) -> list[ValidationInsight]:
    if regression is None:
        return []
    out: list[ValidationInsight] = []
    against = f" against {baseline_name!r}" if baseline_name else " against the baseline"
    for delta in sorted(regression.regressions, key=lambda d: -abs(d.change_pct))[:10]:
        info = metric_info(report, delta.suite, delta.metric)
        direction = "increased" if delta.change_pct > 0 else "decreased"
        out.append(
            ValidationInsight(
                id=f"regression-{delta.suite}-{delta.metric}",
                severity=Severity.HIGH,
                category=InsightCategory.REGRESSION,
                title=(
                    f"{delta.suite}.{delta.metric} {direction} "
                    f"{abs(delta.change_pct):.1f}%{against}"
                ),
                impact=((info.description + " ") if info.description else "")
                + f"This metric is {info.direction_label}, so the change is a regression.",
                evidence=(
                    Evidence("Baseline", format_value(delta.baseline, info)),
                    Evidence("This run", format_value(delta.current, info)),
                    Evidence("Change", f"{delta.change_pct:+.2f}%"),
                ),
                action=RecommendedAction(
                    summary=(
                        "Compare the two runs metric by metric, then bisect the change that "
                        "introduced it."
                    ),
                    command=(f"eaiv runs compare {baseline_name or '<baseline-id>'} <this-run-id>"),
                ),
                suite=delta.suite,
                metrics=(delta.metric,),
                confidence=Confidence.DERIVED,
                provenance=_provenance_of(report, delta.suite, delta.metric),
                magnitude=abs(delta.change_pct),
            )
        )
    return out


def _accuracy_insights(report: dict[str, Any]) -> list[ValidationInsight]:
    """Fusion accuracy and fault-robustness threshold failures."""
    out: list[ValidationInsight] = []

    fusion = _metrics(report, "fusion")
    limit = _threshold(report, "sensor_fusion.max_rmse_deg")
    for axis in ("roll", "pitch"):
        key = f"{axis}_rmse_deg"
        value = _numeric(fusion, key)
        if value is None or limit is None or value <= limit:
            continue
        out.append(
            ValidationInsight(
                id=f"fusion-rmse-{axis}",
                severity=Severity.HIGH,
                category=InsightCategory.ACCURACY,
                title=f"{axis.capitalize()} orientation RMSE crossed the configured {limit:g}° limit",
                impact=(
                    "The filter's orientation estimate is further from ground truth than the "
                    "project allows, so anything navigating on it inherits that error."
                ),
                evidence=(
                    Evidence("Observed RMSE", f"{value:.3f}°"),
                    Evidence("Configured limit", f"{limit:g}°"),
                    Evidence("Exceeded by", f"{value - limit:.3f}°"),
                    Evidence("Algorithm", str(fusion.get("algorithm", "?"))),
                    Evidence("Samples", str(fusion.get("samples", "?"))),
                ),
                action=RecommendedAction(
                    summary=(
                        "Tune the filter parameters or try another algorithm on the same "
                        "dataset; the Compare page shows both side by side."
                    ),
                    config_path="sensor_fusion.params",
                ),
                suite="fusion",
                metrics=(key,),
                provenance=_provenance_of(report, "fusion", key),
                magnitude=value - limit,
            )
        )

    hil = _metrics(report, "hil")
    hil_limit = _threshold(report, "hil.max_faulted_rmse_deg")
    faulted = _numeric(hil, "faulted_rmse_deg")
    clean = _numeric(hil, "clean_rmse_deg")
    if faulted is not None and hil_limit is not None and faulted > hil_limit:
        evidence = [
            Evidence("Faulted RMSE", f"{faulted:.3f}°"),
            Evidence("Configured limit", f"{hil_limit:g}°"),
        ]
        if clean is not None:
            evidence.append(Evidence("Clean-stream RMSE", f"{clean:.3f}°"))
            evidence.append(Evidence("Degradation caused by faults", f"{faulted - clean:.3f}°"))
        faults = hil.get("faults")
        if isinstance(faults, list) and faults:
            evidence.append(Evidence("Fault chain", ", ".join(str(f) for f in faults)))
        out.append(
            ValidationInsight(
                id="hil-faulted-rmse",
                severity=Severity.HIGH,
                category=InsightCategory.ROBUSTNESS,
                title=f"Fault-injected orientation RMSE crossed the configured {hil_limit:g}° limit",
                impact=(
                    "Under the degraded sensor conditions this project treats as survivable, "
                    "the filter's error leaves the acceptable envelope."
                ),
                evidence=tuple(evidence),
                action=RecommendedAction(
                    summary=(
                        "Harden the filter (outlier rejection, dropout handling) or revise the "
                        "fault envelope if it is stricter than the field."
                    ),
                    config_path="hil.max_faulted_rmse_deg",
                ),
                suite="hil",
                metrics=("faulted_rmse_deg",),
                provenance=_provenance_of(report, "hil", "faulted_rmse_deg"),
                magnitude=faulted - hil_limit,
            )
        )

    drop_rate = _numeric(hil, "drop_rate")
    if drop_rate is not None and drop_rate > 0.10:
        out.append(
            ValidationInsight(
                id="hil-drop-rate",
                severity=Severity.MEDIUM,
                category=InsightCategory.ROBUSTNESS,
                title=f"{drop_rate:.1%} of samples were dropped by the fault chain",
                impact=(
                    "At this loss rate the filter is running on sparse data; accuracy figures "
                    "from this run describe a heavily degraded stream."
                ),
                evidence=(
                    Evidence("Drop rate", f"{drop_rate:.2%}"),
                    Evidence("Samples in", str(hil.get("samples_in", "?"))),
                    Evidence("Samples out", str(hil.get("samples_out", "?"))),
                ),
                action=RecommendedAction(
                    summary="Confirm this loss rate matches the environment you are certifying for.",
                    config_path="hil.faults",
                ),
                suite="hil",
                metrics=("drop_rate",),
                confidence=Confidence.MEASURED,
                provenance=_provenance_of(report, "hil", "drop_rate"),
                magnitude=drop_rate * 100,
            )
        )

    stability = _numeric(_metrics(report, "tinyml"), "confidence_stability")
    if stability is not None and stability > 0:
        out.append(
            ValidationInsight(
                id="tinyml-unstable-output",
                severity=Severity.HIGH,
                category=InsightCategory.ACCURACY,
                title="Model output is not reproducible across identical inputs",
                impact=(
                    "The same input produced different outputs across repeated runs. Any "
                    "threshold tuned on this model is unreliable, and failures will be "
                    "intermittent."
                ),
                evidence=(
                    Evidence("Max per-element output spread", f"{stability:g}"),
                    Evidence("Expected for a deterministic model", "0"),
                ),
                action=RecommendedAction(
                    summary=(
                        "Look for uninitialised buffers, dropout left enabled, or a "
                        "non-deterministic accelerator path."
                    ),
                ),
                suite="tinyml",
                metrics=("confidence_stability",),
                confidence=Confidence.INFERRED,
                provenance=_provenance_of(report, "tinyml", "confidence_stability"),
                magnitude=stability,
            )
        )
    return out


_COVERED_BY_SPECIFIC_RULES = {"rt_perf", "memory"}


def _suite_failure_insights(report: dict[str, Any]) -> list[ValidationInsight]:
    """Anything that failed and was not explained by a more specific rule."""
    out: list[ValidationInsight] = []
    specific = {"fusion", "hil", *_COVERED_BY_SPECIFIC_RULES}
    for entry in report.get("suites") or []:
        if not isinstance(entry, dict) or entry.get("passed"):
            continue
        name = str(entry.get("name", "?"))
        notes = str(entry.get("notes", "")).strip()
        if name in specific:
            # Only add a fallback when no threshold rule produced anything.
            continue
        evidence = [Evidence("Verdict", "FAIL")]
        if notes:
            evidence.append(Evidence("Suite notes", notes[:400]))
        metrics = entry.get("metrics") or {}
        for key in list(metrics)[:4]:
            info = metric_info(report, name, key)
            evidence.append(Evidence(key, format_value(metrics[key], info)))
        action_summary = {
            "firmware": (
                "Read the captured serial output: the device either never printed a pass "
                "pattern or printed a fail pattern."
            ),
            "tinyml": "Check the model path and runtime; the benchmark produced no timing data.",
        }.get(name, "Open the suite's notes and metrics for the failure detail.")
        out.append(
            ValidationInsight(
                id=f"suite-failed-{name}",
                severity=Severity.HIGH,
                category=(
                    InsightCategory.ACCURACY if name != "firmware" else InsightCategory.EXECUTION
                ),
                title=f"The {name} suite failed",
                impact="This suite is part of the release gate, so the build is not shippable.",
                evidence=tuple(evidence),
                action=RecommendedAction(summary=action_summary),
                suite=name,
                magnitude=50.0,
            )
        )
    return out


def _unexplained_failure_insights(
    report: dict[str, Any], existing: list[ValidationInsight]
) -> list[ValidationInsight]:
    """Catch failing threshold suites whose specific rule did not fire.

    A fusion suite can fail for reasons other than crossing the RMSE limit
    (a missing dataset, for instance). Without this rule the failure would
    be visible in the table but absent from the diagnosis.

    A suite counts as explained only when something release-blocking was
    already said about it: a medium-severity headroom note does not
    account for a suite that actually failed.
    """
    explained = {i.suite for i in existing if i.severity.blocks_release}
    out: list[ValidationInsight] = []
    for entry in report.get("suites") or []:
        if not isinstance(entry, dict) or entry.get("passed"):
            continue
        name = str(entry.get("name", "?"))
        if name not in {"fusion", "hil", "rt_perf", "memory"} or name in explained:
            continue
        notes = str(entry.get("notes", "")).strip()
        out.append(
            ValidationInsight(
                id=f"suite-failed-{name}",
                severity=Severity.HIGH,
                category=InsightCategory.ACCURACY,
                title=f"The {name} suite failed",
                impact="This suite is part of the release gate, so the build is not shippable.",
                evidence=(
                    Evidence("Verdict", "FAIL"),
                    Evidence("Suite notes", notes[:400] or "no notes recorded"),
                ),
                action=RecommendedAction(
                    summary=(
                        "The failure is not a threshold crossing — check the suite's inputs "
                        "(dataset present? task set defined?)."
                    ),
                    command="eaiv config validate <config>",
                ),
                suite=name,
                magnitude=45.0,
            )
        )
    return out


def _improvement_insights(
    report: dict[str, Any], regression: RegressionReport | None
) -> list[ValidationInsight]:
    if regression is None:
        return []
    improved = [
        d
        for d in regression.deltas
        if not d.regressed
        and d.direction != 0
        and (
            (d.direction > 0 and d.change_pct > IMPROVEMENT_REPORT_PCT)
            or (d.direction < 0 and d.change_pct < -IMPROVEMENT_REPORT_PCT)
        )
    ]
    if not improved:
        return []
    best = max(improved, key=lambda d: abs(d.change_pct))
    info = metric_info(report, best.suite, best.metric)
    return [
        ValidationInsight(
            id="improvements",
            severity=Severity.INFO,
            category=InsightCategory.IMPROVEMENT,
            title=(
                f"{len(improved)} metric(s) improved — best: {best.suite}.{best.metric} "
                f"by {abs(best.change_pct):.1f}%"
            ),
            impact="Worth confirming the gain is real before it becomes the new expectation.",
            evidence=(
                Evidence("Baseline", format_value(best.baseline, info)),
                Evidence("This run", format_value(best.current, info)),
                Evidence("Metrics improved", str(len(improved))),
            ),
            action=RecommendedAction(
                summary="If this run is representative, promote it as the new baseline.",
                command="eaiv baseline save reports/latest.json --name <name>",
            ),
            suite=best.suite,
            metrics=(best.metric,),
            confidence=Confidence.DERIVED,
            magnitude=abs(best.change_pct),
        )
    ]


def _provenance_insights(report: dict[str, Any]) -> list[ValidationInsight]:
    """State plainly when the numbers did not come from hardware."""
    provenance = overall_provenance(report)
    if provenance == "measured":
        return []
    if provenance == "unknown":
        return [
            ValidationInsight(
                id="provenance-unknown",
                severity=Severity.INFO,
                category=InsightCategory.PROVENANCE,
                title="This report predates metric provenance tracking",
                impact=(
                    "It is not recorded whether these values were measured on hardware or "
                    "produced by a simulation. Treat cross-run comparisons with care."
                ),
                evidence=(Evidence("Report schema", str(report.get("schema_version", 1))),),
                action=RecommendedAction(
                    summary="Re-run to get a report with provenance recorded."
                ),
                confidence=Confidence.MEASURED,
                provenance=provenance,
            )
        ]
    counts: dict[str, int] = {}
    for entry in report.get("suites") or []:
        if not isinstance(entry, dict):
            continue
        for metric, value in (entry.get("metrics") or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            info = metric_info(report, str(entry.get("name", "?")), metric)
            if info.provenance is not MetricProvenance.MEASURED:
                counts[str(info.provenance)] = counts.get(str(info.provenance), 0) + 1
    detail = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
    return [
        ValidationInsight(
            id="provenance-not-hardware",
            severity=Severity.INFO,
            category=InsightCategory.PROVENANCE,
            title=(
                "All measurements in this run are simulated"
                if provenance == "simulated"
                else "Some measurements in this run are not hardware readings"
            ),
            impact=(
                "Simulated, mock, and estimated values are useful for catching regressions in "
                "logic, but they cannot certify timing or power behaviour on a real device."
            ),
            evidence=(
                Evidence("Overall provenance", provenance),
                Evidence("Non-hardware metrics", detail or "none"),
                Evidence(
                    "Target", str((report.get("meta") or {}).get("target", {}).get("kind", "?"))
                ),
            ),
            action=RecommendedAction(
                summary="Re-run against a physical target before making a shipping decision.",
                config_path="target.kind",
            ),
            confidence=Confidence.MEASURED,
            provenance=provenance,
        )
    ]


def _coverage_insights(
    report: dict[str, Any], manifest: RunManifest | None
) -> list[ValidationInsight]:
    out: list[ValidationInsight] = []
    memory = _metrics(report, "memory")
    if memory.get("skipped"):
        entry = _suite_entry(report, "memory") or {}
        out.append(
            ValidationInsight(
                id="memory-skipped",
                severity=Severity.MEDIUM,
                category=InsightCategory.COVERAGE,
                title="Footprint analysis was skipped — no ELF to analyse",
                impact=(
                    "Flash and RAM budgets were not checked at all, so a footprint regression "
                    "would pass this gate unnoticed."
                ),
                evidence=(Evidence("Suite notes", str(entry.get("notes", ""))[:300]),),
                action=RecommendedAction(
                    summary="Point memory.binary at a built ELF, or set memory.require to enforce it.",
                    config_path="memory.binary",
                ),
                suite="memory",
                confidence=Confidence.MEASURED,
            )
        )
    if manifest is not None and manifest.suite_selection != "all" and manifest.suites:
        out.append(
            ValidationInsight(
                id="partial-suite-selection",
                severity=Severity.INFO,
                category=InsightCategory.COVERAGE,
                title=f"Only the '{manifest.suite_selection}' suite ran",
                impact="Other suites were not executed, so this run is not a full release gate.",
                evidence=(
                    Evidence("Suites run", ", ".join(manifest.suites)),
                    Evidence("Selection", manifest.suite_selection),
                ),
                action=RecommendedAction(
                    summary="Run the full gate before shipping.",
                    command=f"eaiv pipeline --config {manifest.config_path or '<config>'} --suite all",
                ),
            )
        )
    return out


# -- entry point -----------------------------------------------------------


def generate_insights(
    report: dict[str, Any],
    regression: RegressionReport | None = None,
    manifest: RunManifest | None = None,
    baseline_name: str = "",
) -> list[ValidationInsight]:
    """Prioritized insights for one validation run.

    ``report`` may be any schema version — it is normalized first, so a
    legacy artifact yields the same insight types with whatever evidence
    it actually recorded.
    """
    normalized = normalize_report(report)
    insights: list[ValidationInsight] = []
    insights += _execution_insights(manifest)
    insights += _report_integrity_insights(normalized)
    insights += _deadline_insights(normalized)
    insights += _budget_insights(normalized)
    insights += _regression_insights(normalized, regression, baseline_name)
    insights += _accuracy_insights(normalized)
    insights += _suite_failure_insights(normalized)
    insights += _unexplained_failure_insights(normalized, insights)
    insights += _improvement_insights(normalized, regression)
    insights += _coverage_insights(normalized, manifest)
    insights += _provenance_insights(normalized)
    return sort_insights(insights)


def top_insight(insights: list[ValidationInsight]) -> ValidationInsight | None:
    """The single highest-priority item — the "what do I do next" answer."""
    return insights[0] if insights else None


def blocking_insights(insights: list[ValidationInsight]) -> list[ValidationInsight]:
    return [i for i in insights if i.severity.blocks_release]


__all__ = [
    "HEADROOM_WARNING_FRACTION",
    "IMPROVEMENT_REPORT_PCT",
    "blocking_insights",
    "generate_insights",
    "top_insight",
]
