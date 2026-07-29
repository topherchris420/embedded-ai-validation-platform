"""Environment diagnosis: what works, what does not, and how to fix it.

``eaiv doctor`` exists because "it didn't run" has a dozen causes — a
missing runtime, a toolchain not on PATH, a config pointing at a model
that was never downloaded, a report directory that is not writable. Each
check answers one of those questions and, when it fails, says what to
type next.

Nothing here connects to hardware or runs a validation; the whole
diagnosis is safe to run on a laptop, in CI, or inside a container.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

MIN_PYTHON = (3, 12)

#: Diagnostics never wait long on an external tool.
PROBE_TIMEOUT_S = 5.0


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @property
    def label(self) -> str:
        return {
            CheckStatus.OK: "OK",
            CheckStatus.WARN: "WARN",
            CheckStatus.FAIL: "FAIL",
            CheckStatus.SKIP: "SKIP",
        }[self]


@dataclass(frozen=True)
class Check:
    """One diagnosis result."""

    name: str
    status: CheckStatus
    detail: str = ""
    fix: str = ""
    category: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": str(self.status),
            "detail": self.detail,
            "fix": self.fix,
            "category": self.category,
        }


@dataclass
class Diagnosis:
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status is CheckStatus.FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status is CheckStatus.WARN]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def exit_code(self) -> int:
        """0 when everything required works, 1 when something is broken."""
        return 1 if self.failures else 0

    def by_category(self) -> dict[str, list[Check]]:
        grouped: dict[str, list[Check]] = {}
        for check in self.checks:
            grouped.setdefault(check.category, []).append(check)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": len(self.failures),
            "warnings": len(self.warnings),
            "checks": [c.to_dict() for c in self.checks],
        }


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _module_version(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return ""


def _probe(executable: str, *args: str) -> tuple[bool, str]:
    """Run ``executable args`` briefly to confirm it works. Never uses a shell."""
    path = shutil.which(executable)
    if path is None:
        return False, ""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv from the caller, no shell
            [path, *args],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{path} could not be executed: {exc}"
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    return True, (output[0] if output else path)


# -- individual checks -----------------------------------------------------


def check_python() -> Check:
    current = sys.version_info[:2]
    if current >= MIN_PYTHON:
        return Check(
            "Python version",
            CheckStatus.OK,
            f"{platform.python_version()} on {platform.system()} ({platform.machine()})",
            category="runtime",
        )
    return Check(
        "Python version",
        CheckStatus.FAIL,
        f"{platform.python_version()} is older than the required {MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        fix=f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ and reinstall eaiv in that interpreter.",
        category="runtime",
    )


def check_required_dependencies() -> list[Check]:
    required = {
        "yaml": ("PyYAML", "pip install pyyaml"),
        "numpy": ("NumPy", "pip install numpy"),
        "click": ("Click", "pip install click"),
        "rich": ("Rich", "pip install rich"),
        "serial": ("pyserial", "pip install pyserial"),
        "elftools": ("pyelftools", "pip install pyelftools"),
    }
    out: list[Check] = []
    for module, (label, fix) in required.items():
        available = _module_available(module)
        out.append(
            Check(
                f"Required dependency: {label}",
                CheckStatus.OK if available else CheckStatus.FAIL,
                "installed" if available else "not importable",
                fix="" if available else f"{fix} (or reinstall with: pip install -e .)",
                category="dependencies",
            )
        )
    return out


def check_optional_dependencies() -> list[Check]:
    optional = {
        "streamlit": ("Dashboard (streamlit)", 'pip install -e ".[dashboard]"', "dashboard"),
        "plotly": ("Dashboard charts (plotly)", 'pip install -e ".[dashboard]"', "dashboard"),
        "pandas": ("Dashboard tables (pandas)", 'pip install -e ".[dashboard]"', "dashboard"),
        "onnxruntime": ("ONNX runtime", 'pip install -e ".[tinyml]"', "tinyml"),
        "tflite_runtime": ("TFLite runtime", 'pip install -e ".[tinyml]"', "tinyml"),
        "pylink": ("J-Link support (pylink-square)", 'pip install -e ".[jlink]"', "hardware"),
    }
    out: list[Check] = []
    for module, (label, fix, category) in optional.items():
        available = _module_available(module)
        version = _module_version(module.replace("_", "-")) if available else ""
        out.append(
            Check(
                f"Optional: {label}",
                CheckStatus.OK if available else CheckStatus.WARN,
                f"installed{f' {version}' if version else ''}" if available else "not installed",
                fix="" if available else f"{fix} — needed only for {category} features.",
                category="dependencies",
            )
        )
    return out


def check_platformio() -> Check:
    found, detail = _probe("pio", "--version")
    if found:
        return Check("PlatformIO", CheckStatus.OK, detail, category="toolchain")
    return Check(
        "PlatformIO",
        CheckStatus.WARN,
        "'pio' is not on PATH",
        fix="pip install platformio — required only to build firmware (--build-env).",
        category="toolchain",
    )


def check_qemu() -> Check:
    for binary in ("qemu-system-arm", "qemu-system-aarch64"):
        found, detail = _probe(binary, "--version")
        if found:
            return Check("QEMU", CheckStatus.OK, detail, category="toolchain")
    return Check(
        "QEMU",
        CheckStatus.WARN,
        "no qemu-system-arm on PATH",
        fix=(
            "Install QEMU to use the 'qemu' target, or use target.kind: sim for a "
            "hardware-free run that needs no emulator."
        ),
        category="toolchain",
    )


def check_jlink() -> Check:
    for binary in ("JLinkExe", "JLink"):
        found, detail = _probe(binary, "-CommanderScript", os.devnull)
        if found:
            return Check("J-Link tooling", CheckStatus.OK, f"{binary} found", category="toolchain")
    if _module_available("pylink"):
        return Check(
            "J-Link tooling",
            CheckStatus.OK,
            "pylink-square installed (no JLinkExe on PATH)",
            category="toolchain",
        )
    return Check(
        "J-Link tooling",
        CheckStatus.WARN,
        "neither JLinkExe nor pylink-square found",
        fix='Install the Segger J-Link software and pip install -e ".[jlink]" to use jlink targets.',
        category="toolchain",
    )


def check_serial_ports() -> Check:
    if not _module_available("serial"):
        return Check(
            "Serial ports",
            CheckStatus.SKIP,
            "pyserial is not installed, so ports cannot be enumerated",
            fix="pip install pyserial",
            category="hardware",
        )
    try:
        from serial.tools import list_ports

        ports = list(list_ports.comports())
    except Exception as exc:  # noqa: BLE001 - enumeration is platform-specific
        return Check(
            "Serial ports",
            CheckStatus.WARN,
            f"could not enumerate ports: {exc}",
            category="hardware",
        )
    if not ports:
        return Check(
            "Serial ports",
            CheckStatus.WARN,
            "no serial devices detected",
            fix=(
                "Connect a board, or use target.kind: sim — every suite has a hardware-free "
                "path."
            ),
            category="hardware",
        )
    described = ", ".join(f"{p.device} ({p.description})" for p in ports[:5])
    return Check("Serial ports", CheckStatus.OK, described, category="hardware")


def check_plugins() -> list[Check]:
    from eaiv.cli import _load_all_plugins
    from eaiv.plugins import get_registry, load_entry_point_plugins

    try:
        _load_all_plugins()
        external = load_entry_point_plugins()
    except Exception as exc:  # noqa: BLE001 - a broken third-party plugin must be reported
        return [
            Check(
                "Plugin discovery",
                CheckStatus.FAIL,
                f"an external plugin failed to import: {exc}",
                fix="Uninstall or fix the plugin package advertising the 'eaiv.plugins' entry point.",
                category="plugins",
            )
        ]
    registry = get_registry()
    by_type: dict[str, int] = {}
    for meta in registry.list_plugins():
        by_type[meta.plugin_type] = by_type.get(meta.plugin_type, 0) + 1
    summary = ", ".join(f"{count} {name}" for name, count in sorted(by_type.items()))
    checks = [
        Check(
            "Plugin discovery",
            CheckStatus.OK if by_type else CheckStatus.FAIL,
            summary or "no plugins registered",
            fix="" if by_type else "Reinstall the package: pip install -e .",
            category="plugins",
        )
    ]
    if external:
        checks.append(
            Check(
                "External plugins",
                CheckStatus.OK,
                f"{external} entry-point plugin module(s) loaded",
                category="plugins",
            )
        )
    return checks


def check_report_dir(report_dir: str | Path = "reports") -> Check:
    directory = Path(report_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".doctor-", delete=True):
            pass
    except OSError as exc:
        return Check(
            "Report directory",
            CheckStatus.FAIL,
            f"{directory} is not writable: {exc}",
            fix=f"Create it or choose another: eaiv run --report-dir <path> (current: {directory})",
            category="storage",
        )
    return Check("Report directory", CheckStatus.OK, f"{directory.resolve()} is writable",
                 category="storage")


def check_config(config_path: str | Path) -> list[Check]:
    """Load and validate a config, reporting each problem it contains."""
    from eaiv.config import ConfigError, load_config
    from eaiv.configspec import validate_config

    path = Path(config_path)
    try:
        cfg = load_config(path)
    except ConfigError as exc:
        return [
            Check(
                f"Config: {path.name}",
                CheckStatus.FAIL,
                str(exc),
                fix="Fix the YAML, then re-run: eaiv config validate " + str(path),
                category="config",
            )
        ]

    result = validate_config(cfg.raw)
    checks: list[Check] = [
        Check(
            f"Config: {path.name}",
            CheckStatus.OK if result.ok else CheckStatus.FAIL,
            (
                f"loaded from {len(cfg.sources)} file(s); "
                f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)"
            ),
            fix="" if result.ok else f"eaiv config validate {path}",
            category="config",
        )
    ]
    for issue in result.errors[:10]:
        checks.append(
            Check(f"  {issue.path}", CheckStatus.FAIL, issue.message, issue.hint, "config")
        )
    for issue in result.warnings[:10]:
        checks.append(
            Check(f"  {issue.path}", CheckStatus.WARN, issue.message, issue.hint, "config")
        )
    return checks


def check_datasets(root: str | Path = "datasets") -> Check:
    directory = Path(root)
    if not directory.exists():
        return Check(
            "Replay datasets",
            CheckStatus.WARN,
            f"{directory} not found",
            fix="eaiv datasets generate --profile gentle --duration 20 -o datasets/imu/my_log.csv",
            category="storage",
        )
    csvs = sorted(directory.glob("**/*.csv"))
    if not csvs:
        return Check(
            "Replay datasets",
            CheckStatus.WARN,
            f"no CSV datasets under {directory}",
            fix="eaiv datasets generate --profile gentle --duration 20 -o datasets/imu/my_log.csv",
            category="storage",
        )
    return Check(
        "Replay datasets",
        CheckStatus.OK,
        f"{len(csvs)} dataset(s) under {directory}",
        category="storage",
    )


def run_diagnostics(
    config_path: str | Path | None = None,
    report_dir: str | Path = "reports",
    dataset_dir: str | Path = "datasets",
    include_hardware: bool = True,
) -> Diagnosis:
    """Run every check and return the collected diagnosis."""
    checks: list[Check] = [check_python()]
    checks += check_required_dependencies()
    checks += check_optional_dependencies()
    checks.append(check_platformio())
    checks.append(check_qemu())
    if include_hardware:
        checks.append(check_jlink())
        checks.append(check_serial_ports())
    checks += check_plugins()
    checks.append(check_report_dir(report_dir))
    checks.append(check_datasets(dataset_dir))
    if config_path is not None:
        checks += check_config(config_path)
    return Diagnosis(checks)


__all__ = [
    "MIN_PYTHON",
    "Check",
    "CheckStatus",
    "Diagnosis",
    "check_config",
    "check_datasets",
    "check_jlink",
    "check_platformio",
    "check_plugins",
    "check_python",
    "check_qemu",
    "check_report_dir",
    "check_serial_ports",
    "run_diagnostics",
]
