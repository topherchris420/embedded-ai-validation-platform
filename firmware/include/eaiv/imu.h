// IMU sensor abstraction. Physical drivers (MPU-6050, LSM6DS3, ...)
// implement IImu; SyntheticImu generates the same seeded trajectory as the
// Python dataset generator so host-side and on-device pipelines can be
// cross-validated sample-for-sample.
#pragma once

#include <math.h>
#include <stdint.h>

namespace eaiv {

struct ImuSample {
  float t_s;             // seconds since sensor start
  float gx, gy, gz;      // gyro body rates, rad/s
  float ax, ay, az;      // accelerometer, g
};

class IImu {
 public:
  virtual ~IImu() = default;
  virtual const char* name() const = 0;
  virtual bool begin() = 0;
  // Fill `out` with the next sample; false when no sample is available.
  virtual bool read(ImuSample& out) = 0;
};

// Deterministic synthetic IMU following the "gentle" motion profile of
// eaiv.datasets.generator (noise-free): roll 15 deg @ 0.2 Hz, pitch 10 deg
// @ 0.13 Hz, yaw 20 deg @ 0.05 Hz.
class SyntheticImu : public IImu {
 public:
  explicit SyntheticImu(float rate_hz = 100.0f) : dt_s_(1.0f / rate_hz) {}

  const char* name() const override { return "synthetic-imu"; }
  bool begin() override {
    t_s_ = 0.0f;
    return true;
  }

  bool read(ImuSample& out) override {
    const float t = t_s_;
    t_s_ += dt_s_;

    const float roll = amp_roll_ * sinf(kTwoPi * f_roll_ * t);
    const float pitch = amp_pitch_ * sinf(kTwoPi * f_pitch_ * t);
    const float droll = amp_roll_ * kTwoPi * f_roll_ * cosf(kTwoPi * f_roll_ * t);
    const float dpitch = amp_pitch_ * kTwoPi * f_pitch_ * cosf(kTwoPi * f_pitch_ * t);
    const float dyaw = amp_yaw_ * kTwoPi * f_yaw_ * cosf(kTwoPi * f_yaw_ * t);

    const float sr = sinf(roll), cr = cosf(roll);
    const float sp = sinf(pitch), cp = cosf(pitch);

    out.t_s = t;
    // Euler rates -> body rates (ZYX)
    out.gx = droll - dyaw * sp;
    out.gy = dpitch * cr + dyaw * cp * sr;
    out.gz = -dpitch * sr + dyaw * cp * cr;
    // Gravity direction in the body frame
    out.ax = -sp;
    out.ay = sr * cp;
    out.az = cr * cp;
    return true;
  }

 private:
  static constexpr float kTwoPi = 6.28318530718f;
  static constexpr float kDegToRad = 0.0174532925f;
  float dt_s_;
  float t_s_ = 0.0f;
  float amp_roll_ = 15.0f * kDegToRad, f_roll_ = 0.2f;
  float amp_pitch_ = 10.0f * kDegToRad, f_pitch_ = 0.13f;
  float amp_yaw_ = 20.0f * kDegToRad, f_yaw_ = 0.05f;
};

}  // namespace eaiv
