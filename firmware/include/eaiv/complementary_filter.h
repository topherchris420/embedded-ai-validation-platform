// Complementary filter mirroring eaiv.sensor_fusion.fusion.ComplementaryFilter
// so on-device results can be cross-validated against the Python reference.
#pragma once

#include <math.h>

#include "eaiv/imu.h"

namespace eaiv {

struct Orientation {
  float roll_deg;
  float pitch_deg;
};

class ComplementaryFilter {
 public:
  explicit ComplementaryFilter(float alpha = 0.98f) : alpha_(alpha) {}

  Orientation update(float dt_s, const ImuSample& s) {
    const float acc_roll = atan2f(s.ay, s.az) * kRadToDeg;
    const float acc_pitch = atan2f(-s.ax, sqrtf(s.ay * s.ay + s.az * s.az)) * kRadToDeg;

    const float gyro_roll = roll_ + s.gx * kRadToDeg * dt_s;
    const float gyro_pitch = pitch_ + s.gy * kRadToDeg * dt_s;

    roll_ = alpha_ * gyro_roll + (1.0f - alpha_) * acc_roll;
    pitch_ = alpha_ * gyro_pitch + (1.0f - alpha_) * acc_pitch;
    return Orientation{roll_, pitch_};
  }

  void reset() { roll_ = pitch_ = 0.0f; }

 private:
  static constexpr float kRadToDeg = 57.2957795f;
  float alpha_;
  float roll_ = 0.0f;
  float pitch_ = 0.0f;
};

}  // namespace eaiv
