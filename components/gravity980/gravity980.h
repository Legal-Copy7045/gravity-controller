#pragma once
// ESPHome bridge to the stock Char-Griller Gravity 980 controller over Wi-Fi
// (TCP :3333) and/or Bluetooth LE (GATT service 0xAAAA). Both transports feed
// the same parser (protocol.h). See docs/protocol.md.

#include <functional>
#include <string>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/hal.h"
#include "esphome/core/preferences.h"

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
  void gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) override;
  void request_rssi();
  int link_rssi() const { return this->link_rssi_; }
  uint32_t link_rssi_at() const { return this->link_rssi_at_; }
  int adv_rssi() const { return this->adv_rssi_; }
  bool gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *param) override;
  bool ready() const { return this->write_handle_ != 0; }
  bool write(const std::vector<uint8_t> &data);
  void set_enabled(bool enabled);
  // Drop a link that isn't delivering (the grill was still starting up, or its notifications stopped) so the next
  // advertisement reconnects from scratch.
  bool reconnect(const char *why);
  uint32_t grill_seen_at() const { return this->grill_seen_at_; }  // last advertisement from the grill (0 = never)
  uint32_t any_adv_at() const { return this->any_adv_at_; }        // last advertisement from anything
  bool has_fixed_address() const { return this->fixed_address_ != 0; }
  uint64_t fixed_address() const { return this->fixed_address_; }
  void clear_link_rssi() { this->link_rssi_at_ = 0; }  // a new connection: the last reading was another link's

 protected:
  Gravity980Component *parent_{nullptr};
  std::string name_prefix_{"Gravity980"};
  uint64_t fixed_address_{0};
  uint32_t seen_at_{0};  // last advertisement from the address we connect to
  uint32_t grill_seen_at_{0};
  int link_rssi_{0};
  uint32_t link_rssi_at_{0};
  int adv_rssi_{0};
  uint32_t any_adv_at_{0};
  uint16_t notify_handle_{0};
  uint16_t write_handle_{0};
  bool enabled_{true};
};
#endif

class Gravity980Component : public Component {
 public:
  /// The grill's Bluetooth address, remembered across restarts (it's preferred; see Gravity980BLE::parse_device).
  void remember_grill(uint64_t a);
  /// Forget it: the next Gravity 980 heard is used (a different or replaced grill).
  void forget_grill();
  uint64_t remembered_grill() const { return this->remembered_grill_; }
  /// A grill Wi-Fi scan, join or credential send is under way (the Bluetooth peer must not change meanwhile).
  bool wifi_setup_pending() const {
#ifdef USE_TEXT_SENSOR
    return this->wifi_scan_at_ != 0 || this->wifi_cred_at_ != 0 || !this->wifi_join_ssid_.empty();
#else
    return false;
#endif
  }
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
  void set_ble_signal_sensor(sensor::Sensor *s) { this->ble_signal_ = s; }
  void set_grill_wifi_signal_sensor(sensor::Sensor *s) { this->grill_wifi_signal_ = s; }
#endif
#ifdef USE_BINARY_SENSOR
  void set_connected_binary_sensor(binary_sensor::BinarySensor *s) { this->connected_bs_ = s; }
  void set_wifi_link_binary_sensor(binary_sensor::BinarySensor *s) { this->wifi_link_bs_ = s; }
  void set_bluetooth_link_binary_sensor(binary_sensor::BinarySensor *s) { this->ble_link_bs_ = s; }
  void set_door_binary_sensor(binary_sensor::BinarySensor *s) { this->door_bs_ = s; }
  void set_fan_binary_sensor(binary_sensor::BinarySensor *s) { this->fan_bs_ = s; }
  void set_fan_turbo_binary_sensor(binary_sensor::BinarySensor *s) { this->fan_turbo_bs_ = s; }
  void set_alarm_binary_sensor(binary_sensor::BinarySensor *s) { this->alarm_bs_ = s; }
#endif
#ifdef USE_TEXT_SENSOR
  void set_raw_frame_text_sensor(text_sensor::TextSensor *s) { this->raw_ts_ = s; }
  void set_transport_text_sensor(text_sensor::TextSensor *s) { this->transport_ts_ = s; }
  void set_link_status_text_sensor(text_sensor::TextSensor *s) { this->link_status_ts_ = s; }
  void set_wifi_text_sensor(text_sensor::TextSensor *s) { this->wifi_ts_ = s; }
  void set_wifi_networks_text_sensor(text_sensor::TextSensor *s) { this->wifi_networks_ts_ = s; }

