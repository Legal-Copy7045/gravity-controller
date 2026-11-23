#include "capture_ble.h"
#include "gravity980.h"

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#ifdef USE_GRAVITY980_CAPTURE
#include <algorithm>
#include <cstring>
#include <esp_gap_ble_api.h>
#include "esphome/components/esp32_ble/ble.h"
#include "esphome/components/esp32_ble_server/ble_2902.h"
#include "esphome/components/esp32_ble_server/ble_characteristic.h"
#include "esphome/components/esp32_ble_server/ble_service.h"
#ifdef USE_IMPROV_BLE
#include "esphome/components/improv_ble/improv_ble_component.h"
#endif
#endif

namespace esphome {
namespace gravity980 {

using namespace ::g980proto;

static const char *const TAG = "CAPTURE";

uint32_t AppCapture::millis_() { return millis(); }

void AppCapture::record_(const CaptureRecord &r) {
  {
    std::lock_guard<std::mutex> g(this->lock_);
    this->log_.add(r);
  }
  ESP_LOGI(TAG, "%s", capture_line(r).c_str());
  this->dirty_ = true;
}

void AppCapture::clear() {
  {
    std::lock_guard<std::mutex> g(this->lock_);
    this->log_.clear();
  }
  this->dirty_ = true;
}

void AppCapture::publish_switch_(bool on) {
#ifdef USE_SWITCH
  if (this->switch_ != nullptr)
    this->switch_->publish_state(on);  // also when unchanged: a refused "on" must reach Home Assistant as off
#endif
}

std::string AppCapture::json() {
  std::lock_guard<std::mutex> g(this->lock_);
  const bool on = this->state_ != State::OFF;
  const uint32_t used = this->started_at_ ? millis() - this->started_at_ : 0;
  char b[256];
  std::snprintf(b, sizeof b,
                "{\"available\":%s,\"active\":%s,\"advertising\":%s,\"left_s\":%u,\"name\":\"%s\",\"connected\":%s,"
                "\"subscribed\":%s,\"total\":%u,",
#ifdef USE_GRAVITY980_CAPTURE
                "true",
#else
                "false",
#endif
                on ? "true" : "false", this->state_ == State::ON ? "true" : "false",
                on && used < CAPTURE_MS ? unsigned((CAPTURE_MS - used + 999) / 1000) : 0u, on ? this->name_ : "",
                this->connected_ ? "true" : "false", this->subscribed_ ? "true" : "false", unsigned(this->log_.total()));
  // why_off_ is fixed text from this file (no quotes to escape).
  return std::string(b) + "\"why_off\":\"" + this->why_off_ + "\",\"records\":" + this->log_.json() + "}";
}

void AppCapture::loop(uint32_t now) {
  if (this->dirty_.exchange(false)) {
#ifdef USE_TEXT_SENSOR
    if (this->text_ != nullptr) {
      std::string s;
      {
        std::lock_guard<std::mutex> g(this->lock_);
        s = this->log_.summary(255);
      }
      this->text_->publish_state(s);
    }
#endif
  }
  if (this->state_ == State::OFF)
    return;
  if (now - this->started_at_ >= CAPTURE_MS) {
    this->stop("10 minutes are up");
    return;
  }
#ifdef USE_GRAVITY980_CAPTURE
  auto *server = esp32_ble_server::global_ble_server;
  if (esp32_ble::global_ble == nullptr || !esp32_ble::global_ble->is_active() || server == nullptr ||
      !server->is_running()) {
    this->stop("Bluetooth stopped");
    return;
  }
  if (this->state_ == State::STARTING) {
    if (this->svc_->is_failed()) {
      this->stop("its Bluetooth service couldn't be set up");
      return;
    }
    // Called each loop while the characteristics are created one by one, then once more to start the service.
    if (this->svc_->is_created() || this->svc_->is_stopped())
      this->svc_->start();
    if (this->svc_->is_running() && this->notify_handle_ != 0) {
      {
        std::lock_guard<std::mutex> g(this->lock_);
        this->state_ = State::ON;
      }
      this->advertise_(true);
      this->record_(capture_event(now - this->started_at_, CaptureEvent::STARTED));
      ESP_LOGI(TAG, "Advertising as %s: open the Char-Griller app and connect to it", this->name_);
    } else if (now - this->starting_at_ > 15000) {
      this->stop("its Bluetooth service didn't start");
    }
    return;
  }
  if (this->phone_ && this->notify_handle_ != 0 && (this->send_now_ || now - this->sent_at_ >= CAPTURE_NOTIFY_MS))
    this->send_status_();
#endif
}

std::string AppCapture::start() {
  if (this->state_ != State::OFF)
    return "";
  std::string why;
#ifndef USE_GRAVITY980_CAPTURE
  why = "this controller has no Bluetooth";
#else
  auto *ble = esp32_ble::global_ble;
  auto *server = esp32_ble_server::global_ble_server;
  if (ble == nullptr || !ble->is_active())
    why = "Bluetooth isn't running (try again in a minute)";
  else if (server == nullptr || !server->is_running())
    why = "the Bluetooth server isn't ready yet (try again in a minute)";
#ifdef USE_IMPROV_BLE
  // Improv (Wi-Fi setup over Bluetooth) advertises from the same radio during the first minutes without Wi-Fi.
  else if (improv_ble::global_improv_component != nullptr &&
           (improv_ble::global_improv_component->is_active() || improv_ble::global_improv_component->should_start()))
    why = "Wi-Fi setup over Bluetooth (Improv) is running: try again once the controller is on your Wi-Fi";
#endif
#endif
  if (!why.empty()) {
    {
      std::lock_guard<std::mutex> g(this->lock_);
      this->why_off_ = "Didn't start: " + why;
    }
    ESP_LOGW(TAG, "Capture mode didn't start: %s", why.c_str());
    this->publish_switch_(false);
    return why;
  }
#ifdef USE_GRAVITY980_CAPTURE
  uint8_t mac[6]{};
  ble->get_mac_msb_first(mac);
  std::snprintf(this->name_, sizeof this->name_, "Gravity980-%02X%02X", mac[4], mac[5]);
  if (this->svc_ == nullptr) {
    using esp32_ble_server::BLECharacteristic;
    // Created once, started and stopped per session. 1 service + 2 x (declaration, value) + the CCCD = 6 handles.
    this->svc_ = server->create_service(esp32_ble::ESPBTUUID::from_uint16(CAPTURE_SVC_UUID), true, 10);
    if (this->svc_ == nullptr) {
      this->publish_switch_(false);
      return "its Bluetooth service couldn't be created";
    }
    this->write_chr_ = this->svc_->create_characteristic(
        CAPTURE_WRITE_UUID, esp_gatt_char_prop_t(BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR),
        ESP_GATT_PERM_WRITE);
    this->write_chr_->on_write([this](std::span<const uint8_t> v, uint16_t conn) {
      this->on_write_(CAPTURE_WRITE_UUID, v, conn);
    });
    this->notify_chr_ = this->svc_->create_characteristic(
        CAPTURE_NOTIFY_UUID, esp_gatt_char_prop_t(BLECharacteristic::PROPERTY_NOTIFY | BLECharacteristic::PROPERTY_READ),
        ESP_GATT_PERM_READ);
    this->notify_chr_->add_descriptor(new esp32_ble_server::BLE2902());  // NOLINT(cppcoreguidelines-owning-memory)
  }
  this->fake_.reset(this->parent_->has_status() ? &this->parent_->last_status() : nullptr);
  uint8_t note[FakeGrill::NOTIFY_LEN];
  this->fake_.notification(note);
  this->notify_chr_->set_value(note, sizeof note);
  // The real grill's link is paused: the app might reach for it too, and nothing captured ever goes to it.
  this->parent_->set_capture_pause(true);
  // Our name while capturing: in the advertisement and as the GAP device name the phone reads.
  ble->set_name(this->name_);
  esp_ble_gap_set_device_name(this->name_);
  const uint32_t now = millis();
  {
    std::lock_guard<std::mutex> g(this->lock_);
    this->state_ = State::STARTING;
    this->started_at_ = now ? now : 1;
    this->why_off_.clear();
  }
  this->starting_at_ = now;
  this->send_now_ = false;
  this->publish_switch_(true);
  ESP_LOGI(TAG, "Capture mode on for 10 minutes (the grill's Bluetooth link is paused; nothing is sent to it)");
#endif
  return "";
}

void AppCapture::stop(const char *why) {
  if (this->state_ == State::OFF) {
    this->publish_switch_(false);
    return;
  }
  this->record_(capture_event(this->elapsed_(), CaptureEvent::STOPPED));
  ESP_LOGI(TAG, "Capture mode off (%s)", why);
#ifdef USE_GRAVITY980_CAPTURE
  this->drop_phone_();
  this->advertise_(false);
  auto *ble = esp32_ble::global_ble;
  const bool up = ble != nullptr && ble->is_active();
  if (this->svc_ != nullptr && up && (this->svc_->is_running() || this->svc_->is_starting()))
    this->svc_->stop();
  if (!up)
    this->notify_handle_ = this->cccd_handle_ = 0;  // Bluetooth restarted: the service comes back with new handles
  if (ble != nullptr) {
    ble->set_name(nullptr);  // back to the controller's own name (base.yaml sets no esp32_ble name)
    char buf[esp32_ble::ESP32BLE::DEVICE_NAME_BUFFER_SIZE];
    if (up) {
      esp_ble_gap_set_device_name(ble->device_name(buf));
      ble->advertising_set_service_data_and_name(std::span<const uint8_t>{}, false);
    }
  }
  this->parent_->set_capture_pause(false);
#endif
  {
    std::lock_guard<std::mutex> g(this->lock_);
    this->state_ = State::OFF;
    this->started_at_ = 0;
    this->why_off_ = std::string("Off: ") + why;
  }
  this->connected_ = this->subscribed_ = false;
  this->publish_switch_(false);
}

#ifdef USE_GRAVITY980_CAPTURE
void AppCapture::advertise_(bool on) {
  auto *ble = esp32_ble::global_ble;
  if (ble == nullptr || on == this->advertising_)
    return;
  this->advertising_ = on;
  if (on) {
    ble->advertising_set_service_data_and_name(std::span<const uint8_t>{}, true);  // the name in the advert itself
    ble->advertising_start();
  } else {
    ble->advertising_stop();
  }
}

void AppCapture::drop_phone_() {
  if (!this->phone_)
    return;
  esp_ble_gap_disconnect(this->phone_bda_);
  this->phone_ = false;
}

void AppCapture::send_status_() {
  uint8_t buf[FakeGrill::NOTIFY_LEN];
  this->fake_.notification(buf);
  this->notify_chr_->set_value(buf, sizeof buf);
  // Sent from the moment a phone connects, as the real grill does (subscribed or not); 20 bytes fit the default MTU.
  esp_err_t err = esp_ble_gatts_send_indicate(esp32_ble_server::global_ble_server->get_gatts_if(), this->phone_conn_,
                                              this->notify_handle_, sizeof buf, buf, false);
  if (err != ESP_OK)
    ESP_LOGD(TAG, "Status notification failed: %d", err);
  this->sent_at_ = millis();
  this->send_now_ = false;
}

void AppCapture::on_write_(uint16_t uuid, std::span<const uint8_t> value, uint16_t conn_id) {
  if (this->state_ == State::ON && this->phone_ && conn_id == this->phone_conn_) {
    this->record_(capture_write(this->elapsed_(), uuid, value.data(), value.size()));
    if (this->fake_.apply_write(value.data(), value.size()))
      this->send_now_ = true;  // the app sees its new target straight away
  }
  // The characteristic keeps what was written: wipe it (it may be a Wi-Fi password the app tried to provision).
  auto &kept = this->write_chr_->get_value();
  std::fill(kept.begin(), kept.end(), 0);
  kept.clear();
  kept.shrink_to_fit();
}

void AppCapture::gatts_event_handler(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if,
                                     esp_ble_gatts_cb_param_t *param) {
  if (this->svc_ == nullptr)
    return;  // never switched on since boot: nothing of ours exists
  switch (event) {
    case ESP_GATTS_ADD_CHAR_EVT:
      if (param->add_char.status == ESP_GATT_OK && param->add_char.service_handle == this->svc_->get_handle() &&
          esp32_ble::ESPBTUUID::from_uuid(param->add_char.char_uuid) ==
              esp32_ble::ESPBTUUID::from_uint16(CAPTURE_NOTIFY_UUID))
        this->notify_handle_ = param->add_char.attr_handle;
      break;
    case ESP_GATTS_ADD_CHAR_DESCR_EVT:
      if (param->add_char_descr.status == ESP_GATT_OK &&
          param->add_char_descr.service_handle == this->svc_->get_handle() &&
          esp32_ble::ESPBTUUID::from_uuid(param->add_char_descr.descr_uuid) ==
              esp32_ble::ESPBTUUID::from_uint16(ESP_GATT_UUID_CHAR_CLIENT_CONFIG))
        this->cccd_handle_ = param->add_char_descr.attr_handle;
      break;
    case ESP_GATTS_CONNECT_EVT: {
      // Links the controller opened itself (to the grill, the thermometer, the proxy's devices) show up here too.
      if (param->connect.link_role != 1 || this->state_ != State::ON)
        break;
      if (this->phone_) {
        // One phone at a time (advertising stops while one is connected; this is for a race).
        esp_ble_gap_disconnect(param->connect.remote_bda);
        this->record_(capture_event(this->elapsed_(), CaptureEvent::REFUSED));
        break;
      }
      this->phone_ = true;
      this->phone_conn_ = param->connect.conn_id;
      std::memcpy(this->phone_bda_, param->connect.remote_bda, sizeof(esp_bd_addr_t));
      this->connected_ = true;
      this->subscribed_ = false;
      this->advertise_(false);  // nobody else can find it meanwhile
      this->sent_at_ = millis() - CAPTURE_NOTIFY_MS + 500;  // first status half a second after connecting
      this->record_(capture_event(this->elapsed_(), CaptureEvent::CONNECT));
      break;
    }
    case ESP_GATTS_DISCONNECT_EVT:
      if (!this->connected_ || param->disconnect.conn_id != this->phone_conn_)
        break;
      this->phone_ = false;
      this->connected_ = this->subscribed_ = false;
      this->record_(capture_event(this->elapsed_(), CaptureEvent::DISCONNECT));
      if (this->state_ == State::ON)
        this->advertise_(true);  // the app may reconnect
      break;
    case ESP_GATTS_WRITE_EVT:
      if (this->cccd_handle_ != 0 && param->write.handle == this->cccd_handle_ && this->phone_ &&
          param->write.conn_id == this->phone_conn_ && !param->write.is_prep && param->write.len == 2) {
        const bool sub = (param->write.value[0] & 0x03) != 0;
        if (sub != this->subscribed_) {
          this->subscribed_ = sub;
          this->record_(capture_event(this->elapsed_(), sub ? CaptureEvent::SUBSCRIBE : CaptureEvent::UNSUBSCRIBE));
        }
      }
      break;
    default:
      break;
  }
}
#endif

#ifdef USE_SWITCH
void CaptureSwitch::write_state(bool state) {
  if (this->capture_ == nullptr)
    return;
  if (state)
    this->capture_->start();  // publishes the outcome (off again if it couldn't start)
  else
    this->capture_->stop("switched off");
}
#endif

}  // namespace gravity980
}  // namespace esphome
