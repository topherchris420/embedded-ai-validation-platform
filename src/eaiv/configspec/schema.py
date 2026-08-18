"""Declarative description of the eaiv configuration.

YAML stays the source of truth; this module says what the YAML *means* —
which sections exist, which fields they accept, what each field does,
what a sensible default is, and which choices are legal. That single
description drives three things at once: field-level validation, the
mission builder's form, and the configuration reference in the docs.

Choices that come from the plugin registry (target kinds, fusion
algorithms, fault models, power monitors, telemetry adapters) are
declared as a plugin *type*, never as a hard-coded list, so a target
contributed by a third-party package appears in the UI the moment it is
installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    PATH = "path"
    ENUM = "enum"
    LIST = "list"
    MAPPING = "mapping"


@dataclass(frozen=True)
class FieldSpec:
    """One configurable field inside a section."""

    key: str
    label: str
    type: FieldType = FieldType.STRING
    default: Any = None
    description: str = ""
    required: bool = False
    choices: tuple[str, ...] = ()
    #: Plugin type whose registered names are the legal values.
    choices_plugin: str = ""
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    #: When set, the field only applies for these ``target.kind`` values.
    target_kinds: tuple[str, ...] = ()
    #: Hidden behind "advanced" in the mission builder.
    advanced: bool = False
    #: Shown as placeholder/help text.
    example: str = ""

    @property
    def dotted(self) -> str:
        return self.key


@dataclass(frozen=True)
class SectionSpec:
    """A top-level config section, usually one validation suite's settings."""

    name: str
    title: str
    description: str
    fields: tuple[FieldSpec, ...] = ()
    #: Suite selector this section configures (``eaiv run --suite <x>``).
    suite: str = ""
    #: Free-form mapping sections (``extra_suites``) accept any key.
    free_form: bool = False

    def field(self, key: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.key == key), None)


TARGET_SECTION = SectionSpec(
    name="target",
    title="Target",
    description=(
        "The device under validation. Every suite that needs hardware talks to it through "
        "this one backend, so switching from the simulator to a board is a config change."
    ),
    fields=(
        FieldSpec(
            key="kind",
            label="Target backend",
            type=FieldType.ENUM,
            default="sim",
            required=True,
            choices_plugin="target",
            description="Which target plugin drives the device.",
        ),
        FieldSpec(
            key="binary",
            label="Firmware binary",
            type=FieldType.PATH,
            default="build/firmware.elf",
            description="Firmware flashed before firmware/telemetry runs.",
            example="firmware/.pio/build/esp32/firmware.elf",
        ),
        FieldSpec(
            key="serial.port",
            label="Serial port",
            type=FieldType.STRING,
            default="/dev/ttyACM0",
            description="Device node the board enumerates as.",
            target_kinds=("serial",),
            example="/dev/ttyACM0 or COM5",
        ),
        FieldSpec(
            key="serial.baud",
            label="Baud rate",
            type=FieldType.INTEGER,
            default=115200,
            minimum=1200,
            description="Must match the firmware's UART configuration.",
            target_kinds=("serial",),
        ),
        FieldSpec(
            key="jlink.device",
            label="J-Link device",
            type=FieldType.STRING,
            default="STM32H743VI",
            description="Segger device identifier for the MCU.",
            target_kinds=("jlink",),
        ),
        FieldSpec(
            key="jlink.interface",
            label="Debug interface",
            type=FieldType.ENUM,
            default="swd",
            choices=("swd", "jtag"),
            target_kinds=("jlink",),
            description="Wiring between the probe and the MCU.",
        ),
        FieldSpec(
            key="qemu.machine",
            label="QEMU machine",
            type=FieldType.STRING,
            default="mps2-an385",
            target_kinds=("qemu",),
            description="Board model QEMU emulates.",
        ),
        FieldSpec(
            key="qemu.cpu",
            label="QEMU CPU",
            type=FieldType.STRING,
            default="cortex-m3",
            target_kinds=("qemu",),
            description="Core QEMU emulates.",
        ),
        FieldSpec(
            key="sim.dataset",
            label="Simulator dataset",
            type=FieldType.PATH,
            description="Replay log the simulated device streams; synthetic when empty.",
            target_kinds=("sim",),
            example="datasets/imu/imu_run1.csv",
        ),
        FieldSpec(
            key="sim.telemetry_lines",
            label="Simulated telemetry lines",
            type=FieldType.INTEGER,
            default=50,
            minimum=1,
            maximum=100000,
            target_kinds=("sim",),
            description="How many telemetry lines the simulated device emits per boot.",
        ),
        FieldSpec(
            key="sim.fail",
            label="Force a failing device",
            type=FieldType.BOOLEAN,
            default=False,
            target_kinds=("sim",),
            advanced=True,
            description="Makes the simulated device report FAIL — for exercising failure paths.",
        ),
    ),
)

