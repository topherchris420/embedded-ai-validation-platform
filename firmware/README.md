# Firmware Module

PlatformIO-based validation firmware buildable for every supported board.

## Structure

```
firmware/
├── platformio.ini            # One [env:*] section per board
├── include/eaiv/             # Hardware abstraction layer (header-only)
│   ├── board.h               # Board info, monotonic clock, heap probe
│   ├── imu.h                 # IImu interface + deterministic SyntheticImu
│   └── complementary_filter.h# C++ mirror of the Python reference filter
└── src/
    └── main.cpp              # Validation app (serial test protocol)
```

## Building

```bash
pip install platformio
cd firmware
pio run -e esp32        # or: esp32-s3 | stm32h7 | pico
pio run -e esp32 -t upload
```

All four environments are built in CI on every firmware change.

## Serial test protocol

The firmware speaks the protocol consumed by
`eaiv.firmware.tester.FirmwareTester` (and mirrored by the HIL
`SimulatedTarget`):

```
BOOT eaiv-fw board=esp32 cpu_hz=240000000 heap=294976
T t=0.0000 gx=0.32899 gy=0.08541 gz=0.00274 ax=0.00000 ay=0.00000 az=1.00000 roll=0.000 pitch=0.000
...
ALL_TESTS_OK            # or: FAIL <reason>
```

Self-tests run at boot: monotonic clock sanity, heap allocation, and
convergence of the complementary filter from a cold start. After the
verdict, the firmware answers line commands:

| Command | Response |
|---------|----------|
| `id`     | `eaiv-fw v<version> board=<name>` |
| `ping`   | `pong` |
| `bench`  | `B iters=1000 us_per_update=<mean> max_us=<max>` |
| `mem`    | `M heap=<bytes>` |
| `uptime` | `U ms=<ms>` |

One `M` line and one `U boot_ms=<ms>` line are also emitted right before
the boot verdict, so a single boot capture carries free memory and startup
time; `eaiv monitor --summary` surfaces them via `eaiv.telemetry`.

`bench` times the sensor-fusion update loop on-device, giving a real
per-board latency figure comparable across hardware.

## Cross-validation with the Python stack

`SyntheticImu` generates exactly the noise-free "gentle" trajectory of
`eaiv.datasets.generate_imu_trajectory`, and `ComplementaryFilter` mirrors
`eaiv.sensor_fusion.fusion.ComplementaryFilter`. Telemetry captured from a
device can therefore be scored against the Python reference
sample-for-sample.

## Adding a board

1. Add an `[env:<name>]` section to `platformio.ini` with the right
   `platform`/`board` pair and a `-DEAIV_BOARD_NAME=\"<name>\"` flag.
2. If the Arduino core lacks `F_CPU`, extend `eaiv::cpu_hz()` in
   `include/eaiv/board.h`.
3. Add the environment to `.github/workflows/firmware.yml`.

No application code changes are required.
