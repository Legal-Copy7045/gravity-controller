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

}  // namespace h5198