FIRMWARE_SECTION = SectionSpec(
    name="firmware",
    title="Firmware smoke test",
    suite="firmware",
    description="Flash, boot, and watch the serial stream for pass/fail patterns.",
    fields=(
        FieldSpec(
            key="timeout_s",
            label="Serial read timeout",
            type=FieldType.FLOAT,
            default=30.0,
            unit="s",
            minimum=0.1,
            description="How long to watch the boot output for a verdict.",
        ),
        FieldSpec(
            key="retries",
            label="Retries",
            type=FieldType.INTEGER,
            default=2,
            minimum=0,
            maximum=10,
            description="Extra flash+boot attempts before declaring failure.",
        ),
        FieldSpec(
            key="pass_patterns",
            label="Pass patterns",
            type=FieldType.LIST,
            default=["PASS", "ALL_TESTS_OK"],
            description="Any of these substrings in the output means success.",
        ),
        FieldSpec(
            key="fail_patterns",
            label="Fail patterns",
            type=FieldType.LIST,
            default=["FAIL", "ASSERT"],
            description="Any of these ends the attempt immediately as a failure.",
        ),
    ),
)

TINYML_SECTION = SectionSpec(
    name="tinyml",
    title="TinyML benchmark",
    suite="tinyml",
    description=(
        "Latency distribution, throughput, startup cost, and output stability for a "
        "model. Runs on the host runtime — results are host measurements, not on-device."
    ),
    fields=(
        FieldSpec(
            key="model",
            label="Model file",
            type=FieldType.PATH,
            default="",
            description=".tflite or .onnx model; a mock runtime is used when absent.",
            example="models/mobilenet_v1_0.25_128_int8.tflite",
        ),
        FieldSpec(
            key="runtime",
            label="Runtime",
            type=FieldType.ENUM,
            default="mock",
            choices=("tflite", "onnx", "mock"),
            description="Inference backend. 'mock' produces clearly-labelled stand-in timings.",
        ),
        FieldSpec(
            key="iterations",
            label="Timed iterations",
            type=FieldType.INTEGER,
            default=50,
            minimum=1,
            maximum=100000,
            description="Samples in the latency distribution. More iterations, tighter tails.",
        ),
        FieldSpec(
            key="warmup",
            label="Warm-up iterations",
            type=FieldType.INTEGER,
            default=5,
            minimum=0,
            description="Discarded before timing, to exclude first-call allocation costs.",
        ),
        FieldSpec(
            key="inputs",
            label="Input tensor file",
            type=FieldType.PATH,
            advanced=True,
            description="Optional .npy sample; random input of the right shape when absent.",
        ),
        FieldSpec(
            key="power.kind",
            label="Power monitor",
            type=FieldType.ENUM,
            choices_plugin="power_monitor",
            advanced=True,
            description="Adds mean/peak power and energy per inference. 'sim' is synthetic.",
        ),
        FieldSpec(
            key="power.active_mw",
            label="Simulated active power",
            type=FieldType.FLOAT,
            default=150.0,
            unit="mW",
            advanced=True,
            description="Set-point for the simulated monitor.",
        ),
        FieldSpec(
            key="power.shunt_ohms",
            label="INA226 Shunt Resistor",
            type=FieldType.FLOAT,
            default=0.1,
            unit="Ω",
            advanced=True,
            description="Shunt resistor value for INA226 power monitor.",
        ),
        FieldSpec(
            key="power.address",
            label="INA226 I2C Address",
            type=FieldType.INTEGER,
            default=0x40,
            advanced=True,
            description="I2C device address for INA226.",
        ),
        FieldSpec(
            key="power.port",
            label="PPK2 Serial Port",
            type=FieldType.STRING,
            default="mock",
            advanced=True,
            description="Virtual COM port for Nordic PPK2 (e.g. COM3, /dev/ttyACM0).",
        ),
        FieldSpec(
            key="power.mode",
            label="PPK2 Power Mode",
            type=FieldType.ENUM,
            default="source",
            choices=("source", "ampere"),
            advanced=True,
            description="PPK2 operation mode: 'source' (supplies VDD) or 'ampere' (measures inline).",
        ),
        FieldSpec(
            key="power.vdd_v",
            label="PPK2 Output Voltage",
            type=FieldType.FLOAT,
            default=3.3,
            unit="V",
            minimum=0.8,
            maximum=5.0,
            advanced=True,
            description="Target voltage supplied in PPK2 source mode (0.8V - 5.0V).",
        ),
    ),
)

