# Plugin Development Guide

Every extension point in the platform goes through one registry
(`eaiv.plugins`). A plugin is a **name + type + factory**: the factory
receives a config dict (usually a YAML fragment) and returns an instance
of the type's interface. Core code never needs modification.

## Plugin types

| Type | Interface | Built-ins | Config entry point |
|------|-----------|-----------|--------------------|
| `target` | `eaiv.plugins.targets.Target` | `qemu`, `serial`, `jlink`, `sim` | `target.kind` |
| `fusion_filter` | `update(dt, gyro, accel) -> Orientation` | `complementary`, `mahony`, `madgwick`, `kalman`, `ekf` | `sensor_fusion.algorithm` |
| `fault` | `eaiv.hil.Fault` | `noise`, `packet_loss`, `jitter`, `outage` | `hil.faults[].kind` |
| `power_monitor` | `eaiv.power.PowerMonitor` | `sim` | `tinyml.power.kind` |
| `telemetry_adapter` | `eaiv.telemetry.TelemetryAdapter` | `eaiv-line` | `eaiv monitor --adapter` |
| `suite` | `run() -> SuiteResult` | (none built-in) | `extra_suites.<name>` |
| `sensor` | `eaiv.plugins.sensors.Sensor` | (bases only) | — |
| `benchmark` | `eaiv.plugins.benchmarks.Benchmark` | (bases only) | — |

`eaiv plugins` lists everything currently registered.

## Writing a plugin

### 1. Decorate a class or factory

```python
from eaiv.plugins import register_plugin
from eaiv.plugins.targets import Target, TargetInfo

@register_plugin(
    "my_board",
    "target",
    "My board over vendor CLI",
    version="1.0.0",
    supported_hardware=["my-board-rev-a"],
)
class MyBoardTarget(Target):
    def __init__(self, spec: dict) -> None:
        super().__init__(spec)
        self.port = spec.get("my_board", {}).get("port", "/dev/ttyUSB0")

    def flash(self, binary: str) -> None: ...
    def reset(self) -> None: ...
    def run_command(self, cmd: str, timeout_s: float = 5.0) -> str: ...
    def read_serial(self, duration_s: float) -> str: ...
    def info(self) -> TargetInfo: ...
```

The factory contract is `Callable[[dict], T]` — a class taking one dict
works directly; use a function when construction needs translation:

```python
@register_plugin("ina226", "power_monitor", "INA226 over I2C")
def make_ina226(cfg: dict) -> PowerMonitor:
    return Ina226Monitor(bus=cfg.get("bus", 1), addr=cfg.get("addr", 0x40))
```

### 2. Use it from config

```yaml
target:
  kind: my_board
  my_board:
    port: /dev/ttyUSB1
```

### 3. Ship it (external packages)

Expose a module in the `eaiv.plugins` entry-point group; importing the
module must run the `register_plugin` decorators:

```toml
# your package's pyproject.toml
[project.entry-points."eaiv.plugins"]
my_board = "my_pkg.eaiv_plugins"
```

The CLI calls `eaiv.plugins.load_entry_point_plugins()` before resolving
names, so `pip install my-pkg` is all a user needs.

## Declaring metric provenance

A suite plugin's `SuiteResult` can declare where each metric came from.
Doing so is what keeps the platform honest: without it, metrics show up as
*origin unrecorded*, and the release verdict refuses to call the run
measured.

```python
from eaiv.core.metrics import MetricProvenance, MetricSource, metric_meta
from eaiv.core.results import SuiteResult


class MyThroughputSuite:
    def __init__(self, spec: dict) -> None:
        self.spec = spec

    def run(self) -> SuiteResult:
        metrics = {"packets_per_s": 4210.0, "estimated_queue_kb": 12.0}
        return SuiteResult(
            name="my_throughput",
            passed=metrics["packets_per_s"] > float(self.spec.get("min_pps", 1000)),
            metrics=metrics,
            notes="measured over a 10 s window on the device",
            metric_meta=metric_meta(
                metrics,
                MetricProvenance.MEASURED,          # the suite default
                MetricSource.DEVICE,
                overrides={                          # per-metric exceptions
                    "estimated_queue_kb": (
                        MetricProvenance.ESTIMATED,
                        MetricSource.STATIC_ANALYSIS,
                    )
                },
            ),
        )
```

