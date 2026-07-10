"""Firmware smoke/regression tester: flash, boot, watch serial for patterns."""

from __future__ import annotations

import time

from eaiv.core.results import SuiteResult
from eaiv.targets.base import Target


class FirmwareTester:
    def __init__(self, spec: dict, target: Target) -> None:
        self.spec = spec
        self.target = target

    def run(self) -> SuiteResult:
        binary = self.target.spec.get("binary", "")
        timeout = float(self.spec.get("timeout_s", 30))
        retries = int(self.spec.get("retries", 2))
        pass_pats = self.spec.get("pass_patterns", ["PASS"])
        fail_pats = self.spec.get("fail_patterns", ["FAIL"])

        last_output = ""
        passed = False
        attempt = 0
        for attempt in range(retries + 1):
            try:
                self.target.flash(binary)
                self.target.reset()
                time.sleep(0.5)
                last_output = self.target.read_serial(timeout)
            except Exception as e:  # noqa: BLE001 - want to record and retry
                last_output = f"exception: {e}"
                continue

            if any(p in last_output for p in fail_pats):
                break
            if any(p in last_output for p in pass_pats):
                passed = True
                break

        return SuiteResult(
            name="firmware",
            passed=passed,
            metrics={
                "attempts": attempt + 1,
                "output_bytes": len(last_output),
                "target": self.target.info().name,
            },
            notes=(last_output[-400:] if not passed else "matched pass pattern"),
        )
