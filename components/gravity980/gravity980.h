#pragma once
// ESPHome bridge to the stock Char-Griller Gravity 980 controller over Wi-Fi
// (TCP :3333) and/or Bluetooth LE (GATT service 0xAAAA). Both transports feed
// the same parser (protocol.h). See docs/protocol.md.

#include <functional>
#include <string>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/defines.h"

#include "protocol.h"

#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif
#ifdef USE_BINARY_SENSOR
#include "esphome/components/binary_sensor/binary_sensor.h"
#endif
#ifdef USE_TEXT_SENSOR
#include "esphome/components/text_sensor/text_sensor.h"
#endif
#ifdef USE_NUMBER
#include "esphome/components/number/number.h"
#endif
#ifdef USE_SWITCH
#include "esphome/components/switch/switch.h"
#endif
#ifdef USE_GRAVITY980_BLE
#include "esphome/components/esp32_ble_client/ble_client_base.h"
#endif

namespace esphome {
namespace gravity980 {

using namespace ::g980proto;

/// "AA BB CC" hex dump.
std::string hex_dump(const uint8_t *data, size_t len);
inline std::string hex_dump(const std::vector<uint8_t> &v) { return hex_dump(v.data(), v.size()); }

class Gravity980Component;

#ifdef USE_NUMBER
class Gravity980TargetNumber : public number::Number, public Component {
 public:
  void set_parent(Gravity980Component *parent) { this->parent_ = parent; }
  void set_probe(Probe probe) { this->probe_ = probe; }

 protected:
  void control(float value) override;
  Gravity980Component *parent_{nullptr};
  Probe probe_{PROBE_PIT};
};
#endif

#ifdef USE_SWITCH
/// Releases the TCP connection (the grill accepts one client) so the official app can connect.
class Gravity980EnableSwitch : public switch_::Switch, public Component {
 public:
  void set_parent(Gravity980Component *parent) { this->parent_ = parent; }
  void setup() override;

 protected:
  void write_state(bool state) override;
  Gravity980Component *parent_{nullptr};
};
#endif

#ifdef USE_GRAVITY980_BLE
/// BLE GATT client. Finds the grill by name prefix if no MAC is configured.
class Gravity980BLE : public esp32_ble_client::BLEClientBase {
 public:
  void set_parent(Gravity980Component *parent) { this->parent_ = parent; }
  void set_name_prefix(const std::string &p) { this->name_prefix_ = p; }
  void set_fixed_address(uint64_t a) {
    this->fixed_address_ = a;
    this->set_address(a);
  }
  bool parse_device(const esp32_ble_tracker::ESPBTDevice &device) override;
  bool gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *param) override;
  bool ready() const { return this->write_handle_ != 0; }
  bool write(const std::vector<uint8_t> &data);
  void set_enabled(bool enabled);

 protected:
  Gravity980Component *parent_{nullptr};
  std::string name_prefix_{"Gravity980"};
  uint64_t fixed_address_{0};
  uint16_t notify_handle_{0};
  uint16_t write_handle_{0};
  bool enabled_{true};
};
#endif

class Gravity980Component : public Component {
 public:
  enum class Transport : uint8_t { NONE, TCP, BLE };

  // --- configuration ---
  void set_host(const std::string &host);
  const std::string &get_host() const { return this->host_; }
  void set_port(uint16_t port) { this->port_ = port; }
  void set_fahrenheit(bool f) { this->fahrenheit_ = f; }
  bool is_fahrenheit() const { return this->fahrenheit_; }
  void set_read_only(bool ro) { this->read_only_ = ro; }
  void set_ble_writes(bool w) { this->ble_writes_ = w; }
  void set_log_raw(bool l) { this->log_raw_ = l; }
  void set_reconnect_interval(uint32_t ms) { this->reconnect_interval_ = ms; }
  void set_stale_timeout(uint32_t ms) { this->stale_timeout_ = ms; }
#ifdef USE_GRAVITY980_BLE
  void set_ble(Gravity980BLE *ble) { this->ble_ = ble; }
#endif

#ifdef USE_SENSOR
  void set_temperature_sensor(Probe p, sensor::Sensor *s) { this->temp_sensors_[p] = s; }
  void set_target_sensor(Probe p, sensor::Sensor *s) { this->target_sensors_[p] = s; }
#endif
#ifdef USE_BINARY_SENSOR
  void set_connected_binary_sensor(binary_sensor::BinarySensor *s) { this->connected_bs_ = s; }
  void set_door_binary_sensor(binary_sensor::BinarySensor *s) { this->door_bs_ = s; }
  void set_fan_binary_sensor(binary_sensor::BinarySensor *s) { this->fan_bs_ = s; }
  void set_fan_turbo_binary_sensor(binary_sensor::BinarySensor *s) { this->fan_turbo_bs_ = s; }
  void set_alarm_binary_sensor(binary_sensor::BinarySensor *s) { this->alarm_bs_ = s; }
#endif
#ifdef USE_TEXT_SENSOR
  void set_raw_frame_text_sensor(text_sensor::TextSensor *s) { this->raw_ts_ = s; }
  void set_transport_text_sensor(text_sensor::TextSensor *s) { this->transport_ts_ = s; }
#endif
#ifdef USE_NUMBER
  void set_target_number(Probe p, Gravity980TargetNumber *n) { this->target_numbers_[p] = n; }
#endif

