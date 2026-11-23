#pragma once
// Capture mode, the Bluetooth side (docs/protocol.md, "Capturing the app's commands"). While it's on, the controller
// advertises as a Gravity 980 ("Gravity980-" + the last 2 bytes of its own Bluetooth address, service 0xAAAA) and
// serves the grill's GATT service: 0xBBB0 takes the app's writes, 0xBBB1 sends a status every 2 s. Every write is
// recorded (capture.h); nothing is ever forwarded or replayed to the real grill, whose Bluetooth link is paused
// meanwhile. Off at boot, invisible while off, and off again after 10 minutes. One phone at a time.
//
// Built on ESPHome's esp32_ble_server (Bluedroid on ESP-IDF): the service is created at runtime on the server that
// improv_ble already uses, and advertising is requested from esp32_ble only while capturing. Without Bluetooth (the
// host build) it compiles to a stub that refuses to start.

#include <atomic>
#include <cstdint>
#include <mutex>
#include <span>
#include <string>

#include "esphome/core/defines.h"

#include "capture.h"

#ifdef USE_TEXT_SENSOR
#include "esphome/components/text_sensor/text_sensor.h"
#endif
#ifdef USE_SWITCH
#include "esphome/components/switch/switch.h"
#endif
#ifdef USE_BUTTON
#include "esphome/components/button/button.h"
#endif
#ifdef USE_GRAVITY980_CAPTURE
#include <esp_gatts_api.h>
#include "esphome/components/esp32_ble_server/ble_server.h"
#endif

namespace esphome {
namespace gravity980 {

class Gravity980Component;

class AppCapture {
 public:
  explicit AppCapture(Gravity980Component *parent) : parent_(parent) {}
#ifdef USE_TEXT_SENSOR
  void set_text_sensor(text_sensor::TextSensor *s) { this->text_ = s; }
#endif
#ifdef USE_SWITCH
  void set_switch(switch_::Switch *s) { this->switch_ = s; }
#endif

  /// Turn capture mode on. Returns why not, or "".
  std::string start();
  /// Turn it off (also after 10 minutes, or when Bluetooth goes down).
  void stop(const char *why);
  bool active() const { return this->state_ != State::OFF; }
  /// Forget the records (the page's Clear, the button). Safe from any task.
  void clear();
  /// The state and the records for the device page (GET /local/capture). Safe from any task.
  std::string json();

  void loop(uint32_t now);
#ifdef USE_GRAVITY980_CAPTURE
  void gatts_event_handler(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if, esp_ble_gatts_cb_param_t *param);
#endif

 protected:
  enum class State : uint8_t { OFF, STARTING, ON };
  void record_(const g980proto::CaptureRecord &r);
  uint32_t elapsed_() const { return this->started_at_ ? millis_() - this->started_at_ : 0; }
  static uint32_t millis_();
  void publish_switch_(bool on);

  Gravity980Component *parent_;
  State state_{State::OFF};
  uint32_t started_at_{0};  // when capture mode was switched on (0: off)
  std::string why_off_;     // why it last stopped (or didn't start), for the page

  // Shared with the web server's task (json, clear): under lock_.
  std::mutex lock_;
  g980proto::CaptureLog log_;
  std::atomic<bool> dirty_{false};  // the text sensor needs publishing (main loop)
  std::atomic<bool> connected_{false}, subscribed_{false};
  char name_[21]{};  // "Gravity980-XXXX": also what esp32_ble advertises while on

#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *text_{nullptr};
#endif
#ifdef USE_SWITCH
  switch_::Switch *switch_{nullptr};
#endif

#ifdef USE_GRAVITY980_CAPTURE
  void on_write_(uint16_t uuid, std::span<const uint8_t> value, uint16_t conn_id);
  void send_status_();
  void advertise_(bool on);
  void drop_phone_();
  g980proto::FakeGrill fake_;
  esp32_ble_server::BLEService *svc_{nullptr};
  esp32_ble_server::BLECharacteristic *write_chr_{nullptr}, *notify_chr_{nullptr};
  uint16_t notify_handle_{0}, cccd_handle_{0};
  bool advertising_{false};      // holding one of esp32_ble's advertising requests
  bool phone_{false};            // a phone is connected to us
  uint16_t phone_conn_{0};
  esp_bd_addr_t phone_bda_{};
  uint32_t starting_at_{0};      // service start requested at
  uint32_t sent_at_{0};          // last status notification
  bool send_now_{false};         // a target changed: send the status on the next loop
#endif
};

#ifdef USE_SWITCH
/// "Capture the app's commands": on starts capture mode, off (or 10 minutes) stops it. Always off after a restart.
class CaptureSwitch : public switch_::Switch, public Component {
 public:
  void set_capture(AppCapture *c) { this->capture_ = c; }
  void setup() override { this->publish_state(false); }

 protected:
  void write_state(bool state) override;
  AppCapture *capture_{nullptr};
};
#endif

#ifdef USE_BUTTON
/// "Clear captured app commands".
class CaptureClearButton : public button::Button, public Component {
 public:
  void set_capture(AppCapture *c) { this->capture_ = c; }

 protected:
  void press_action() override {
    if (this->capture_ != nullptr)
      this->capture_->clear();
  }
  AppCapture *capture_{nullptr};
};
#endif

}  // namespace gravity980
}  // namespace esphome
