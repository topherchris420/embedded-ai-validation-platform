# Evidence gates

EAIV answers two separate questions: did this workload regress, and what does
its evidence establish about the target? A passing regression gate can be
useful in simulation. Target-device readiness requires measured device data.

## Comparison contract

| Condition | Gate behavior |
|---|---|
| Numeric worsening beyond the configured allowance | Fail; name the metric and delta |
| Baseline suite or numeric metric absent from the candidate | Fail; report lost coverage |
| Previously executed suite becomes skipped | Fail |
| Failed suite or failed aggregate report on either side | Fail, while retaining valid deltas |
| NaN, infinity, duplicate suite names, malformed metadata or verdicts | Fail with an evidence issue |
| No shared finite numeric metrics | Fail; no evidence to compare |
| Declared unit, direction, provenance or source changes/disappears | Fail; show the changed definition |
| Recorded target name, kind, architecture or clock changes/disappears | Fail |
| Mock values on either side | Informational deltas; provenance changes still fail |
| New candidate metric | Show as added; it has no baseline yet |
| Input hashes or platform version differ | Show compatibility caveats for review |
| Declared firmware authorship differs, or is declared on one side only | Show a compatibility caveat for review |
| Legacy baseline without metric metadata | Allow comparison using inferred definitions; retain provenance caveats |

The numeric allowance must be finite and non-negative. A metric's explicit
`direction` (`-1`, `0`, `1`) takes precedence over its name. Removing evidence
is not a way to retire a requirement: deliberately establish a new baseline
and review its coverage when the workload changes.

An optional suite skipped in both runs is still skipped coverage, not a new
regression. The readiness verdict warns about incomplete evidence. Informational
metrics do not establish performance guarantees.

## Declared firmware authorship

`target.binary_origin` records how the firmware source was written:
`human`, `ai_assisted`, `ai_generated`, or `unknown` (the default). It is the
engineer's declaration, stored with the firmware's identity in
`meta.inputs.firmware.authorship`. EAIV does not detect it and does not gate
on it. A value outside those four is recorded and read as `unknown`, as are
reports written before the field existed. The declaration is recorded even
when `target.binary` is not set.

It has two effects. A comparison shows a non-blocking caveat when the
declared authorship differs between the runs, including when only one run
declares it. And a run whose firmware is declared `ai_assisted` or
`ai_generated`, but whose firmware suite numbers were not measured on the
device, gets a medium-severity finding (`ai-firmware-not-on-device`). Timing,
interrupt ordering, peripheral state and power-mode defects are the ones a
code review is least likely to catch, and they need the hardware to show.
The finding never blocks a release by itself. Like any open medium-severity
finding, it keeps an otherwise device-measured run at "Further validation
required" until the firmware suite has device evidence.

## CI and review exports

```bash
# Text and process exit code for a terminal/CI job
eaiv compare baseline.json reports/latest.json --max-regression-pct 10

# Same gate, structured explanation
eaiv compare baseline.json reports/latest.json --format json > comparison.json
eaiv compare baseline.json reports/latest.json --format markdown > comparison.md

# Recorded runs also account for execution status in their manifests
eaiv runs compare <reference-id> <candidate-id> --format json
```

A successful comparison exits `0`; a blocked comparison exits `1`. Invalid
CLI syntax is a usage error. JSON includes `passed`, `issues` (code, message,
suite, metric), compatibility, counts, and per-metric changes. Output is still
written when the gate fails.

A percentage change from zero to a nonzero value is mathematically undefined.
The directional gate still catches worsening, and JSON represents the percentage
as `null` with `percentage_defined: false`. Markdown shows the zero-baseline
caveat instead of a fictitious percentage. Unrepresentable floating-point
changes likewise serialize as `null`.

## Baseline promotion

`eaiv baseline save report.json --name release-1` refuses failed, empty, or
malformed reports before touching an existing baseline. An accepted snapshot
is flushed to a temporary file and atomically replaced in the same directory.
Historical failed baseline files remain inspectable, but cannot be promoted
again without valid passing evidence. Simulation baselines remain useful and
retain their provenance; saving one does not certify a device.

## Measurement boundaries

- **Host runtime:** TinyML inference currently executes on the host. Measured
  host results do not establish target latency.
- **Power Monitor:** origin comes from the instantiated monitor. INA226 over
  an in-memory I2C Bus Adapter and PPK2 over a mock serial transport produce
  simulated readings. External monitors default to unknown origin until they
  implement `measurement_origin`.
- **Energy:** a mock workload produces mock energy per inference, even with a
  physical monitor. Capture brackets warmup and timed inference, excluding
  the separate output-stability workload. Empty captures fail the benchmark.
- **Dataset:** a missing metadata sidecar means unknown provenance. It is not
  evidence of a physical recording.
- **Run:** failed, cancelled, or interrupted execution cannot be overridden by
  a passing report from an earlier stage in the recorded-run views.

These are evidence checks, not statistical significance tests or hardware
certification. Repeated physical measurements, instrument calibration, and
representative workloads are still required for a device-level claim. Driver
unit tests use mocks; they do not establish physical instrument accuracy.
