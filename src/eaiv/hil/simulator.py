"""HIL simulator core and the simulated hardware target.

``Simulator`` pushes a sample stream through a fault chain and collects
statistics. ``SimulatedTarget`` implements the standard ``Target``
interface entirely in software, emulating a device that boots, streams
telemetry, and reports test results over "serial" — so the firmware suite
and CI can exercise the full flash/reset/read-serial path with no
hardware and no QEMU binary installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence

from eaiv.hil.faults import Fault
from eaiv.plugins import get_registry, register_plugin
from eaiv.plugins.targets import Target, TargetInfo

Sample = tuple[float, dict[str, float]]


@dataclass
class SimulationResult:
    """Outcome of driving a stream through the fault chain."""

    emitted: int = 0
    dropped: int = 0
    duration_s: float = 0.0
    samples: list[Sample] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.emitted + self.dropped

    @property
    def drop_rate(self) -> float:
        return self.dropped / self.total if self.total else 0.0


class Simulator:
    """Applies a fault chain to a sample stream.

    Faults are applied in order; the first fault returning ``None``
    drops the sample.
    """

    def __init__(self, source: Iterable[Sample], faults: Sequence[Fault] = ()) -> None:
        self.source = source
        self.faults = list(faults)
        self.dropped = 0

    def stream(self) -> Iterator[Sample]:
        """Yield faulted samples lazily; dropped ones are counted in ``self.dropped``."""
        for t_s, values in self.source:
            sample: Sample | None = (t_s, values)
            for fault in self.faults:
                if sample is None:
                    break
                sample = fault.apply(sample[0], sample[1])
            if sample is None:
                self.dropped += 1
            else:
                yield sample

    def run(self, keep_samples: bool = True) -> SimulationResult:
        """Consume the whole stream and return statistics."""
        result = SimulationResult()
        self.dropped = 0
        first_t: float | None = None
        last_t = 0.0
        for sample in self.stream():
            result.emitted += 1
            if keep_samples:
                result.samples.append(sample)
            if first_t is None:
                first_t = sample[0]
            last_t = sample[0]
        result.dropped = self.dropped
        if first_t is not None:
            result.duration_s = last_t - first_t
        return result


class SimulatedTarget(Target):
    """A ``Target`` that emulates a device running the validation firmware.

    Serial output follows the platform's firmware test protocol: a BOOT
    banner, telemetry lines for each simulated sensor sample, and a final
    ``ALL_TESTS_OK`` / ``FAIL`` verdict. Configure via the target spec:

        target:
          kind: sim
          sim:
            dataset: datasets/imu/imu_run1.csv   # optional; synthetic otherwise
            fail: false                          # force a failing device
            telemetry_lines: 50
    """

    def __init__(self, spec: dict) -> None:
        super().__init__(spec)
        self.sim = spec.get("sim", {})
        self._flashed: str | None = None
        self._serial_pos = 0
        self._serial_log: list[str] = []

    def flash(self, binary: str) -> None:
        self._flashed = binary
        self._boot()

    def reset(self) -> None:
        self._boot()

    def _boot(self) -> None:
        from eaiv.hil.replay import replay_csv, synthetic_imu_stream

        self._serial_pos = 0
        lines = [f"BOOT eaiv-sim firmware={self._flashed or '<none>'}"]
        dataset = self.sim.get("dataset")
        source = (
            replay_csv(dataset)
            if dataset
            else synthetic_imu_stream(duration_s=1.0, rate_hz=50, seed=0)
        )
        limit = int(self.sim.get("telemetry_lines", 50))
        for i, (t_s, values) in enumerate(source):
            if i >= limit:
                break
            fields = " ".join(f"{k}={v:.5f}" for k, v in sorted(values.items()))
            lines.append(f"T t={t_s:.4f} {fields}")
        lines.append("M heap=524288")
        lines.append("U boot_ms=42")
        lines.append("FAIL simulated-fault" if self.sim.get("fail") else "ALL_TESTS_OK")
        self._serial_log = lines

    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str:
        if cmd == "id":
            return "eaiv-sim v1"
        if cmd == "ping":
            return "pong"
        return f"ERR unknown command: {cmd}"

    def read_serial(self, duration_s: float) -> str:
        # Everything is already buffered; emulate a read draining the buffer.
        chunk = self._serial_log[self._serial_pos :]
        self._serial_pos = len(self._serial_log)
        return "\n".join(chunk) + ("\n" if chunk else "")

    def info(self) -> TargetInfo:
        return TargetInfo(
            name="sim", arch="virtual", clock_hz=100_000_000, flash_size_kb=2048, ram_size_kb=512
        )


if get_registry().get("target", "sim") is None:
    register_plugin(
        "sim",
        "target",
        "Software-simulated device for HIL testing (no hardware required)",
        version="1.0.0",
        supported_hardware=["*"],
    )(SimulatedTarget)
