"""Abstract hardware target interface shared by qemu/serial/jlink backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TargetInfo:
    name: str
    arch: str
    clock_hz: int


class Target(ABC):
    """A device (real or emulated) that firmware can be flashed to and
    communicated with over some transport."""

    def __init__(self, spec: dict) -> None:
        self.spec = spec

    @abstractmethod
    def flash(self, binary: str) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str: ...

    @abstractmethod
    def read_serial(self, duration_s: float) -> str: ...

    @abstractmethod
    def info(self) -> TargetInfo: ...
