# Supported Hardware

## Boards

| Board | MCU / Arch | Firmware env | Status |
|-------|------------|--------------|--------|
| ESP32 | Xtensa LX6 dual-core @ 240 MHz | `esp32` | ✅ builds in CI |
| ESP32-S3 | Xtensa LX7 dual-core @ 240 MHz + vector extensions | `esp32-s3` | ✅ builds in CI |
| STM32H743 (Nucleo-H743ZI) | ARM Cortex-M7 @ 480 MHz | `stm32h7` | ✅ builds in CI |
| Raspberry Pi Pico | RP2040 dual Cortex-M0+ @ 133 MHz | `pico` | ✅ builds in CI |
| Raspberry Pi Zero 2 W | quad Cortex-A53 (Linux) | — | 🔜 needs SSH target backend ([roadmap](../ROADMAP.md)) |

"Builds in CI" means the validation firmware compiles for the board on
every firmware change. Flashing and on-device runs require the matching
target backend below and a connected board.

## Target backends (host ↔ device transports)

| Kind | Transport | Hardware needed | Typical use |
|------|-----------|-----------------|-------------|
| `sim` | in-process simulation | none | CI, development, HIL fault testing |
| `qemu` | `qemu-system-arm` stdio | none (system QEMU) | Cortex-M binaries without a board |
| `serial` | UART (pyserial) | any board | ESP32/Pico via USB-serial |
| `jlink` | SWD via pylink/JLinkExe | J-Link probe | STM32 flash + debug |

## Adding a board

1. **Firmware**: add an `[env:<name>]` section to `firmware/platformio.ini`
   (platform + board + `-DEAIV_BOARD_NAME` flag) and list the env in
   `.github/workflows/firmware.yml`. The application code is board-agnostic.
2. **Host side**: if an existing transport fits (most boards are `serial`),
   no code is needed — just a `configs/<board>.yaml`. Otherwise register a
   new `target` plugin implementing `eaiv.plugins.targets.Target`.
3. Add a config example and, ideally, a HIL/sim smoke test.

## Sensors

The firmware HAL defines `eaiv::IImu` (see `firmware/include/eaiv/imu.h`).
`SyntheticImu` ships today and mirrors the Python dataset generator;
physical drivers (MPU-6050, LSM6DS3) are on the [roadmap](../ROADMAP.md).
Host-side sensor abstractions (IMU, GPS, barometer) live in
`eaiv.plugins.sensors`.
