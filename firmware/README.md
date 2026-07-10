# Firmware Module

Reusable firmware examples and PlatformIO-based projects for embedded AI validation.

## Structure

```
firmware/
├── boards/         # Board configurations (ESP32, STM32, RPi Pico, etc.)
├── sensors/        # Sensor driver implementations
├── examples/      # Reference firmware examples
└── platformio.ini  # PlatformIO project configuration
```

## Supported Hardware

- **ESP32** - WiFi/BT capable, dual-core
- **ESP32-S3** - AI accelerator, USB OTG
- **STM32H7** - High-performance ARM Cortex-M7
- **RPi Pico** - RP2040 dual-core ARM M0+
- **RPi Zero 2 W** - ARM Cortex-A53 (Linux-capable)

## Adding New Hardware

1. Create a board configuration in `boards/`
2. Add sensor drivers in `sensors/`
3. Update `platformio.ini` with new environments

## Dependencies

- PlatformIO (`pip install platformio`)
- Board-specific toolchains (installed via PlatformIO)

## Usage

```bash
# Build firmware
pio run -e esp32

# Flash firmware
pio run -e esp32 -t upload

# Monitor serial output
pio device monitor
```