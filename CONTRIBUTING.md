# Contributing

Thanks for helping build the open-source reference platform for embedded AI
validation. This guide covers workflow, code standards, and how to add each
kind of component.

## Development setup

```bash
git clone https://github.com/topherchris420/embedded-ai-validation-platform.git
cd embedded-ai-validation-platform
pip install -e ".[all]"
pre-commit install        # optional but recommended
```

Verify your environment:

```bash
pytest tests/ -v
ruff check .
black --check .
eaiv run --config configs/sim.yaml --suite all   # no hardware required
```

## Code standards

- **Python ≥ 3.11**, type hints on public APIs, docstrings on modules and
  non-obvious functions.
- **Formatting/linting**: `black` and `ruff` (both enforced in CI),
  100-character lines.
- **C++ (firmware)**: header-only HAL style, `-Wall -Wextra` clean on all
  PlatformIO environments, no board-specific APIs outside
  `firmware/include/eaiv/board.h`.
- **No global state** beyond the default plugin registry; prefer
  constructor injection (see `Orchestrator`, `Simulator`).
- **Determinism**: anything random takes a `seed`; benchmarks and datasets
  must be reproducible bit-for-bit.

## Testing

- Every feature lands with tests; keep `pytest tests/ -q` green.
- Hardware-dependent code must have a hardware-free test path — use the
  `sim` target (`eaiv.hil.SimulatedTarget`) or a fake `Target` (see
  `tests/test_firmware.py`).
- Prefer testing observable behavior (suite results, CLI output, serial
  protocol) over internals.

## Adding components (plugin system)

All extension points go through `eaiv.plugins.register_plugin`; core code
never needs to be modified.

| Component | Plugin type | Interface | Reference |
|-----------|-------------|-----------|-----------|
| Board/target | `target` | `eaiv.plugins.targets.Target` | `src/eaiv/targets/` |
| Fusion algorithm | `fusion_filter` | `update(dt, gyro, accel) -> Orientation` | `src/eaiv/sensor_fusion/fusion.py` |
| Fault model | `fault` | `eaiv.hil.Fault` | `src/eaiv/hil/faults.py` |
| Sensor | `sensor` | `eaiv.plugins.sensors.Sensor` | `src/eaiv/plugins/sensors.py` |
| Benchmark | `benchmark` | `eaiv.plugins.benchmarks.Benchmark` | `src/eaiv/plugins/benchmarks.py` |

External packages can ship plugins by exposing a module in the
`eaiv.plugins` entry-point group; it is imported (and thus registered) by
`eaiv.plugins.load_entry_point_plugins()`.

Adding a **firmware board** is config-only: see "Adding a board" in
[firmware/README.md](firmware/README.md).

## Pull requests

1. Branch from `main`; keep PRs focused — one feature or fix each.
2. Use [Conventional Commits](https://www.conventionalcommits.org/)
   subjects (`feat:`, `fix:`, `docs:`, `refactor:`, `style:`, `test:`).
3. Update documentation and `configs/*.yaml` examples affected by your
   change.
4. CI must pass: lint, tests, and (for firmware changes) all PlatformIO
   builds.

## Reporting issues

Include: board/target kind, config file (redacted as needed), full CLI
output, and `reports/latest.json` when a suite misbehaves.
