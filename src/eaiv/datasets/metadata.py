"""Dataset metadata schema, sidecar I/O, and validation.

Every replay dataset carries a ``<name>.metadata.json`` sidecar next to
its CSV describing what was recorded, at what rate, with what ground
truth, under which license — so a dataset is usable (and auditable)
without reading the code that produced it.

Domains are free-form but the conventional values are:
``imu``, ``robotics``, ``navigation``, ``wearables``, ``industrial``.

    eaiv datasets validate datasets/imu/imu_run1.csv
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class SensorInfo:
    """One sensor's contribution to the CSV columns."""

    name: str  # e.g. "gyroscope"
    fields: list[str]  # e.g. ["gx", "gy", "gz"]
    units: str  # e.g. "rad/s"


@dataclass
class DatasetMetadata:
    name: str
    description: str
    domain: str
    sampling_rate_hz: float
    sensors: list[SensorInfo] = field(default_factory=list)
    ground_truth: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    license: str = "MIT"
    generator: dict = field(default_factory=dict)  # seed/profile for reproducibility
    schema_version: int = SCHEMA_VERSION

    def all_fields(self) -> list[str]:
        out: list[str] = []
        for sensor in self.sensors:
            out.extend(sensor.fields)
        out.extend(self.ground_truth)
        return out


def sidecar_path(csv_path: str | Path) -> Path:
    p = Path(csv_path)
    return p.with_name(p.stem + ".metadata.json")


def write_metadata(meta: DatasetMetadata, csv_path: str | Path) -> Path:
    path = sidecar_path(csv_path)
    path.write_text(json.dumps(asdict(meta), indent=2) + "\n")
    return path


def read_metadata(csv_path: str | Path) -> DatasetMetadata:
    path = sidecar_path(csv_path)
    raw = json.loads(path.read_text())
    raw["sensors"] = [SensorInfo(**s) for s in raw.get("sensors", [])]
    return DatasetMetadata(**raw)


def validate_dataset(csv_path: str | Path, rate_tolerance: float = 0.05) -> list[str]:
    """Check a dataset CSV against its metadata sidecar.

    Returns a list of problems; empty means valid. Checks: sidecar exists
    and parses, required fields are present, every declared column exists
    in the CSV, timestamps are strictly monotonic, and the observed sample
    rate matches the declared one within ``rate_tolerance``.
    """
    csv_p = Path(csv_path)
    problems: list[str] = []
    if not csv_p.exists():
        return [f"{csv_p}: file not found"]
    if not sidecar_path(csv_p).exists():
        return [f"{csv_p}: missing metadata sidecar {sidecar_path(csv_p).name}"]

    try:
        meta = read_metadata(csv_p)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        return [f"{csv_p}: unreadable metadata: {e}"]

    for attr in ("name", "description", "domain", "license", "version"):
        if not getattr(meta, attr):
            problems.append(f"{csv_p}: metadata field {attr!r} is empty")
    if meta.sampling_rate_hz <= 0:
        problems.append(f"{csv_p}: sampling_rate_hz must be positive")
    if meta.schema_version > SCHEMA_VERSION:
        problems.append(
            f"{csv_p}: schema_version {meta.schema_version} newer than supported {SCHEMA_VERSION}"
        )

    import csv as csv_mod

    with csv_p.open(newline="") as f:
        reader = csv_mod.DictReader(f)
        columns = set(reader.fieldnames or [])
        timestamps: list[float] = []
        rows = 0
        for row in reader:
            rows += 1
            try:
                timestamps.append(float(row["t_s"]))
            except (KeyError, ValueError):
                pass

    if "t_s" not in columns:
        problems.append(f"{csv_p}: missing required column 't_s'")
    missing = [c for c in meta.all_fields() if c not in columns]
    if missing:
        problems.append(f"{csv_p}: declared columns missing from CSV: {missing}")
    if rows == 0:
        problems.append(f"{csv_p}: no data rows")

    if len(timestamps) >= 2:
        if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
            problems.append(f"{csv_p}: timestamps are not strictly monotonic")
        observed = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
        declared = meta.sampling_rate_hz
        if declared > 0 and abs(observed - declared) / declared > rate_tolerance:
            problems.append(
                f"{csv_p}: observed rate {observed:.2f} Hz deviates from "
                f"declared {declared:.2f} Hz by more than {rate_tolerance:.0%}"
            )
    return problems


def imu_metadata(
    name: str,
    description: str,
    sampling_rate_hz: float,
    generator: dict | None = None,
    with_ground_truth: bool = True,
) -> DatasetMetadata:
    """Metadata for the platform's standard IMU replay schema."""
    return DatasetMetadata(
        name=name,
        description=description,
        domain="imu",
        sampling_rate_hz=sampling_rate_hz,
        sensors=[
            SensorInfo(name="gyroscope", fields=["gx", "gy", "gz"], units="rad/s"),
            SensorInfo(name="accelerometer", fields=["ax", "ay", "az"], units="g"),
        ],
        ground_truth=["roll_ref_deg", "pitch_ref_deg"] if with_ground_truth else [],
        generator=generator or {},
    )
