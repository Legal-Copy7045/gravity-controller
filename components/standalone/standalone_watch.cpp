// The connectivity watchdog: one status line, notices during a cook, and a last-resort restart for a stuck Wi-Fi.
//
// What it watches (every 10 s): the grill's link (gravity980 already recovers it: reconnects, Bluetooth restarts,
// a capped restart), the controller's own Wi-Fi, Home Assistant (loop_ha_watch_ in standalone_ai.cpp recovers it:
// a Wi-Fi bounce after 10 min, one restart after an hour, never during a cook) and the internet (the last request
// out: weather, notifications, AI, sharing; nothing extra is sent to check).
// What it adds:
//  * "Connectivity": "Grill: Bluetooth · Wi-Fi: -61 dBm · Home Assistant: connected · Internet: OK (3 min ago)";
//  * during a cook, Home Assistant gone for 5 min: a direct notice that alerts now come straight to the phone (if a
//    direct route is set up); and when the controller's Wi-Fi comes back after 2+ min down: what was missed;
//  * the controller's Wi-Fi, after working since this start, down 20 min with no cook: a restart, at most once every
//    6 hours and 3 in a row (never during a cook: the grill link and the program carry on over Bluetooth);
//  * "Local only": the internet clock is kept stopped.

#include "standalone.h"

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "../cook_assistant/cook_assistant.h"

#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif
#ifdef USE_API
#include "esphome/components/api/api_server.h"
#endif
#ifdef USE_ESP32
#include "esp_sntp.h"
#include <esp_attr.h>
#endif