MEMORY_SECTION = SectionSpec(
    name="memory",
    title="Memory footprint",
    suite="memory",
    description="Static ROM/RAM analysis of the ELF plus model flash cost, with budget gates.",
    fields=(
        FieldSpec(
            key="binary",
            label="ELF binary",
            type=FieldType.PATH,
            description="ELF to analyse; the suite is skipped when it is missing.",
            example="firmware/.pio/build/esp32/firmware.elf",
        ),
        FieldSpec(
            key="model",
            label="Model file",
            type=FieldType.PATH,
            description="Counted as additional flash cost alongside the firmware.",
        ),
        FieldSpec(
            key="max_rom_kb",
            label="ROM budget",
            type=FieldType.FLOAT,
            unit="KB",
            minimum=0,
            description="Fails the suite when .text+.rodata+.data exceeds this.",
        ),
        FieldSpec(
            key="max_ram_kb",
            label="Static RAM budget",
            type=FieldType.FLOAT,
            unit="KB",
            minimum=0,
            description="Fails the suite when .data+.bss exceeds this. Excludes heap/stack.",
        ),
        FieldSpec(
            key="require",
            label="Require the binary",
            type=FieldType.BOOLEAN,
            default=False,
            description="When true, a missing ELF fails the suite instead of skipping it.",
        ),
    ),
)

FUSION_SECTION = SectionSpec(
    name="sensor_fusion",
    title="Sensor fusion accuracy",
    suite="fusion",
    description="Replay a recorded IMU log through a fusion filter and score it against truth.",
    fields=(
        FieldSpec(
            key="source",
            label="Replay dataset",
            type=FieldType.PATH,
            default="datasets/imu/imu_run1.csv",
            required=True,
            description="CSV with t_s, gyro, accel and optional ground-truth columns.",
        ),
        FieldSpec(
            key="algorithm",
            label="Fusion algorithm",
            type=FieldType.ENUM,
            default="ekf",
            choices_plugin="fusion_filter",
            description="Filter under test.",
        ),
        FieldSpec(
            key="params",
            label="Filter parameters",
            type=FieldType.MAPPING,
            default={},
            advanced=True,
            description="Forwarded to the filter constructor, e.g. {beta: 0.2}.",
        ),
        FieldSpec(
            key="max_rmse_deg",
            label="Max orientation RMSE",
            type=FieldType.FLOAT,
            default=10.0,
            unit="°",
            minimum=0,
            description="Roll/pitch RMSE above this fails the suite.",
        ),
        FieldSpec(
            key="sample_rate_hz",
            label="Sample rate",
            type=FieldType.FLOAT,
            default=200.0,
            unit="Hz",
            advanced=True,
            description="Declared rate of the source log; used for reporting.",
        ),
        FieldSpec(
            key="metrics",
            label="Metrics",
            type=FieldType.LIST,
            default=["rmse", "drift_deg_per_min", "lag_ms"],
            advanced=True,
            description="Which scores to compute.",
        ),
    ),
)

HIL_SECTION = SectionSpec(
    name="hil",
    title="Fault robustness (HIL)",
    suite="hil",
    description=(
        "Replay a dataset twice — clean and through a fault chain — and measure how much "
        "accuracy degrades. Every fault is injected in software and is deterministic per seed."
    ),
    fields=(
        FieldSpec(
            key="source",
            label="Replay dataset",
            type=FieldType.PATH,
            default="datasets/imu/imu_run1.csv",
            required=True,
            description="Stream the fault chain is applied to.",
        ),
        FieldSpec(
            key="algorithm",
            label="Fusion algorithm",
            type=FieldType.ENUM,
            default="madgwick",
            choices_plugin="fusion_filter",
            description="Filter whose robustness is under test.",
        ),
        FieldSpec(
            key="params",
            label="Filter parameters",
            type=FieldType.MAPPING,
            default={},
            advanced=True,
            description="Forwarded to the filter constructor.",
        ),
        FieldSpec(
            key="faults",
            label="Fault chain",
            type=FieldType.LIST,
            default=[],
            description="Ordered fault specs, each {kind: ..., ...}.",
        ),
        FieldSpec(
            key="max_faulted_rmse_deg",
            label="Max faulted RMSE",
            type=FieldType.FLOAT,
            default=15.0,
            unit="°",
            minimum=0,
            description="Orientation error under faults above this fails the suite.",
        ),
    ),
)

RT_SECTION = SectionSpec(
    name="rt_perf",
    title="Real-time deadlines",
    suite="rt",
    description=(
        "Worst-case execution time, release jitter, and deadline misses per periodic task. "
        "Without device task telemetry the suite falls back to a clearly-labelled synthetic trace."
    ),
    fields=(
        FieldSpec(
            key="task_set",
            label="Task set",
            type=FieldType.LIST,
            default=[],
            required=True,
            description="Tasks to profile: name, period_ms, deadline_ms, wcet_budget_ms.",
        ),
        FieldSpec(
            key="duration_s",
            label="Profiling window",
            type=FieldType.FLOAT,
            default=60.0,
            unit="s",
            minimum=0.01,
            description="How long to collect task telemetry.",
        ),
    ),
)

