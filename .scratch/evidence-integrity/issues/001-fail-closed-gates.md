# Preserve evidence integrity across release decisions

Status: complete
Triage: ready-for-agent
Dependencies: none

Problem: comparisons could pass after coverage disappeared, NaN arrived,
or a suite failed; host measurements and mock hardware transports could
imply device readiness.

Implemented: shared evidence validation; explicit gate blockers and exports;
atomic, validated promotion; target-aware verdicts; transport-aware power
provenance; capture cleanup and missing-sample failures.

Acceptance: regression and integration tests exercise invalid/absent evidence,
metadata changes, failed promotion, interrupted runs, and power capture failures.