namespace esphome {
namespace standalone {

static const char *const TAG = "standalone.watch";

// Watchdog restarts in a row, kept across them (RTC memory survives a software restart, not a power cut): at most 3
// until Wi-Fi has stayed up for an hour, so a network that's really gone can't make the controller restart forever.
#ifdef USE_ESP32
static RTC_NOINIT_ATTR uint32_t watch_restarts;
static RTC_NOINIT_ATTR uint32_t watch_magic;
#else
static uint32_t watch_restarts, watch_magic;
#endif
static const uint32_t WATCH_MAGIC = 0x57415443;
static uint32_t &restarts_in_a_row() {
  if (watch_magic != WATCH_MAGIC) {
    watch_magic = WATCH_MAGIC;
    watch_restarts = 0;
  }
  return watch_restarts;
}

static std::string ago(uint32_t now, uint32_t t) {
  const uint32_t m = (now - t) / 60000;
  if (m < 1)
    return "just now";
  if (m < 120)
    return std::to_string(m) + " min ago";
  return std::to_string(m / 60) + " h ago";
}

void Standalone::loop_watch_(uint32_t now) {
  if (now - this->watch_at_ < 10000 && this->watch_at_ != 0)
    return;
  this->watch_at_ = now ? now : 1;
  const bool cooking = this->cook_ != nullptr && this->cook_->cook_active();

#ifdef USE_ESP32
  // Local only: no internet clock (Home Assistant's clock still works).
  if (this->local_only_) {
    if (esp_sntp_enabled()) {
      esp_sntp_stop();
      this->sntp_stopped_ = true;
      ESP_LOGI(TAG, "Local only: internet clock stopped");
    }
  } else if (this->sntp_stopped_) {
    this->sntp_stopped_ = false;
    if (!esp_sntp_enabled())
      esp_sntp_init();
  }
#endif

  std::string line;
  // The grill
#ifdef USE_BINARY_SENSOR
  if (this->grill_link_ != nullptr)
    line += std::string("Grill: ") + (this->grill_link_->has_state() && this->grill_link_->state ? "connected" : "not connected");
#endif
  // Wi-Fi
  bool wifi_ok = true;
#ifdef USE_WIFI
  if (wifi::global_wifi_component != nullptr) {
    wifi_ok = wifi::global_wifi_component->is_connected();
    if (wifi_ok)
      this->wifi_was_up_ = true;
    if (!line.empty())
      line += " · ";
    if (wifi_ok) {
      if (this->wifi_up_since_ == 0)
        this->wifi_up_since_ = now ? now : 1;
      if (now - this->wifi_up_since_ > 3600000UL)
        restarts_in_a_row() = 0;  // an hour up: the slate is clean
      const int rssi = wifi::global_wifi_component->wifi_rssi();
      line += "Wi-Fi: " + std::to_string(rssi) + " dBm" + (rssi < -80 ? " (weak)" : "");
    } else {
      line += "Wi-Fi: not connected";
    }
    if (!wifi_ok) {
      this->wifi_up_since_ = 0;
      if (this->wifi_down_at_ == 0) {
        this->wifi_down_at_ = now ? now : 1;
        this->wifi_down_in_cook_ = cooking;
      }
      this->wifi_down_in_cook_ = this->wifi_down_in_cook_ || cooking;
      const uint32_t down = now - this->wifi_down_at_;
      // Only a Wi-Fi that worked since this start and then got stuck: a controller not set up yet, or one whose network
      // is gone, keeps its setup hotspot and its Bluetooth link to the grill instead of restarting.
      if (down > 20 * 60000 && !cooking && this->wifi_was_up_ && restarts_in_a_row() < 3 &&
          (this->wifi_reboot_at_ == 0 || now - this->wifi_reboot_at_ > 6 * 3600000UL)) {
        this->wifi_reboot_at_ = now ? now : 1;
        restarts_in_a_row()++;
        ESP_LOGW(TAG, "Wi-Fi down for %u min and no cook: restarting the controller", unsigned(down / 60000));
        this->set_timeout("watch_reboot", 1000, []() { App.safe_reboot(); });
      }
    } else if (this->wifi_down_at_ != 0) {
      const uint32_t down = now - this->wifi_down_at_;
      this->wifi_down_at_ = 0;
      if (this->wifi_down_in_cook_ && down > 2 * 60000 && this->cook_ != nullptr) {
        this->cook_->notify("Controller was offline",
                            "The controller lost its Wi-Fi for about " + std::to_string(down / 60000) +
                                " min during the cook. The cook carried on; any alerts from that time couldn't be sent.",
                            1, "offline");
      }
      this->wifi_down_in_cook_ = false;
    }
  }
#endif
  // Home Assistant
#ifdef USE_API
  if (api::global_api_server != nullptr && (this->ha_state_ & 1)) {
    const bool ha = api::global_api_server->is_connected();
    line += std::string(" · Home Assistant: ") + (ha ? "connected" : "not connected");
    if (ha) {
      if (this->ha_down_told_ && this->cook_ != nullptr)
        this->cook_->notify("Home Assistant is back", "Home Assistant is connected to the controller again.", 0,
                            "ha_link");
      this->ha_down_at_ = 0;
      this->ha_down_told_ = false;
    } else if (wifi_ok && now > 120000) {
      if (this->ha_down_at_ == 0)
        this->ha_down_at_ = now ? now : 1;
      if (cooking && !this->ha_down_told_ && now - this->ha_down_at_ > 5 * 60000) {
        this->ha_down_told_ = true;
        // Straight to the phone (the Home Assistant route is what's missing).
        this->notify("Home Assistant can't be reached",
                     "The controller hasn't heard from Home Assistant for 5 minutes. The cook carries on and alerts come "
                     "straight to this phone until it's back.",
                     1, "ha_link");
      }
    }
  }
#endif
  // Internet (from the last request out; nothing extra is sent to check)
  {
    const uint32_t ok = this->net_ok_at_, bad = this->net_fail_at_;
    std::string net;
    if (this->local_only_)
      net = "off (local only)";
    else if (ok == 0 && bad == 0)
      net = "not used yet";
    else if (ok != 0 && (bad == 0 || int32_t(ok - bad) > 0))
      net = "OK (" + ago(now, ok) + ")";
    else
      net = "failing (" + ago(now, bad) + ")";
    line += " · Internet: " + net;
#ifdef USE_API
    // Local only: alerts reach a phone only through Home Assistant (ntfy, Pushover and Telegram are on the internet).
    if (this->local_only_ && !(api::global_api_server != nullptr && api::global_api_server->is_connected()))
      line += " · Alerts: none can be sent (local only, and Home Assistant isn't connected)";
#else
    if (this->local_only_)
      line += " · Alerts: none can be sent (local only, and no Home Assistant)";
#endif
  }
  if (line != this->conn_text_) {
    this->conn_text_ = line;
#ifdef USE_TEXT_SENSOR
    if (this->conn_ts_ != nullptr)
      this->conn_ts_->publish_state(line);
#endif
  }
}

}  // namespace standalone
}  // namespace esphome