| Provenance | Use it when |
|------------|-------------|
| `MEASURED` | the value is a real reading |
| `SIMULATED` | a software simulation produced it (QEMU counts) |
| `ESTIMATED` | it comes from a model or heuristic, not a reading |
| `MOCK` | a stand-in produced it; it describes the stand-in |

`metric_meta` fills in each metric's unit and direction by inference, so a
partial declaration never loses information. A metric labelled `MOCK` is
reported but never gates a release. `metric_meta` is optional and defaults
to empty — suites written before provenance existed keep working, their
metrics simply show as origin-unrecorded.

Two helpers save you from re-deriving the obvious:

```python
from eaiv.core.metrics import dataset_provenance, target_provenance

provenance, source = target_provenance(target.spec)   # sim/qemu -> simulated
provenance, source = dataset_provenance(csv_path)     # generated -> simulated
```

## Making a plugin visible in the mission builder

Choices in Mission Control come from the plugin registry, so a registered
plugin appears in the relevant dropdown with no UI change. What you supply
in `register_plugin` is what the user sees:

- `description` — shown next to the name in the Hardware & plugins
  inventory and as help text;
- `version` — shown in the inventory and recorded in every report's
  `meta.plugins`;
- `dependencies` — used to report availability; a plugin whose dependency
  is not importable is listed as *missing dependency* with the install
  command rather than silently failing at run time;
- `supported_hardware` — informational, listed in the inventory.

If your plugin needs configuration fields with their own labels, defaults,
and validation, add a `SectionSpec` to
[`eaiv/configspec/schema.py`](../src/eaiv/configspec/schema.py) — the same
declaration drives validation, the builder's form, and the configuration
reference. Fields with `choices_plugin="<type>"` enumerate the registry
rather than a hard-coded list.

## Emitting progress from a long-running plugin

If your suite runs long enough that a user would wonder whether it is
stuck, accept an optional event sink and emit progress. Keep the parameter
optional so the plugin stays usable from a plain synchronous call:

```python
from eaiv.runs import EventKind, EventSink, NullEventSink

class MySuite:
    def __init__(self, spec: dict, events: EventSink | None = None) -> None:
        self.spec = spec
        self.events = events or NullEventSink()
```

## Rules of the road

- **Determinism**: take a `seed` for anything random (see the fault
  models); identical config must produce identical behavior.
- **No global state**: read everything from the config dict passed to the
  factory. The registry itself is injectable — construct a private
  `PluginRegistry` in tests.
- **Fail loudly at build time**: raise `ValueError` from the factory on
  bad config; builders (`build_target`, `build_fault`, ...) type-check
  the result and list available plugins on unknown names.
- **Hardware-free test path**: every plugin needs a test that runs
  without hardware — pair a target plugin with a protocol transcript, a
  power monitor with a synthetic workload window.
- **Be honest about provenance**: if your suite's numbers come from a
  simulation, a heuristic, or a stand-in, say so in `metric_meta`. A
  simulated value presented as a hardware measurement is the one failure
  mode a validation tool cannot recover from.
- **No `shell=True`**: build subprocess argv as a list, validate any
  argument that comes from config, and set a timeout.

## Worked examples in-tree

- Target: `src/eaiv/hil/simulator.py` (`SimulatedTarget`)
- Fault: `src/eaiv/hil/faults.py` (four models + typed factories)
- Fusion filter: `src/eaiv/sensor_fusion/fusion.py`
- Power monitor: `src/eaiv/power/monitor.py`
- Telemetry adapter: `src/eaiv/telemetry/adapter.py`
