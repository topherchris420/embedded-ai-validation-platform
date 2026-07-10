"""Standalone example: run the firmware suite against QEMU.

Run: python examples/firmware_smoke_test.py
Requires qemu-system-arm on PATH (apt-get install qemu-system-arm).
"""

from __future__ import annotations

from eaiv.firmware.tester import FirmwareTester
from eaiv.targets import build_target

if __name__ == "__main__":
    target = build_target(
        {
            "kind": "qemu",
            "binary": "build/firmware.elf",
            "qemu": {"machine": "mps2-an385", "cpu": "cortex-m3"},
        }
    )
    spec = {
        "timeout_s": 15,
        "retries": 1,
        "pass_patterns": ["PASS", "ALL_TESTS_OK"],
        "fail_patterns": ["FAIL", "ASSERT"],
    }
    result = FirmwareTester(spec, target).run()
    print(result)
