// Board abstraction: everything the validation firmware needs from the
// hardware, kept behind a minimal interface so new boards only require a
// PlatformIO environment plus (optionally) an override of these hooks.
#pragma once

#include <Arduino.h>

#ifndef EAIV_BOARD_NAME
#define EAIV_BOARD_NAME "unknown"
#endif

namespace eaiv {

struct BoardInfo {
  const char* name;
  uint32_t cpu_hz;
  uint32_t free_heap_bytes;
};

inline uint32_t free_heap_bytes() {
#if defined(ESP32)
  return ESP.getFreeHeap();
#else
  // Portable fallback: probe with a bounded binary search over malloc.
  uint32_t lo = 0, hi = 256 * 1024;
  while (lo + 1024 < hi) {
    uint32_t mid = lo + (hi - lo) / 2;
    void* p = malloc(mid);
    if (p != nullptr) {
      free(p);
      lo = mid;
    } else {
      hi = mid;
    }
  }
  return lo;
#endif
}

inline uint32_t cpu_hz() {
#if defined(F_CPU)
  return F_CPU;
#elif defined(ARDUINO_ARCH_MBED)
  return SystemCoreClock;  // CMSIS global provided by the mbed core
#else
  return 0;
#endif
}

inline BoardInfo board_info() {
  return BoardInfo{EAIV_BOARD_NAME, cpu_hz(), free_heap_bytes()};
}

// Monotonic microsecond clock used for all latency measurements.
inline uint32_t now_us() { return micros(); }

// Die/board temperature in Celsius, NAN when the board has no sensor the
// HAL knows about. Extend per board here — host-side telemetry is
// field-driven and needs no changes for new metrics.
inline float board_temperature_c() {
#if defined(ESP32)
  return temperatureRead();
#else
  return NAN;
#endif
}

}  // namespace eaiv
