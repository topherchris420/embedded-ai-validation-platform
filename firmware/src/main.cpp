// eaiv validation firmware.
//
// Serial protocol (consumed by eaiv.firmware.tester.FirmwareTester and
// mirrored by the HIL SimulatedTarget):
//
//   BOOT eaiv-fw board=<name> cpu_hz=<hz> heap=<bytes>
//   T t=<s> gx=.. gy=.. gz=.. ax=.. ay=.. az=.. roll=.. pitch=..
//   ALL_TESTS_OK | FAIL <reason>
//
// After the verdict the firmware answers line commands:
//   id    -> "eaiv-fw v<version> board=<name>"
//   ping  -> "pong"
//   bench -> "B iters=<n> us_per_update=<mean> max_us=<max>"

#include <Arduino.h>

#include "eaiv/board.h"
#include "eaiv/complementary_filter.h"
#include "eaiv/imu.h"

namespace {

constexpr const char* kVersion = "0.3.0";
constexpr int kTelemetrySamples = 50;
constexpr float kImuRateHz = 100.0f;

eaiv::SyntheticImu g_imu(kImuRateHz);
eaiv::ComplementaryFilter g_filter;

bool self_test_clock() {
  const uint32_t a = eaiv::now_us();
  delayMicroseconds(500);
  const uint32_t b = eaiv::now_us();
  return (b - a) >= 400 && (b - a) < 50000;
}

bool self_test_heap() {
  void* p = malloc(1024);
  if (p == nullptr) return false;
  free(p);
  return true;
}

bool self_test_filter() {
  // Level device: the filter must converge near zero from a cold start.
  eaiv::ComplementaryFilter f;
  eaiv::ImuSample level{0, 0, 0, 0, 0, 0, 1.0f};
  eaiv::Orientation o{0, 0};
  for (int i = 0; i < 500; ++i) o = f.update(0.005f, level);
  return fabsf(o.roll_deg) < 5.0f && fabsf(o.pitch_deg) < 5.0f;
}

void stream_telemetry() {
  eaiv::ImuSample s;
  for (int i = 0; i < kTelemetrySamples; ++i) {
    if (!g_imu.read(s)) break;
    const eaiv::Orientation o = g_filter.update(1.0f / kImuRateHz, s);
    Serial.print("T t=");
    Serial.print(s.t_s, 4);
    Serial.print(" gx=");
    Serial.print(s.gx, 5);
    Serial.print(" gy=");
    Serial.print(s.gy, 5);
    Serial.print(" gz=");
    Serial.print(s.gz, 5);
    Serial.print(" ax=");
    Serial.print(s.ax, 5);
    Serial.print(" ay=");
    Serial.print(s.ay, 5);
    Serial.print(" az=");
    Serial.print(s.az, 5);
    Serial.print(" roll=");
    Serial.print(o.roll_deg, 3);
    Serial.print(" pitch=");
    Serial.println(o.pitch_deg, 3);
  }
}

void run_benchmark() {
  eaiv::SyntheticImu imu(kImuRateHz);
  eaiv::ComplementaryFilter filter;
  imu.begin();

  constexpr int kIters = 1000;
  uint32_t total_us = 0, max_us = 0;
  eaiv::ImuSample s;
  for (int i = 0; i < kIters; ++i) {
    imu.read(s);
    const uint32_t t0 = eaiv::now_us();
    filter.update(1.0f / kImuRateHz, s);
    const uint32_t dt = eaiv::now_us() - t0;
    total_us += dt;
    if (dt > max_us) max_us = dt;
  }
  Serial.print("B iters=");
  Serial.print(kIters);
  Serial.print(" us_per_update=");
  Serial.print(static_cast<float>(total_us) / kIters, 3);
  Serial.print(" max_us=");
  Serial.println(max_us);
}

void handle_command(const String& cmd) {
  if (cmd == "id") {
    Serial.print("eaiv-fw v");
    Serial.print(kVersion);
    Serial.print(" board=");
    Serial.println(EAIV_BOARD_NAME);
  } else if (cmd == "ping") {
    Serial.println("pong");
  } else if (cmd == "bench") {
    run_benchmark();
  } else if (cmd.length() > 0) {
    Serial.print("ERR unknown command: ");
    Serial.println(cmd);
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(100);

  const eaiv::BoardInfo info = eaiv::board_info();
  Serial.print("BOOT eaiv-fw board=");
  Serial.print(info.name);
  Serial.print(" cpu_hz=");
  Serial.print(info.cpu_hz);
  Serial.print(" heap=");
  Serial.println(info.free_heap_bytes);

  if (!g_imu.begin()) {
    Serial.println("FAIL imu-init");
    return;
  }

  stream_telemetry();

  if (!self_test_clock()) {
    Serial.println("FAIL self-test-clock");
  } else if (!self_test_heap()) {
    Serial.println("FAIL self-test-heap");
  } else if (!self_test_filter()) {
    Serial.println("FAIL self-test-filter");
  } else {
    Serial.println("ALL_TESTS_OK");
  }
}

void loop() {
  static String buffer;
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      buffer.trim();
      handle_command(buffer);
      buffer = "";
    } else {
      buffer += c;
    }
  }
}
