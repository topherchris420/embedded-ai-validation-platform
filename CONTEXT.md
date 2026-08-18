# Embedded AI Validation Platform

A validation and continuous integration platform for testing, profiling, and benchmarking TinyML models and embedded firmware on physical hardware and simulators.

## Language

**Power Monitor**:
An instrument or plugin that records instantaneous electrical power (voltage, current, power) across a target device's supply rail during a workload window.
_Avoid_: Power meter, current sensor, energy logger

**Power Trace**:
The time-series and aggregate measurement result (duration, samples in mW, mean mW, peak mW, energy in mJ) produced by a Power Monitor.
_Avoid_: Power profile, energy record

**INA226**:
A high-side or low-side current shunt and power monitor with an I2C interface, programmable conversion times, and averaging.
_Avoid_: Current sensor IC, shunt IC

**PPK2**:
Nordic Semiconductor Power Profiler Kit II, a dedicated bench measurement instrument capable of measuring current from 100 nA to 1 A and optionally powering the device under test.
_Avoid_: Nordic meter, power profiler

**I2C Bus Adapter**:
A transport abstraction allowing the host system to communicate over I2C via native Linux `/dev/i2c-*`, USB-I2C bridge (FTDI), or an in-memory mock.
_Avoid_: Bus driver, I2C handle

**Measurement Provenance**:
The declared origin and certainty classification (`measured`, `simulated`, `estimated`, `mock`) attached to every validation metric.
_Avoid_: Metric source type, data authenticity