REPORTING_SECTION = SectionSpec(
    name="reporting",
    title="Reporting",
    description="Where artifacts land and which formats are produced.",
    fields=(
        FieldSpec(
            key="out_dir",
            label="Report directory",
            type=FieldType.STRING,
            default="reports/",
            description="Root for run directories and the legacy latest.json pointer.",
        ),
        FieldSpec(
            key="format",
            label="Formats",
            type=FieldType.LIST,
            default=["console", "json", "html"],
            advanced=True,
            description="Informational: all formats are always written.",
        ),
    ),
)

EXTRA_SUITES_SECTION = SectionSpec(
    name="extra_suites",
    title="Plugin suites",
    description="Suites contributed by plugins, keyed by their registered name.",
    free_form=True,
)

MISSION_SECTION = SectionSpec(
    name="mission",
    title="Mission",
    description=(
        "Run intent saved alongside the configuration: which preset it came from, which "
        "suites to run, which baseline to gate against. Ignored by the suites themselves."
    ),
    free_form=True,
)

SCHEMA: tuple[SectionSpec, ...] = (
    TARGET_SECTION,
    FIRMWARE_SECTION,
    TINYML_SECTION,
    MEMORY_SECTION,
    FUSION_SECTION,
    HIL_SECTION,
    RT_SECTION,
    REPORTING_SECTION,
    EXTRA_SUITES_SECTION,
    MISSION_SECTION,
)

SECTIONS_BY_NAME: dict[str, SectionSpec] = {s.name: s for s in SCHEMA}


def section_for_suite(suite: str) -> SectionSpec | None:
    return next((s for s in SCHEMA if s.suite == suite), None)


def plugin_choices(plugin_type: str) -> list[str]:
    """Registered plugin names of a type, sorted — the UI's option list."""
    from eaiv.plugins import get_registry

    return sorted(p.name for p in get_registry().list_plugins(plugin_type))


def field_choices(spec: FieldSpec) -> list[str]:
    """Legal values for a field, resolved through the registry if needed."""
    if spec.choices_plugin:
        return plugin_choices(spec.choices_plugin)
    return list(spec.choices)


def fields_for_target(kind: str, include_advanced: bool = True) -> list[FieldSpec]:
    """Target fields relevant to one backend, hiding the rest."""
    out = []
    for spec in TARGET_SECTION.fields:
        if spec.target_kinds and kind not in spec.target_kinds:
            continue
        if spec.advanced and not include_advanced:
            continue
        out.append(spec)
    return out


def get_nested(data: dict[str, Any], dotted: str) -> Any:
    """Read ``a.b.c`` out of nested mappings, returning None when absent."""
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def set_nested(data: dict[str, Any], dotted: str, value: Any) -> None:
    """Write ``a.b.c`` into nested mappings, creating intermediate dicts."""
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def default_config(target_kind: str = "sim") -> dict[str, Any]:
    """A complete, valid configuration built from schema defaults.

    This is what makes "launch the dashboard and run a validation" work
    without editing YAML: the mission builder starts from here.
    """
    raw: dict[str, Any] = {}
    for section in SCHEMA:
        if section.free_form:
            continue
        body: dict[str, Any] = {}
        for spec in section.fields:
            if spec.default is None:
                continue
            if (
                section.name == "target"
                and spec.target_kinds
                and target_kind not in spec.target_kinds
            ):
                continue
            value = spec.default
            set_nested(body, spec.key, list(value) if isinstance(value, list) else value)
        if body:
            raw[section.name] = body
    set_nested(raw, "target.kind", target_kind)
    return raw


@dataclass
class SectionView:
    """A section paired with the values a config currently holds."""

    spec: SectionSpec
    values: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "EXTRA_SUITES_SECTION",
    "FIRMWARE_SECTION",
    "FUSION_SECTION",
    "HIL_SECTION",
    "MEMORY_SECTION",
    "MISSION_SECTION",
    "REPORTING_SECTION",
    "RT_SECTION",
    "SCHEMA",
    "SECTIONS_BY_NAME",
    "TARGET_SECTION",
    "TINYML_SECTION",
    "FieldSpec",
    "FieldType",
    "SectionSpec",
    "SectionView",
    "default_config",
    "field_choices",
    "fields_for_target",
    "get_nested",
    "plugin_choices",
    "section_for_suite",
    "set_nested",
]
