# 1. Hardware Power Monitoring Drivers (INA226 & PPK2)

Date: 2026-08-18
Status: accepted

## Context
The platform previously supported only a `SimulatedPowerMonitor`, which generated synthetic Gaussian power noise around a configured set-point. Because of this, TinyML power metrics were marked with `simulated` provenance, preventing release gating from asserting real physical hardware energy budgets.

## Decision
We implement first-class hardware power monitoring drivers for the Texas Instruments **INA226** (over I2C) and Nordic Semiconductor **PPK2** (over USB serial):

1. **Pluggable `I2CBus` Abstraction**: An `I2CBus` adapter layer with three backends:
   - `LinuxI2CBus` (`smbus2` targeting `/dev/i2c-*`)
   - `PyFtdiI2CBus` (`pyftdi` for USB-to-I2C FT232H adapters)
   - `MockI2CBus` (in-memory register map emulation for headless CI and unit testing)
2. **INA226 Driver**: Complete register mapping, shunt calibration arithmetic, programmable conversion time/averaging, and continuous background sampling thread.
3. **Nordic PPK2 Driver**: Support for both `source` (supplying 0.8V–5.0V VDD to DUT) and `ampere` modes, with 5-range dynamic current decoding.
4. **Non-Blocking Background Thread**: Samples are polled asynchronously into a timestamped trace during the workload window so the benchmark loop is not delayed.
5. **Metric Provenance**: Metrics from these monitors are automatically stamped `(MetricProvenance.MEASURED, MetricSource.DEVICE)`.

## Consequences
- TinyML benchmarks running on physical hardware with INA226 or PPK2 now produce `measured` power metrics that qualify for release gating.
- Tests can exercise the complete register and protocol logic without requiring physical hardware via `MockI2CBus` and mock serial transports.