  // Grill Wi-Fi setup over Bluetooth (the Char-Griller app's provisioning commands, as documented by cg980app).
  // Only these raw 4/6-byte commands and the credentials message are sent; never control ids 0x01/0x04/0x05.
  bool wifi_rejoin();                                                   // join the network the grill has stored
  bool wifi_scan();                                                     // grill reports the networks it can see
  bool wifi_join(const std::string &ssid, const std::string &password);  // store credentials, then join
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
  /// The Char-Griller app's own controls (command 0x04, one flag at a time). Return why not, or "".
  std::string set_turbo(bool on);
  /// Turn the grill on or off: needs two presses within 10 s (the first arms it). "armed", "" (sent) or why not.
  std::string power_press(bool on);
  /// "Press again within 10 s to turn the grill off" while armed (or why the last one failed); "" otherwise.
  const std::string &power_prompt();
  /// The grill's "on" flag (byte 14 bit 4: off after power off, on again after power on).
  bool grill_on() const;
  bool turbo() const;
  /// Last reported setpoint in the configured unit (NAN if none).
  float reported_target(Probe probe) const;
  const Status &last_status() const { return this->status_; }
  bool has_status() const { return this->have_status_; }

  void add_on_status_callback(std::function<void(const Status &)> cb) { this->status_cbs_.push_back(std::move(cb)); }

  // Called by the BLE client.
  void on_ble_data(const uint8_t *data, size_t len);
  void on_ble_connected();
  void on_ble_disconnected(int reason = -1);

 protected:
  ESPPreferenceObject grill_pref_;
  uint64_t remembered_grill_{0};
  bool remembered_at_boot_{false};  // remembered_grill_ was saved before this boot
  uint32_t remembered_at_{0};       // when it was remembered this boot
  uint32_t ble_status_since_{0};    // valid status frames on this Bluetooth connection since (0 = none yet)
  enum class TcpState : uint8_t { IDLE, CONNECTING, CONNECTED };
  void tcp_start_connect_();
  void tcp_check_connect_();
  void tcp_read_();
  void tcp_close_(const char *reason);
  void tcp_flush_();
  void handle_status_(const Status &s, Transport via);
  void update_active_();
  void supervise_(uint32_t now);  // link watchdog + recovery, once a second
  void publish_signals_(uint32_t now);
  uint32_t signals_at_{0};
  void set_link_status_(const std::string &s);
#ifdef USE_GRAVITY980_BLE
  void restart_bluetooth_(const char *why);
#endif
  void publish_unknown_();
  void check_pending_();
  float to_unit_(uint16_t f) const;
  uint16_t from_unit_(float v) const;

  std::string host_;
  std::string auto_host_;  // the IP the grill reports over BLE, used when host_ is empty
  uint64_t auto_host_peer_{0};   // the Bluetooth device that reported it
  bool auto_host_blocked_{false};  // the reported IP's data disagreed with Bluetooth: not used again until a restart
  uint32_t wifi_info_req_at_{0};   // when we asked the grill for its Wi-Fi info (0 = not waiting)
  void clear_auto_host_(const char *why);
  // Both links delivering: their readings must agree, or the Wi-Fi link is dropped (see LinkCrossCheck).
  Status tcp_seen_{}, ble_seen_{};
  uint32_t tcp_seen_at_{0}, ble_seen_at_{0};
  LinkCrossCheck cross_check_;
  uint32_t tcp_hold_at_{0};  // Wi-Fi link dropped for disagreeing at (a configured host waits 10 min; 0 = none)
  const std::string &host_for_tcp_() const { return this->host_.empty() ? this->auto_host_ : this->host_; }
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
  uint8_t ble_retries_{0};  // reconnects in a row without a status frame
  // Recovery (supervise_): the bridge must never sit silently on a dead link.
  uint32_t supervised_at_{0};
  uint32_t down_since_{0};        // no grill data since (0 = connected)
  uint8_t ble_state_{0};          // last seen BLE client state, and since when
  uint32_t ble_state_since_{0};
  uint8_t recover_stage_{0};      // 0 = normal, 1 = Bluetooth restarted, 2 = gave up rebooting
  uint32_t recover_at_{0};
  bool scan_restarted_{false};    // restarted Bluetooth for a silent scanner (once until adverts resume)
  uint32_t recover_boots_{0};     // reboots in a row for a link that wouldn't come back (saved)
  ESPPreferenceObject recover_pref_;
  std::string last_drop_;         // why the last link ended, for the status text
  std::string link_status_;
  bool tcp_got_frame_{false};
  bool tcp_up_{false}, ble_up_{false};  // each link delivering status right now (published once known)
  bool links_known_{false};
  std::string resolved_host_;
  uint32_t resolved_addr_{0};
  uint32_t resolved_at_{0};

