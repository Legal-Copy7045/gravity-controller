#pragma once
// Govee H5198 (4-probe Wi-Fi/Bluetooth meat thermometer) advertisement decoding. Pure C++, unit tested.
//
// Manufacturer data, company id 0x2331 (bytes below exclude the 2-byte company id):
//   [6]      packet type: 0xC1 = probes 1 & 2, 0xC2 = probes 3 & 4
//   [8..9]   first probe temperature,  big-endian uint16, 1/100 °C
//   [14..15] second probe temperature, big-endian uint16, 1/100 °C
//   0x0000 or 0xFFFF = probe not plugged in
// Source: github.com/openworldtechio/govee_H5198_bluetooth_temperature_monitor (MIT). Unverified on more units:
// the component can log raw packets to confirm.

#include <cmath>
#include <cstddef>
#include <cstdint>

namespace h5198 {

constexpr uint16_t COMPANY_ID = 0x2331;

struct Reading {
  int first_probe{-1};  // 0-based probe index of the first value (0 or 2), -1 = not a probe packet
  float temp_c[2]{NAN, NAN};
};

inline Reading decode(const uint8_t *d, size_t len) {
  Reading r;
  if (len < 16)
    return r;
  if (d[6] == 0xC1)
    r.first_probe = 0;
  else if (d[6] == 0xC2)
    r.first_probe = 2;
  else
    return r;
  auto val = [](const uint8_t *p) -> float {
    uint16_t v = uint16_t(p[0]) << 8 | p[1];
    if (v == 0x0000 || v == 0xFFFF)
      return NAN;
    return v / 100.0f;
  };
  r.temp_c[0] = val(d + 8);
  r.temp_c[1] = val(d + 14);
  return r;
}

}  // namespace h5198
