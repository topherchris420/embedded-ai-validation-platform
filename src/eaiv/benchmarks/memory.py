"""Static memory-footprint benchmark: ELF ROM/RAM plus model storage.

Fully static analysis — nothing is flashed or executed — so it runs in CI
on every build. Config:

    memory:
      binary: firmware/.pio/build/esp32/firmware.elf
      model: models/net.tflite         # optional; adds model flash cost
      max_rom_kb: 512                  # optional pass thresholds
      max_ram_kb: 128
      require: false                   # true => missing binary fails
"""

from __future__ import annotations

from pathlib import Path

from eaiv.core.results import SuiteResult
from eaiv.firmware.flasher import footprint_summary


class MemoryBenchmark:
    def __init__(self, spec: dict) -> None:
        self.spec = spec

    def run(self) -> SuiteResult:
        binary = self.spec.get("binary", "")
        require = bool(self.spec.get("require", False))

        if not binary or not Path(binary).exists():
            if require:
                return SuiteResult(
                    name="memory",
                    passed=False,
                    metrics={},
                    notes=f"binary not found: {binary!r}",
                )
            return SuiteResult(
                name="memory",
                passed=True,
                metrics={"skipped": True},
                notes=f"skipped: binary not found ({binary!r}); set memory.require to enforce",
            )

        try:
            footprint = footprint_summary(binary)
        except Exception as e:  # noqa: BLE001 - malformed ELFs must not crash the run
            return SuiteResult(
                name="memory", passed=False, metrics={}, notes=f"ELF analysis failed: {e}"
            )

        rom_kb = footprint["rom_bytes"] / 1024.0
        ram_kb = footprint["ram_bytes"] / 1024.0
        metrics: dict = {
            "rom_kb": round(rom_kb, 2),
            "ram_static_kb": round(ram_kb, 2),
        }

        model = self.spec.get("model", "")
        model_path = Path(model) if model else None
        if model_path is not None and model_path.exists():
            model_kb = model_path.stat().st_size / 1024.0
            metrics["model_flash_kb"] = round(model_kb, 2)
            metrics["total_flash_kb"] = round(rom_kb + model_kb, 2)

        passed = True
        max_rom = self.spec.get("max_rom_kb")
        if max_rom is not None and rom_kb > float(max_rom):
            passed = False
        max_ram = self.spec.get("max_ram_kb")
        if max_ram is not None and ram_kb > float(max_ram):
            passed = False

        top = sorted(footprint["sections"].items(), key=lambda kv: kv[1], reverse=True)[:5]
        notes = "largest sections: " + ", ".join(f"{name}={size // 1024}KB" for name, size in top)
        return SuiteResult(name="memory", passed=passed, metrics=metrics, notes=notes)
