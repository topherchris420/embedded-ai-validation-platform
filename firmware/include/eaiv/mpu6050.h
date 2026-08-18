// Texas Instruments / InvenSense MPU-6050 6-Axis IMU Driver.
// Implements eaiv::IImu over I2C (Arduino Wire).
#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <stdint.h>

#include "eaiv/imu.h"

namespace eaiv {

class MPU6050Imu : public IImu {
 public:
  static constexpr uint8_t kDefaultAddress = 0x68;
  static constexpr uint8_t kAltAddress = 0x69;

  // MPU-6050 Register Map
  static constexpr uint8_t kRegSampleRateDiv = 0x19;
  static constexpr uint8_t kRegConfig = 0x1A;
  static constexpr uint8_t kRegGyroConfig = 0x1B;
  static constexpr uint8_t kRegAccelConfig = 0x1C;
  static constexpr uint8_t kRegAccelXOutH = 0x3B;
  static constexpr uint8_t kRegTempOutH = 0x41;
  static constexpr uint8_t kRegGyroXOutH = 0x43;
  static constexpr uint8_t kRegPwrMgmt1 = 0x6B;
  static constexpr uint8_t kRegWhoAmI = 0x75;

  explicit MPU6050Imu(uint8_t address = kDefaultAddress, TwoWire& wire = Wire)
      : address_(address), wire_(wire) {}

  const char* name() const override { return "mpu6050"; }

  bool begin() override {
    wire_.begin();

    // Wake up MPU-6050 (clear SLEEP bit in PWR_MGMT_1)
    if (!writeRegister(kRegPwrMgmt1, 0x01)) return false;  // PLL with X-axis gyro reference

    // Configure DLPF (~44Hz Accel, ~42Hz Gyro)
    writeRegister(kRegConfig, 0x03);

    // Sample rate divider: 1kHz / (1 + 9) = 100Hz
    writeRegister(kRegSampleRateDiv, 0x09);

    // Gyro full scale: +/- 2000 deg/s (FS_SEL = 3) -> 16.4 LSB/(deg/s)
    writeRegister(kRegGyroConfig, 0x18);

    // Accel full scale: +/- 4g (AFS_SEL = 1) -> 8192 LSB/g
    writeRegister(kRegAccelConfig, 0x08);

    t0_us_ = micros();
    return true;
  }

  bool read(ImuSample& out) override {
    wire_.beginTransmission(address_);
    wire_.write(kRegAccelXOutH);
    if (wire_.endTransmission(false) != 0) return false;

    // Request 14 bytes: Accel (6) + Temp (2) + Gyro (6)
    if (wire_.requestFrom(address_, static_cast<uint8_t>(14)) != 14) return false;

    const int16_t raw_ax = (wire_.read() << 8) | wire_.read();
    const int16_t raw_ay = (wire_.read() << 8) | wire_.read();
    const int16_t raw_az = (wire_.read() << 8) | wire_.read();
    wire_.read(); wire_.read();  // Skip temperature
    const int16_t raw_gx = (wire_.read() << 8) | wire_.read();
    const int16_t raw_gy = (wire_.read() << 8) | wire_.read();
    const int16_t raw_gz = (wire_.read() << 8) | wire_.read();

    const uint32_t now = micros();
    out.t_s = static_cast<float>(now - t0_us_) * 1e-6f;

    // Convert Accel (+/- 4g -> 8192 LSB/g)
    out.ax = static_cast<float>(raw_ax) / 8192.0f;
    out.ay = static_cast<float>(raw_ay) / 8192.0f;
    out.az = static_cast<float>(raw_az) / 8192.0f;

    // Convert Gyro (+/- 2000 deg/s -> 16.4 LSB / (deg/s) -> convert to rad/s)
    constexpr float kDegToRad = 0.017453292519943295f;
    out.gx = (static_cast<float>(raw_gx) / 16.4f) * kDegToRad;
    out.gy = (static_cast<float>(raw_gy) / 16.4f) * kDegToRad;
    out.gz = (static_cast<float>(raw_gz) / 16.4f) * kDegToRad;

    return true;
  }

 private:
  bool writeRegister(uint8_t reg, uint8_t value) {
    wire_.beginTransmission(address_);
    wire_.write(reg);
    wire_.write(value);
    return wire_.endTransmission() == 0;
  }

  uint8_t address_;
  TwoWire& wire_;
  uint32_t t0_us_ = 0;
};

}  // namespace eaiv
