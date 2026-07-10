"""Physical target attached over UART (e.g. USB-CDC on a dev board)."""

from __future__ import annotations

import time
from typing import Any

from eaiv.targets.base import Target, TargetInfo


class SerialTarget(Target):
    def __init__(self, spec: dict) -> None:
        super().__init__(spec)
        s = spec.get("serial", {})
        self.port = s.get("port", "/dev/ttyACM0")
        self.baud = s.get("baud", 115200)
        self._ser: Any = None

    def _open(self) -> Any:
        if self._ser is None:
            import serial  # pyserial

            self._ser = serial.Serial(self.port, self.baud, timeout=1)
        return self._ser

    def flash(self, binary: str) -> None:
        # Most dev boards with a DFU/mass-storage bootloader are flashed by
        # a separate tool (e.g. `st-flash`, board-specific bootloader
        # scripts) invoked before eaiv runs. Here we just reset and assume
        # the binary named in `binary` is already resident on the device.
        self.reset()

    def reset(self) -> None:
        ser = self._open()
        if hasattr(ser, "dsrdtr"):
            ser.dsrdtr = False
            time.sleep(0.1)
            ser.dsrdtr = True
            time.sleep(0.1)
            ser.dsrdtr = False

    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        ser = self._open()
        ser.write((cmd + "\n").encode())
        return self.read_serial(timeout_s)

    def read_serial(self, duration_s: float) -> str:
        ser = self._open()
        end = time.time() + duration_s
        buf = bytearray()
        while time.time() < end:
            n = ser.in_waiting
            if n:
                buf += ser.read(n)
            else:
                time.sleep(0.01)
        return buf.decode(errors="replace")

    def info(self) -> TargetInfo:
        return TargetInfo(name=f"serial:{self.port}", arch="unknown", clock_hz=0)
