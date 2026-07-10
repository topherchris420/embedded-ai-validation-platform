"""Helpers for inspecting ELF binaries: sections, loadable segments, sizes."""

from __future__ import annotations

from pathlib import Path

from elftools.elf.elffile import ELFFile  # type: ignore


def elf_sections(path: str) -> list[dict]:
    """Return non-empty sections with name/address/size — useful for a
    quick ROM/RAM footprint sanity check before flashing."""
    p = Path(path)
    with p.open("rb") as f:
        elf = ELFFile(f)
        return [
            {"name": s.name, "addr": s["sh_addr"], "size": s["sh_size"]}
            for s in elf.iter_sections()
            if s["sh_size"] > 0
        ]


def flash_regions(path: str) -> list[tuple[int, int, bytes]]:
    """Return (address, size, data) tuples for each PT_LOAD segment."""
    p = Path(path)
    regions: list[tuple[int, int, bytes]] = []
    with p.open("rb") as f:
        elf = ELFFile(f)
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            regions.append((seg["p_paddr"], seg["p_memsz"], seg.data()))
    return regions


def footprint_summary(path: str) -> dict:
    """Rough ROM (.text + .rodata + .data) / RAM (.data + .bss) totals."""
    sections = {s["name"]: s["size"] for s in elf_sections(path)}
    rom = sections.get(".text", 0) + sections.get(".rodata", 0) + sections.get(".data", 0)
    ram = sections.get(".data", 0) + sections.get(".bss", 0)
    return {"rom_bytes": rom, "ram_bytes": ram, "sections": sections}
