# 2. Fail-closed evidence gates

Date: 2026-10-22
Status: accepted

## Context

Shared-metric-only comparisons can silently pass after a suite or metric is
removed. Non-finite arithmetic can compare false in both directions. A report
can also contain better numbers while declaring failure. These cases undermine
the platform's primary purpose: defensible validation decisions.

## Decision

Validate raw report evidence before normalization. Carry structured gate issues
alongside metric deltas, and require both to pass. Reuse these checks in the
regression engine, aggregate results, baseline store, CLI, and readiness verdict.
Explicit metric definitions take precedence over name inference; measurement
changes and coverage loss block comparisons. Keep historical reports readable.

Keep measurement source separate from provenance. Host measurements and mock
hardware transports cannot establish device readiness. Power Monitor plugins
declare their actual origin, with unknown as the default. Never substitute
nominal power when no capture data exists.

## Consequences

Some previously green comparisons now fail because they lack evidence. Existing
failed baseline files can be inspected, but new promotion refuses them. JSON
exports add `passed`, `issues`, and `percentage_defined`; undefined percentages
are `null`. Baseline writes become atomic. The `ship-with-risk` enum remains
stable, while its user-facing label is “Further validation required.”
