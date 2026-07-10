"""J-Link target using pylink-square if available, else the JLinkExe CLI."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from eaiv.targets.base import Target, TargetInfo


class JLinkTarget(Target):
    def __init__(self, spec: dict) -> None:
        super().__init__(spec)
        j = spec.get("jlink", {})
        self.device = j.get("device", "STM32H743VI")
        self.interface = j.get("interface", "swd")
        self._pylink: Any = None
        self._jlink: Any = None
        try:
            import pylink

            self._pylink = pylink
        except ImportError:
            pass

    def _ensure_connected(self) -> Any:
        if self._pylink is None:
            raise RuntimeError("pylink-square not installed; pip install '.[jlink]'")
        if self._jlink is None:
            self._jlink = self._pylink.JLink()
            self._jlink.open()
            self._jlink.set_tif(getattr(self._pylink.enums.JLinkInterfaces, self.interface.upper()))
            self._jlink.connect(self.device)
        return self._jlink

    def flash(self, binary: str) -> None:
        if self._pylink:
            j = self._ensure_connected()
            j.flash_file(binary, 0x08000000)
        else:
            exe = shutil.which("JLinkExe") or shutil.which("JLink")
            if not exe:
                raise RuntimeError(
                    "Neither pylink-square nor JLinkExe found. Install "
                    "'.[jlink]' or the SEGGER J-Link software pack."
                )
            script = (
                f"device {self.device}\n"
                f"si {self.interface}\n"
                "speed 4000\n"
                "connect\n"
                f"loadfile {binary}\n"
                "r\n"
                "g\n"
                "exit\n"
            )
            subprocess.run(
                [exe, "-autoconnect", "1", "-CommanderScript", "/dev/stdin"],
                input=script,
                text=True,
                check=True,
            )

    def reset(self) -> None:
        if self._pylink:
            self._ensure_connected().reset()

    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        # RTT-based command channel would be wired in here; kept as a
        # documented stub since RTT block discovery is device-specific.
        return ""

    def read_serial(self, duration_s: float) -> str:
        return ""

    def info(self) -> TargetInfo:
        return TargetInfo(name=f"jlink:{self.device}", arch="arm", clock_hz=480_000_000)
