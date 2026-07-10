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

## Worked examples in-tree

- Target: `src/eaiv/hil/simulator.py` (`SimulatedTarget`)
- Fault: `src/eaiv/hil/faults.py` (four models + typed factories)
- Fusion filter: `src/eaiv/sensor_fusion/fusion.py`
- Power monitor: `src/eaiv/power/monitor.py`
- Telemetry adapter: `src/eaiv/telemetry/adapter.py`
