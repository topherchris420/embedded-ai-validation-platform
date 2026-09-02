## 2025-05-18 - Single-pass telemetry series aggregation

**Learning:** `TelemetryCollector.summary()` previously iterated over all telemetry samples once per field via list comprehension to extract field values (`[s.values[name] for s in samples if name in s.values]`), leading to $O(\text{samples} \times \text{fields})$ overhead.

**Action:** Accumulate telemetry field series in a single pass dictionary (`series_by_name`) to reduce total passes over large telemetry collections.
