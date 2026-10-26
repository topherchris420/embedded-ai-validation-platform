# 3. Declared firmware authorship

Date: 2026-10-26
Status: accepted

## Context

Engineers increasingly write firmware with AI coding tools. Reviewers want
to know which builds were written that way, because the defects a code
review is least likely to catch (timing, interrupt ordering, peripheral
state, power modes) need the hardware to show. EAIV records evidence:
measurements with their provenance and source. Authorship is not evidence.
It is a statement by the engineer, and nothing in a binary or a report can
confirm it.

## Decision

Record authorship as a declaration, kept apart from evidence:

1. `target.binary_origin` takes `unknown`, `human`, `ai_assisted`, or
   `ai_generated`; `target.binary_origin_tool` optionally names the tool.
   Both are recorded in `meta.inputs.firmware.authorship`, next to the
   firmware's hash, even when no binary path is configured.
2. EAIV never infers or detects authorship. `unknown` is the default and
   makes no claim. Values outside the four, malformed entries, and reports
   written before the field existed all read as `unknown`.
3. Authorship never turns a gate green or red by itself. Comparisons show a
   non-blocking caveat when the declarations differ, including when only one
   run declares. Firmware declared `ai_assisted` or `ai_generated` whose
   firmware suite has no measured device evidence gets one medium-severity
   finding, and the release verdict names the missing evidence. Like any
   open medium finding, it keeps an otherwise device-measured run at
   "Further validation required"; it never produces "Not ready to ship".
4. The field lives under `target.*`, not `firmware.*`. It describes the
   binary in `target.binary`, which every target suite runs; `firmware.*`
   configures one suite.

## Consequences

Reports can say how firmware was written without treating that as a
measurement. A missing or removed declaration is visible in comparisons
rather than read as a match. Teams that want authorship to block a release
need a policy outside EAIV's gates; adding one here would let a claim
override evidence. Mission presets do not declare authorship for the
engineer.
