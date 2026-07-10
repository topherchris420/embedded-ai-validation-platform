"""Run firmware under qemu-system-arm (no hardware required)."""

from __future__ import annotations

import shutil
import subprocess
import time

from eaiv.targets.base import Target, TargetInfo


class QEMUTarget(Target):
    def __init__(self, spec: dict) -> None:
        super().__init__(spec)
        self.q = spec.get("qemu", {})
        self.machine = self.q.get("machine", "mps2-an385")
        self.cpu = self.q.get("cpu", "cortex-m3")
        self._proc: subprocess.Popen | None = None

    def flash(self, binary: str) -> None:
        if shutil.which("qemu-system-arm") is None:
            raise RuntimeError(
                "qemu-system-arm not found on PATH; install the 'qemu' "
                "extra dependencies or apt-get install qemu-system-arm"
            )
        self._proc = subprocess.Popen(
            [
                "qemu-system-arm",
                "-M",
                self.machine,
                "-cpu",
                self.cpu,
                "-kernel",
                binary,
                "-nographic",
                "-serial",
                "mon:stdio",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def reset(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self.flash(self.spec.get("binary", ""))

    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()
        return self.read_serial(timeout_s)

    def read_serial(self, duration_s: float) -> str:
        assert self._proc and self._proc.stdout
        end = time.time() + duration_s
        buf: list[str] = []
        while time.time() < end:
            line = self._proc.stdout.readline()
            if line:
                buf.append(line)
        return "".join(buf)

    def info(self) -> TargetInfo:
        return TargetInfo(name=f"qemu:{self.machine}", arch=self.cpu, clock_hz=25_000_000)

    def close(self) -> None:
        """Clean up QEMU process."""
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
