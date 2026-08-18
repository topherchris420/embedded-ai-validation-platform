"""Tests for hardware power monitoring drivers (INA226, PPK2) and I2C bus backends."""

from __future__ import annotations

import time

import pytest

from eaiv.power import (
    INA226PowerMonitor,
    MockI2CBus,
    MockPPK2Serial,
    PowerTrace,
    PPK2PowerMonitor,
    build_i2c_bus,
    build_power_monitor,
)
from eaiv.power.ina226 import (
    REG_BUSVOLTAGE,
    REG_CALIBRATION,
    REG_CONFIG,
    REG_CURRENT,
    REG_POWER,
    REG_SHUNTVOLTAGE,
)
from eaiv.tinyml.benchmark import TinyMLBenchmark


def test_mock_i2c_bus_read_write() -> None:
    bus = MockI2CBus()
    addr = 0x40
    reg = 0x05
    bus.write_word_data(addr, reg, 0x1234)
    assert bus.read_word_data(addr, reg) == 0x1234
    assert bus.read_word_data(addr, 0x00) == 0x0000

    bus.close()
    with pytest.raises(RuntimeError, match="Cannot read from a closed I2C bus"):
        bus.read_word_data(addr, reg)
    with pytest.raises(RuntimeError, match="Cannot write to a closed I2C bus"):
        bus.write_word_data(addr, reg, 0x5678)


def test_build_i2c_bus_factory() -> None:
    mock_bus = build_i2c_bus({"backend": "mock"})
    assert isinstance(mock_bus, MockI2CBus)

    default_bus = build_i2c_bus(None)
    assert isinstance(default_bus, MockI2CBus)

    with pytest.raises(ValueError, match="Unknown I2C bus backend"):
        build_i2c_bus({"backend": "invalid_backend"})


def test_ina226_configuration_and_registers() -> None:
    mock_bus = MockI2CBus()
    addr = 0x40
    monitor = INA226PowerMonitor(
        i2c_bus=mock_bus,
        address=addr,
        shunt_ohms=0.1,
        max_expected_a=3.2,
        averaging=16,
    )

    # Verify CONFIG and CALIBRATION were written
    cfg_val = mock_bus.read_word_data(addr, REG_CONFIG)
    assert cfg_val != 0
    cal_val = mock_bus.read_word_data(addr, REG_CALIBRATION)
    assert cal_val == monitor.calibration_val
    assert cal_val > 0


def test_ina226_voltage_current_power_math() -> None:
    mock_bus = MockI2CBus()
    addr = 0x40
    # Simulate VBUS = 3.3V (3.3 / 0.00125 = 2640 = 0x0A50)
    # Simulate Current = 50mA
    mock_bus.devices[addr] = {
        REG_BUSVOLTAGE: 2640,
        REG_SHUNTVOLTAGE: 2000,  # 2000 * 2.5uV = 5.0 mV -> 5mV / 0.1 ohm = 50 mA
        REG_CURRENT: 512,  # 512 * current_lsb (~0.09765mA) ~ 50 mA
        REG_POWER: 67,  # 67 * 25 * current_lsb * 1000 ~ 165 mW
    }

    monitor = INA226PowerMonitor(
        i2c_bus=mock_bus,
        address=addr,
        shunt_ohms=0.1,
        max_expected_a=3.2,
    )

    v_bus = monitor.read_bus_voltage_v()
    assert pytest.approx(v_bus, rel=1e-2) == 3.3

    v_shunt = monitor.read_shunt_voltage_mv()
    assert pytest.approx(v_shunt, rel=1e-2) == 5.0

    p_mw = monitor.read_power_mw()
    assert p_mw > 0.0


def test_ina226_start_stop_trace() -> None:
    mock_bus = MockI2CBus()
    addr = 0x40
    mock_bus.devices[addr] = {
        REG_BUSVOLTAGE: 2640,
        REG_POWER: 100,
    }

    monitor = INA226PowerMonitor(
        i2c_bus=mock_bus,
        address=addr,
        sample_rate_hz=100.0,
    )

    monitor.start()
    time.sleep(0.05)  # Collect several samples
    trace = monitor.stop()

    assert isinstance(trace, PowerTrace)
    assert trace.duration_s > 0.0
    assert len(trace.samples_mw) > 0
    assert trace.mean_mw > 0.0
    assert trace.peak_mw >= trace.mean_mw
    assert trace.energy_mj > 0.0


def test_build_ina226_plugin() -> None:
    monitor = build_power_monitor(
        {
            "kind": "ina226",
            "shunt_ohms": 0.05,
            "max_expected_a": 1.0,
            "address": 0x41,
        }
    )
    assert isinstance(monitor, INA226PowerMonitor)
    assert monitor.address == 0x41
    assert monitor.shunt_ohms == 0.05


def test_ppk2_source_mode_and_packet_decoding() -> None:
    mock_serial = MockPPK2Serial(vdd_v=3.3)
    monitor = PPK2PowerMonitor(
        port=mock_serial,
        mode="source",
        vdd_v=3.3,
    )
    assert monitor.mode == "source"
    assert monitor.vdd_v == 3.3

    # Decode a synthetic 4-byte packet (range 3, ADC 8192)
    val = 8192 | (3 << 14)
    import struct

    pkt = struct.pack("<I", val)
    p_mw = monitor.decode_packet(pkt)
    assert p_mw > 0.0


def test_ppk2_start_stop_trace() -> None:
    mock_serial = MockPPK2Serial(vdd_v=3.3)
    monitor = PPK2PowerMonitor(port=mock_serial, vdd_v=3.3)

    monitor.start()
    time.sleep(0.05)
    trace = monitor.stop()

    assert isinstance(trace, PowerTrace)
    assert trace.duration_s > 0.0
    assert len(trace.samples_mw) > 0
    assert trace.mean_mw > 0.0
    assert trace.energy_mj > 0.0


def test_build_ppk2_plugin() -> None:
    monitor = build_power_monitor(
        {
            "kind": "ppk2",
            "port": "mock",
            "mode": "ampere",
            "vdd_v": 1.8,
        }
    )
    assert isinstance(monitor, PPK2PowerMonitor)
    assert monitor.mode == "ampere"
    assert monitor.vdd_v == 1.8


def test_tinyml_benchmark_hardware_provenance() -> None:
    """Verify TinyMLBenchmark stamps MEASURED and DEVICE provenance for hardware monitors."""
    target = None
    spec = {
        "runtime": "mock",
        "iterations": 10,
        "warmup": 2,
        "power": {
            "kind": "ina226",
            "shunt_ohms": 0.1,
            "address": 0x40,
        },
    }

    bench = TinyMLBenchmark(spec=spec, target=target)
    result = bench.run()

    assert result.passed
    assert "mean_power_mw" in result.metrics
    assert "peak_power_mw" in result.metrics
    assert "energy_per_inference_mj" in result.metrics

    # Check metric metadata provenance
    meta = result.metric_meta
    assert meta["mean_power_mw"]["provenance"] == "measured"
    assert meta["mean_power_mw"]["source"] == "device"
    assert meta["peak_power_mw"]["provenance"] == "measured"
    assert meta["peak_power_mw"]["source"] == "device"
    assert meta["energy_per_inference_mj"]["provenance"] == "measured"
    assert meta["energy_per_inference_mj"]["source"] == "device"
