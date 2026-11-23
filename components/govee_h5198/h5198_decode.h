#pragma once
// Govee H5198 (4-probe meat thermometer) advertisement decoding. Pure C++, unit tested.
//
// Format as decoded by govee-ble (github.com/Bluetooth-Devices/govee-ble, Apache-2.0), the library Home Assistant's
// Govee Bluetooth integration uses, and checked against a real H5198's advertisement:
//   * recognised by the 16-bit service UUID 0x9851 (or company id 0x3022, or "H5198" in the name); the
//     manufacturer-data company id itself varies between units;
//   * manufacturer data (without the 2-byte company id) is 20 bytes;
//   * [6] packet type: 1, 65, 129, 193 = probes 1 & 2; 2, 66, 130, 194 = probes 3 & 4 (low 6 bits);
//   * [8..19] six big-endian int16, 1/100 °C: probe A temperature, A high alarm, A low alarm, then the same for B;
//   * a negative value (0xFFFF) = probe not plugged in / alarm not set.

#include <cmath>
#include <cstddef>
#include <cstdint>

namespace h5198 {

constexpr uint16_t SERVICE_UUID = 0x9851;
constexpr uint16_t COMPANY_ID_ALT = 0x3022;
constexpr size_t PACKET_LEN = 20;

struct Reading {
  int first_probe{-1};  // 0-based index of probe A (0 or 2); -1 = not a probe packet
  float temp_c[2]{NAN, NAN};
  float alarm_high_c[2]{NAN, NAN};
  float alarm_low_c[2]{NAN, NAN};
};

inline float value_c(const uint8_t *p) {
  int16_t v = int16_t(uint16_t(p[0]) << 8 | p[1]);
  return v < 0 ? NAN : v / 100.0f;
}

inline Reading decode(const uint8_t *d, size_t len) {
  Reading r;
  if (len != PACKET_LEN)
    return r;
  switch (d[6] & 0x3F) {
    case 1:
      r.first_probe = 0;
      break;
    case 2:
      r.first_probe = 2;
      break;
    default:
      return r;
  }
  for (int k = 0; k < 2; k++) {
    const uint8_t *b = d + 8 + 6 * k;
    r.temp_c[k] = value_c(b);
    r.alarm_high_c[k] = value_c(b + 2);
    r.alarm_low_c[k] = value_c(b + 4);
  }
  return r;
}

// ---- Plausibility (pure, unit tested). The thermometer is chosen and read from unauthenticated advertisements, so
// anything in range can send probe packets: these keep a look-alike from taking over or bending readings.

constexpr float JUMP_C = 15.0f;            // a reading further than this from the last one...
constexpr uint32_t JUMP_WINDOW_MS = 10000;  // ...within this time is a jump
constexpr uint8_t JUMP_REPEATS = 3;        // a jump is taken once it repeats in this many advertisements in a row

/// Per probe: drops a reading that jumps more than JUMP_C from the last accepted one within JUMP_WINDOW_MS, unless it
/// repeats JUMP_REPEATS advertisements in a row (a probe really put into the pit, or plugged in). NaN (unplugged) is
/// a value like any other: an unplug or replug is a jump too.
class ProbeFilter {
 public:
  bool accept(float c, uint32_t now) {
    if (!has_ || now - last_ms_ > JUMP_WINDOW_MS || close_(c, last_c_))
      return take_(c, now);
    if (cand_n_ != 0 && close_(c, cand_c_)) {
      if (++cand_n_ >= JUMP_REPEATS)
        return take_(c, now);
    } else {
      cand_c_ = c;
      cand_n_ = 1;
    }
    return false;
  }
  void reset() {
    has_ = false;
    cand_n_ = 0;
  }

 protected:
  static bool close_(float a, float b) {
    if (std::isnan(a) || std::isnan(b))
      return std::isnan(a) && std::isnan(b);
    return std::fabs(a - b) <= JUMP_C;
  }
  bool take_(float c, uint32_t now) {
    has_ = true;
    last_c_ = c;
    last_ms_ = now;
    cand_n_ = 0;
    return true;
  }
  bool has_{false};
  float last_c_{NAN};
  uint32_t last_ms_{0};
  float cand_c_{NAN};
  uint8_t cand_n_{0};
};

constexpr uint32_t LOCK_AFTER_MS = 60000;  // a new thermometer is remembered once heard this long...
constexpr uint32_t LOCK_GAP_MS = 10000;    // ...with no silence longer than this

/// Choosing a thermometer when none is remembered: the first one heard is used, others are ignored while it keeps
/// advertising, and it is remembered (LOCK) only after LOCK_AFTER_MS of steady advertisements. One that goes quiet
/// for LOCK_GAP_MS is dropped, and the next one heard starts over.
class Candidate {
 public:
  enum Verdict : uint8_t { IGNORE, USE, LOCK };
  Verdict heard(uint64_t a, uint32_t now) {
    if (addr_ != 0 && now - last_ > LOCK_GAP_MS)
      addr_ = 0;
    if (addr_ == 0) {
      addr_ = a;
      first_ = last_ = now;
    }
    if (a != addr_)
      return IGNORE;
    last_ = now;
    return now - first_ >= LOCK_AFTER_MS ? LOCK : USE;
  }
  void reset() { addr_ = 0; }
  uint64_t address() const { return addr_; }

 protected:
  uint64_t addr_{0};
  uint32_t first_{0}, last_{0};
};

}  // namespace h5198
