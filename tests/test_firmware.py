"""Tests for the firmware suite using a fake in-memory Target."""
from __future__ import annotations

from eaiv.firmware.tester import FirmwareTester
from eaiv.targets.base import Target, TargetInfo


class FakeTarget(Target):
    def __init__(self, spec: dict, scripted_output: str) -> None:
        super().__init__(spec)
        self.scripted_output = scripted_output
        self.flash_calls = 0
        self.reset_calls = 0

    def flash(self, binary: str) -> None:
        self.flash_calls += 1

    def reset(self) -> None:
        self.reset_calls += 1

    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        return self.scripted_output

    def read_serial(self, duration_s: float) -> str:
        return self.scripted_output

    def info(self) -> TargetInfo:
        return TargetInfo(name="fake", arch="test", clock_hz=0)


def test_firmware_pass_pattern_matches():
    target = FakeTarget({"binary": "x.elf"}, "booting...\nALL_TESTS_OK\n")
    spec = {"timeout_s": 1, "retries": 0, "pass_patterns": ["ALL_TESTS_OK"], "fail_patterns": ["FAIL"]}
    result = FirmwareTester(spec, target).run()
    assert result.passed
    assert result.metrics["attempts"] == 1
    assert target.flash_calls == 1


def test_firmware_fail_pattern_short_circuits():
    target = FakeTarget({"binary": "x.elf"}, "booting...\nASSERT triggered\nFAIL\n")
    spec = {"timeout_s": 1, "retries": 2, "pass_patterns": ["PASS"], "fail_patterns": ["FAIL"]}
    result = FirmwareTester(spec, target).run()
    assert not result.passed


def test_firmware_neither_pattern_retries_then_fails():
    target = FakeTarget({"binary": "x.elf"}, "no useful output\n")
    spec = {"timeout_s": 1, "retries": 2, "pass_patterns": ["PASS"], "fail_patterns": ["FAIL"]}
    result = FirmwareTester(spec, target).run()
    assert not result.passed
    assert result.metrics["attempts"] == 3
