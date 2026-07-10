# Roadmap

The goal: the open-source reference implementation for embedded AI
validation — pytest + PlatformIO + MLPerf Tiny + hardware telemetry for
resource-constrained devices.

## Done (v0.3)

- Plugin architecture (targets, fusion filters, fault models) with
  entry-point discovery for external packages
- Suites: firmware smoke/regression, TinyML benchmarking (host runtimes),
  sensor-fusion replay scoring, RT profiling, HIL robustness
- Fusion filters: complementary, Mahony, Madgwick, 1-D Kalman, 4-state EKF
  with gyro-bias estimation
- Deterministic dataset generator + committed replay logs with ground truth
- HIL: fault injection (noise, packet loss, jitter, outage), simulated
  target running the full firmware suite hardware-free
- Regression gating: `eaiv compare` over report JSON artifacts
- Firmware: header-only C++ HAL + validation app building for ESP32,
  ESP32-S3, STM32H7, RPi Pico; on-device fusion benchmark (`bench`)
- CI: lint, tests, firmware builds; Streamlit dashboard

## Next (v0.4)

- **On-device TinyML**: TFLite-Micro benchmark harness in the firmware app;
  report on-device latency/RAM through the serial protocol
- **Power measurement**: `PowerMonitor` interface + INA226 and Nordic PPK2
  drivers; power column in benchmark reports
- **Raspberry Pi Zero 2 W target**: SSH/Linux target backend (flash =
  deploy, serial = journald/stdout)
- **Physical IMU drivers**: MPU-6050 and LSM6DS3 implementations of `IImu`
- **Magnetometer-aware fusion**: mag input for Madgwick/EKF yaw correction
- **Baseline management**: `eaiv baseline save/promote` and a CI recipe
  storing baselines as workflow artifacts

## Later

- MkDocs documentation site with generated API reference
- Dashboard: live serial telemetry view, benchmark comparison across
  boards, report-history browser
- QEMU semihosting harness for cycle-accurate Cortex-M profiling
- MLPerf Tiny workload pack (keyword spotting, visual wake words, anomaly
  detection) with reference models
- Camera/microphone virtual sensors for HIL
- Zephyr and ESP-IDF (non-Arduino) firmware variants

Contributions in any of these areas are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).