  Transport active_{Transport::NONE};
  Status status_{};
  bool have_status_{false};
  uint16_t pending_f_[PROBE_COUNT]{0, 0, 0};
  // A boost left running by firmware before 1.0 (0: none): its real pit target is put back once after the update.
  uint16_t old_boost_base_f_{0};
  uint16_t old_boost_f_{0};
  uint32_t old_boost_at_{0};
  uint8_t old_boost_tries_{0};
  ESPPreferenceObject old_boost_pref_;
  void old_boost_restore_(const Status &s);
  void old_boost_done_();
  bool write_target_(Probe probe, uint16_t f);
  std::string send_flags_(uint16_t flags, const char *what);
  static constexpr uint32_t POWER_CONFIRM_MS = 10000;
  uint32_t power_armed_{0};
  bool power_armed_on_{false};
  std::string power_prompt_;
  uint32_t pending_since_[PROBE_COUNT]{0, 0, 0};
  std::string last_raw_;
  std::vector<std::function<void(const Status &)>> status_cbs_;

#ifdef USE_GRAVITY980_BLE
  Gravity980BLE *ble_{nullptr};
#endif
#ifdef USE_SENSOR
  sensor::Sensor *temp_sensors_[PROBE_COUNT]{nullptr, nullptr, nullptr};
  sensor::Sensor *target_sensors_[PROBE_COUNT]{nullptr, nullptr, nullptr};
  sensor::Sensor *ble_signal_{nullptr};
  sensor::Sensor *grill_wifi_signal_{nullptr};
#endif
#ifdef USE_BINARY_SENSOR
  binary_sensor::BinarySensor *connected_bs_{nullptr};
  binary_sensor::BinarySensor *wifi_link_bs_{nullptr};
  binary_sensor::BinarySensor *ble_link_bs_{nullptr};
  binary_sensor::BinarySensor *door_bs_{nullptr};
  binary_sensor::BinarySensor *fan_bs_{nullptr};
  binary_sensor::BinarySensor *fan_turbo_bs_{nullptr};
  binary_sensor::BinarySensor *alarm_bs_{nullptr};
#endif
#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *raw_ts_{nullptr};
  text_sensor::TextSensor *transport_ts_{nullptr};
  text_sensor::TextSensor *link_status_ts_{nullptr};
  text_sensor::TextSensor *wifi_ts_{nullptr};
  text_sensor::TextSensor *wifi_networks_ts_{nullptr};
  struct WifiNet {
    std::string ssid;
    uint8_t bssid[6];
    uint8_t signal;
    uint8_t security;
  };
  std::vector<WifiNet> wifi_nets_;
  uint32_t wifi_scan_at_{0};        // scan running since (0 = not scanning)
  std::string wifi_join_ssid_, wifi_join_pass_;  // a join waiting for a scan (password kept only until sent)
  uint32_t wifi_cred_at_{0};        // credentials sent at (waiting for the grill's ack before "rejoin")
  void wifi_status_(const std::string &msg);
  void wifi_scan_done_();
  bool wifi_send_credentials_(const WifiNet &net, const std::string &password);
  std::string credentials_refusal_();  // "" when the connected Bluetooth peer may get the Wi-Fi password
  bool ble_raw_(const std::vector<uint8_t> &data, const char *what);
#endif
#ifdef USE_NUMBER
  Gravity980TargetNumber *target_numbers_[PROBE_COUNT]{nullptr, nullptr, nullptr};
#endif
};

}  // namespace gravity980
}  // namespace esphome
