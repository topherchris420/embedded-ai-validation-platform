# Runs, Reports, and Events

A report says *what was measured*. A run says *what happened*. The
platform models both, which is what lets it show an in-flight run, a
cancelled run, or a run that crashed before it could write a report at
all.

## The run storage model

`eaiv pipeline` (and anything launched from Mission Control) records each
run under the report directory:

```text
reports/
  runs/
    20260729T161220-ci-gate-c088c0/
      manifest.json          run identity, stages, artifacts, outcome
      events.jsonl           append-only event log, one JSON object per line
      report.json            the report artifacts for this run
      report.md
      report.csv
      report.html
      telemetry.csv          when telemetry capture ran
      resolved-config.yaml   the configuration exactly as this run used it
      logs/run.log           human-readable log (rotated at 4 MB)
      cancel.request         present only while a cancellation is pending
  latest.json                unchanged legacy pointer
  report_<timestamp>.json    unchanged legacy per-run report
  report.csv / .md / .html   unchanged legacy renderings
```

Run IDs are sortable, filesystem-safe, and validated before they are used
as a path segment, so an id arriving from a URL or a form cannot escape the
store.

### Manifest contents

`manifest.json` is a serialized
[`RunManifest`](../src/eaiv/runs/models.py):

| Field | Meaning |
|-------|---------|
| `run_id`, `name` | stable identifier and human-readable name |
| `status` | `pending`, `running`, `passed`, `failed`, `cancelled`, `interrupted`, `error` |
| `created_at`, `started_at`, `completed_at`, `duration_s` | timing |
| `suite_selection`, `suites` | what was asked for, and what actually ran |
| `target` | kind, name, architecture, clock, flash/RAM size |
| `config_path`, `resolved_config` | reproduction inputs |
| `baseline`, `save_baseline`, `max_regression_pct` | gate configuration |
| `eaiv_version`, `report_schema_version` | versions |
| `git`, `host` | commit/branch/dirty state, platform, Python, CPU count |
| `stages` | per-stage status, timing, detail, and structured failure |
| `artifacts` | produced files, relative to the run directory |
| `summary` | suite counts, pass rate, regressions, worst regression |
| `failure` | exception type, message, traceback, and a hint |
| `cancel_reason`, `provenance`, `trigger`, `pid`, `heartbeat` | operational context |

### Atomic writes and interrupted runs

Manifests are written to a temporary file in the same directory and then
`os.replace`d, so a process killed mid-write leaves the previous manifest
intact rather than a truncated file.

A run whose process died is *reconciled* the next time the store is read:
if its heartbeat is stale and its process is gone, its status becomes
`interrupted`, its in-flight stage is marked failed, and a `RunFailure`
explains that the process exited early. A completed run never looks
active, and an abandoned one never looks alive. `RunStore.reconcile_all()`
does this for every run; the dashboard calls it on page load.

## Report schema

Reports carry a `schema_version`:

| Version | Adds |
|---------|------|
| 1 | the original format: `timestamp`, `meta.eaiv_version`, `meta.target`, `suites[]`, `all_passed` |
| 2 | `schema_version`, `run` identity, reproduction context (`meta.config`, `meta.host`, `meta.git`, `meta.inputs` with SHA-256 hashes, `meta.thresholds`, `meta.plugins`), and per-metric `metric_meta` |

Reports written before this schema existed have no `schema_version` and
are still first-class inputs. `normalize_report()` upgrades any payload to
the current in-memory shape without touching the file, so the dashboard,
the comparison engine, and the insight engine treat a two-year-old
artifact and a report written a second ago identically. Fields a legacy
report genuinely lacks come back empty and are flagged `legacy` so the UI
can say so rather than inventing values.

A newer `schema_version` than this build understands is passed through
with its fields intact — refusing to open the file would be worse.

## Measurement provenance

Every numeric metric can declare where it came from. This is the single
most important honesty guarantee in the platform: **a simulated number is
never presented as a hardware measurement.**

| Provenance | Meaning |
|------------|---------|
| `measured` | a real reading (device, host runtime, or static analysis of a real artifact) |
| `simulated` | produced by a software simulation, including QEMU |
| `estimated` | derived from a model or heuristic, not a direct reading |
| `mock` | produced by a stand-in runtime; not a real workload |
| `unknown` | origin not recorded (every legacy report) |

Alongside it, `source` records *where* the reading was taken: `device`,
`host`, `simulator`, `static-analysis`, or `dataset`.

What the built-in suites declare:

| Suite | Provenance | Notes |
|-------|------------|-------|
| `firmware` | from the target kind | `sim`/`qemu` → simulated; `serial`/`jlink` → measured |
| `tinyml` | `measured` (host) or `mock` | timings are **host-side even with a real runtime** — this suite does not run the model on the device |
| `tinyml` MAC/arena estimates | `estimated` | crude bounds, not layer-accurate profiles |
| `tinyml` power | `simulated` or `measured` | depends on `tinyml.power.kind` |
| `memory` | `measured` (static analysis) | read out of the ELF itself |
| `fusion` | from the dataset's sidecar | a generated dataset yields simulated scores |
| `hil` | `simulated` | faults are injected in software |
| `rt_perf` | measured or `simulated` | the synthetic-trace fallback is labelled |

A run's overall provenance is `measured` only when every metric is;
`simulated` when none are; `mixed` in between. The release verdict never
returns "ready to ship" for a run that is not fully measured.

### Provenance and the regression gate

Metrics labelled `mock` are reported but **never gate**: a stand-in
runtime's sub-microsecond timings swing by orders of magnitude between
runs and say nothing about the code under review. They are downgraded to
informational. Pass `gate_non_measured=True` to `compare_reports` to
compare them anyway. Metrics without declared provenance — every legacy
report — gate exactly as they always did.

## The event system

Execution emits typed `PipelineEvent` values through an `EventSink`
(anything with an `emit(event)` method). The core package never imports a
UI toolkit.

Event kinds: `run_created`, `stage_started`, `stage_progress`, `log`,
`target_connected`, `artifact`, `metric`, `suite_passed`, `suite_failed`,
`stage_completed`, `run_cancelled`, `run_failed`, `run_completed`.

Each event carries a monotonic per-run `seq`, a timestamp, the stage it
belongs to, a level, and a `data` payload. The sequence number is what
makes ordering assertions and incremental reads possible when timestamps
collide at millisecond resolution.

```python
from eaiv.config import load_config
from eaiv.core.pipeline import ValidationPipeline
from eaiv.runs import CallbackEventSink, RunStore

def on_event(event):
    print(event.seq, event.kind, event.stage, event.message)

pipeline = ValidationPipeline(
    load_config("configs/sim.yaml"),
    run_store=RunStore("reports"),      # durable events.jsonl + manifest
    events=CallbackEventSink(on_event),  # plus your own observer
)
result = pipeline.run(suite="all")
```

Sinks provided: `NullEventSink`, `MemoryEventSink` (bounded),
`CallbackEventSink` (a failing observer is logged, never fatal),
`JsonlEventSink` (append-only, rotated at 8 MB), and
`CompositeEventSink`. Reading a JSONL log tolerates a truncated final line,
which is normal while a run is in flight.

## Cancellation

Cancellation is cooperative and checked between stages plus inside the
long-running loops that can afford a poll. A `CancellationToken` can watch
a sentinel file, and that is how the dashboard cancels:

```bash
# What "Cancel run" does, and it works across processes
python -c "from eaiv.runs import RunStore; RunStore('reports').request_cancel('<run-id>')"
```

Because the request lives in the run directory, a run started in one
browser session (or one process) can be cancelled from another. A
cancelled run records `cancel_reason`, marks every unreached stage
`cancelled`, and finishes with status `cancelled` — never a silent hang.

## Backward compatibility

Everything below is unchanged by the run model:

- `reports/latest.json`, `reports/report_<timestamp>.json`, and
  `reports/report.{csv,md,html}` are still written to the same paths with
  the same top-level keys. The CSV keeps its original leading columns
  (`suite,metric,value,passed`) and appends `unit,provenance`.
- `eaiv run` behaves exactly as before and does **not** create a run
  directory. `eaiv pipeline` records runs; pass `--no-record` to opt out.
- `ValidationPipeline` and `Orchestrator` work with no session, sink, or
  store — that is the default, and it is the pre-existing behaviour.
- `StageResult.status` still holds the strings `ok`, `failed`, `skipped`,
  so callers comparing against literals keep working. (`StageStatus` is a
  `StrEnum` over the same values, plus `pending`, `running`, `cancelled`.)
- `SuiteResult` gained `metric_meta` with an empty default, so suites and
  plugins written before provenance existed are unaffected.
- Legacy reports remain readable, comparable, and diagnosable.

## Python API

```python
from eaiv.runs import RunStore

store = RunStore("reports")
store.reconcile_all()                    # settle abandoned runs
for manifest in store.list(limit=10):    # newest first
    print(manifest.run_id, manifest.status, manifest.summary.pass_rate)

manifest = store.load("<run-id>")
events = store.events("<run-id>", after_seq=0)
report = store.run_dir("<run-id>") / "report.json"
```

To treat recorded runs and legacy report files uniformly, use the
dashboard data layer — it is Streamlit-free and unit-tested:

```python
from eaiv.dashboard.runs import all_sources

for source in all_sources(RunStore("reports"), "reports"):
    print(source.kind, source.label, source.provenance, source.passed)
```
