// STMicroelectronics LSM6DS3 6-Axis IMU Driver.
// Implements eaiv::IImu over I2C (Arduino Wire).
#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <stdint.h>

#include "eaiv/imu.h"

namespace eaiv {

class LSM6DS3Imu : public IImu {
 public:
  static constexpr uint8_t kDefaultAddress = 0x6A;
  static constexpr uint8_t kAltAddress = 0x6B;

  // LSM6DS3 Register Map
  static constexpr uint8_t kRegWhoAmI = 0x0F;
  static constexpr uint8_t kRegCtrl1Xl = 0x10;
  static constexpr uint8_t kRegCtrl2G = 0x11;
  static constexpr uint8_t kRegCtrl3C = 0x12;
  static constexpr uint8_t kRegOutXLG = 0x22;
  static constexpr uint8_t kRegOutXLXl = 0x28;

  explicit LSM6DS3Imu(uint8_t address = kDefaultAddress, TwoWire& wire = Wire)
      : address_(address), wire_(wire) {}

  const char* name() const override { return "lsm6ds3"; }

  bool begin() override {
    wire_.begin();

    // Enable auto-increment (IF_INC) and Block Data Update (BDU) in CTRL3_C
    if (!writeRegister(kRegCtrl3C, 0x44)) return false;

    // Configure Accelerometer in CTRL1_XL: 104Hz ODR, +/- 4g full scale (0b01001000 = 0x48)
    writeRegister(kRegCtrl1Xl, 0x48);

    // Configure Gyroscope in CTRL2_G: 104Hz ODR, +/- 2000 dps full scale (0b01001100 = 0x4C)
    writeRegister(kRegCtrl2G, 0x4C);

    t0_us_ = micros();
    return true;
  }

  bool read(ImuSample& out) override {
    wire_.beginTransmission(address_);
    wire_.write(kRegOutXLG);
    if (wire_.endTransmission(false) != 0) return false;

    // Read 12 bytes: Gyro X,Y,Z (6 bytes) + Accel X,Y,Z (6 bytes)
    // Note: LSM6DS3 registers are Little-Endian (LSB followed by MSB)
    if (wire_.requestFrom(address_, static_cast<uint8_t>(12)) != 12) return false;

    const uint8_t gx_l = wire_.read();
    const uint8_t gx_h = wire_.read();
    const uint8_t gy_l = wire_.read();
    const uint8_t gy_h = wire_.read();
    const uint8_t gz_l = wire_.read();
    const uint8_t gz_h = wire_.read();

    const uint8_t ax_l = wire_.read();
    const uint8_t ax_h = wire_.read();
    const uint8_t ay_l = wire_.read();
    const uint8_t ay_h = wire_.read();
    const uint8_t az_l = wire_.read();
    const uint8_t az_h = wire_.read();

    const int16_t raw_gx = static_cast<int16_t>((gx_h << 8) | gx_l);
    const int16_t raw_gy = static_cast<int16_t>((gy_h << 8) | gy_l);
    const int16_t raw_gz = static_cast<int16_t>((gz_h << 8) | gz_l);

    const int16_t raw_ax = static_cast<int16_t>((ax_h << 8) | ax_l);
    const int16_t raw_ay = static_cast<int16_t>((ay_h << 8) | ay_l);
    const int16_t raw_az = static_cast<int16_t>((az_h << 8) | az_l);

    const uint32_t now = micros();
    out.t_s = static_cast<float>(now - t0_us_) * 1e-6f;

    // Convert Accel (+/- 4g full scale -> 0.122 mg/LSB = 0.000122 g/LSB)
    out.ax = static_cast<float>(raw_ax) * 0.000122f;
    out.ay = static_cast<float>(raw_ay) * 0.000122f;
    out.az = static_cast<float>(raw_az) * 0.000122f;

    // Convert Gyro (+/- 2000 dps full scale -> 70 mdps/LSB = 0.070 deg/s/LSB -> rad/s)
    constexpr float kDegToRad = 0.017453292519943295f;
    out.gx = (static_cast<float>(raw_gx) * 0.070f) * kDegToRad;
    out.gy = (static_cast<float>(raw_gy) * 0.070f) * kDegToRad;
    out.gz = (static_cast<float>(raw_gz) * 0.070f) * kDegToRad;

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