  // --- ESPHome ---
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  // --- API for other components / lambdas ---
  void set_enabled(bool enabled);
  bool is_enabled() const { return this->enabled_; }
  bool is_connected() const { return this->active_ != Transport::NONE; }
  Transport active_transport() const { return this->active_; }
  /// Request a setpoint in the configured unit. Returns false if rejected locally.
  bool request_target(Probe probe, float value);
  /// Last reported setpoint in the configured unit (NAN if none).
  float reported_target(Probe probe) const;
  const Status &last_status() const { return this->status_; }
  void add_on_status_callback(std::function<void(const Status &)> cb) { this->status_cbs_.push_back(std::move(cb)); }

  // Called by the BLE client.
  void on_ble_data(const uint8_t *data, size_t len);
  void on_ble_connected();
  void on_ble_disconnected();

 protected:
  enum class TcpState : uint8_t { IDLE, CONNECTING, CONNECTED };
  void tcp_start_connect_();
  void tcp_check_connect_();
  void tcp_read_();
  void tcp_close_(const char *reason);
  void tcp_flush_();
  void handle_status_(const Status &s, Transport via);
  void update_active_();
  void publish_unknown_();
  void check_pending_();
  float to_unit_(uint16_t f) const;
  uint16_t from_unit_(float v) const;

  std::string host_;
  uint16_t port_{3333};
  bool fahrenheit_{true};
  bool read_only_{false};
  bool ble_writes_{false};
  bool log_raw_{false};
  bool enabled_{true};
  uint32_t reconnect_interval_{10000};
  uint32_t stale_timeout_{15000};

  TcpState tcp_state_{TcpState::IDLE};
  int fd_{-1};
  uint32_t tcp_since_{0};
  uint32_t tcp_last_attempt_{0};
  uint32_t tcp_last_frame_{0};
  FrameAssembler assembler_;
  std::vector<uint8_t> tx_;

  bool ble_connected_{false};
  bool ble_got_frame_{false};
  uint32_t ble_last_frame_{0};
  uint32_t ble_warned_{0};
  bool tcp_got_frame_{false};
  std::string resolved_host_;
  uint32_t resolved_addr_{0};
  uint32_t resolved_at_{0};

  Transport active_{Transport::NONE};
  Status status_{};
  bool have_status_{false};
  uint16_t pending_f_[PROBE_COUNT]{0, 0, 0};
  uint32_t pending_since_[PROBE_COUNT]{0, 0, 0};
  std::string last_raw_;
  std::vector<std::function<void(const Status &)>> status_cbs_;

#ifdef USE_GRAVITY980_BLE
  Gravity980BLE *ble_{nullptr};
#endif
#ifdef USE_SENSOR
  sensor::Sensor *temp_sensors_[PROBE_COUNT]{nullptr, nullptr, nullptr};
  sensor::Sensor *target_sensors_[PROBE_COUNT]{nullptr, nullptr, nullptr};
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *connected_bs_{nullptr};
  binary_sensor::BinarySensor *door_bs_{nullptr};
  binary_sensor::BinarySensor *fan_bs_{nullptr};
  binary_sensor::BinarySensor *fan_turbo_bs_{nullptr};
  binary_sensor::BinarySensor *alarm_bs_{nullptr};
#endif
#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *raw_ts_{nullptr};
  text_sensor::TextSensor *transport_ts_{nullptr};
#endif
#ifdef USE_NUMBER
  Gravity980TargetNumber *target_numbers_[PROBE_COUNT]{nullptr, nullptr, nullptr};
#endif
};

}  // namespace gravity980
}  // namespace esphome
