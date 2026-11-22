#pragma once
// Reads a Govee H5198 meat thermometer's Bluetooth advertisements directly (no Home Assistant needed).

#include "esphome/core/component.h"
#include "esphome/components/ble_device_base/ble_device.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"

#include "h5198_decode.h"

namespace esphome {
namespace govee_h5198 {

class GoveeH5198 : public ble_device_base::ESPBTDeviceListener, public Component {
 public:
  void set_address(uint64_t a) { this->address_ = a; }
  void set_fahrenheit(bool f) { this->fahrenheit_ = f; }
  void set_log_raw(bool l) { this->log_raw_ = l; }
  void set_probe_sensor(int i, sensor::Sensor *s) { this->probes_[i] = s; }
  void set_rssi_sensor(sensor::Sensor *s) { this->rssi_ = s; }
  void set_connected_binary_sensor(binary_sensor::BinarySensor *b) { this->connected_ = b; }

  bool parse_device(const ble_device_base::ESPBTDevice &device) override;
  void setup() override;
  void loop() override;
  void dump_config() override;

 protected:
  uint64_t address_{0};  // 0 = lock onto the first H5198 heard
  bool fahrenheit_{true};
  bool log_raw_{false};
  sensor::Sensor *probes_[4]{nullptr, nullptr, nullptr, nullptr};
  sensor::Sensor *rssi_{nullptr};
  binary_sensor::BinarySensor *connected_{nullptr};
  uint32_t last_seen_[4]{0, 0, 0, 0};
  uint32_t last_packet_{0};
  uint32_t rssi_ms_{0};
  int last_rssi_{0};
  bool seen_{false};
};

}  // namespace govee_h5198
}  // namespace esphome
