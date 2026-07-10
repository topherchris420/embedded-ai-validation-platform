"""Example 4: add a new hardware target as a plugin — no core changes.

Registers a toy target that "flashes" by copying a file and answers the
platform's serial protocol from a canned transcript, then drives the
standard firmware suite against it. Replace the transcript with a real
transport (vendor CLI, socket, CMSIS-DAP, ...) and the rest of the
platform — suites, telemetry, pipeline, dashboard — works unchanged.

For packaging this in your own distribution (entry points, config
wiring), see docs/plugin-development.md.

Run: python examples/add_hardware_target.py
"""

from __future__ import annotations

from eaiv.firmware.tester import FirmwareTester
from eaiv.plugins import register_plugin
from eaiv.plugins.targets import Target, TargetInfo
from eaiv.targets import build_target


@register_plugin(
    "toyboard",
    "target",
    "Example board speaking the eaiv protocol from a canned transcript",
    version="1.0.0",
    supported_hardware=["toyboard-rev-a"],
)
class ToyBoardTarget(Target):
    def __init__(self, spec: dict) -> None:
        super().__init__(spec)
        self._booted = False

    def flash(self, binary: str) -> None:
        # Real implementation: hand `binary` to your flasher tool here.
        self._booted = True

    def reset(self) -> None:
        self._booted = True

    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        return {"id": "toyboard v1", "ping": "pong"}.get(cmd, f"ERR unknown command: {cmd}")

    def read_serial(self, duration_s: float) -> str:
        if not self._booted:
            return ""
        self._booted = False
        return (
            "BOOT eaiv-fw board=toyboard cpu_hz=64000000 heap=131072\n"
            "T t=0.0000 gx=0.00000 gy=0.00000 gz=0.00000 ax=0.00000 ay=0.00000 az=1.00000\n"
            "M heap=131072\n"
            "U boot_ms=17\n"
            "ALL_TESTS_OK\n"
        )

    def info(self) -> TargetInfo:
        return TargetInfo(name="toyboard", arch="cortex-m4", clock_hz=64_000_000)


if __name__ == "__main__":
    # The registry resolves the new board exactly like the built-ins:
    target = build_target({"kind": "toyboard", "binary": "build/firmware.elf"})
    result = FirmwareTester(
        {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"]}, target
    ).run()
    print(result)
    print("PASS" if result.passed else "FAIL")
