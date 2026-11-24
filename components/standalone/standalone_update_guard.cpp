// Automatic rollback after a bad update.
//
// The bootloader keeps the previous firmware. A new one starts "on trial" (ESP-IDF app rollback, which ESPHome
// enables): if it restarts before it's confirmed (a crash, a hang the watchdog catches), the bootloader goes back to
// the previous one. ESPHome's safe mode confirms it after `boot_is_good_after` (15 min here, firmware/base.yaml).
// This adds a health check on top: the new firmware is confirmed as soon as it has held its Wi-Fi for a minute; if
// it hasn't within 10 minutes (it can't reach the network, so it could never be updated again), it rolls itself back.
// After a rollback the controller says so once, and remembers the version so automatic updates skip it (installing
// it by hand still works).

#include "standalone.h"

#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "../cook_assistant/cook_assistant.h"

#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif
#if defined(USE_ESP32) && defined(USE_OTA_ROLLBACK)
#include <esp_ota_ops.h>
#endif

namespace esphome {
namespace standalone {

static const char *const TAG = "standalone.update";

struct GuardBlob {
  char skip[32];      // a version that was rolled back (automatic updates skip it)
  char notified[32];  // the rollback already reported
};

void Standalone::guard_setup_() {
  this->guard_pref_ = global_preferences->make_preference<GuardBlob>(fnv1_hash("standalone_update_guard_v1"));
  GuardBlob b{};
  if (this->guard_pref_.load(&b)) {
    b.skip[sizeof(b.skip) - 1] = 0;
    this->skip_version_ = b.skip;
  }
#if defined(USE_ESP32) && defined(USE_OTA_ROLLBACK)
  esp_ota_img_states_t st;
  const esp_partition_t *running = esp_ota_get_running_partition();
  this->on_trial_ = running != nullptr && esp_ota_get_state_partition(running, &st) == ESP_OK &&
                    st == ESP_OTA_IMG_PENDING_VERIFY;
  if (this->on_trial_)
    ESP_LOGW(TAG, "New firmware on trial: it's confirmed once it has held Wi-Fi for a minute");
  const esp_partition_t *bad = esp_ota_get_last_invalid_partition();
  esp_app_desc_t d{};
  if (bad != nullptr && esp_ota_get_partition_description(bad, &d) == ESP_OK && d.version[0] != 0) {
    b.notified[sizeof(b.notified) - 1] = 0;
    std::string v(d.version, strnlen(d.version, sizeof(d.version)));
    if (v != b.notified) {
      std::strncpy(b.skip, v.c_str(), sizeof(b.skip) - 1);
      std::strncpy(b.notified, v.c_str(), sizeof(b.notified) - 1);
      this->guard_pref_.save(&b);
      this->skip_version_ = v;
      this->rollback_notice_ = v;  // sent once the network is up (loop_guard_)
    }
  }
#endif
}

void Standalone::loop_guard_(uint32_t now) {
  if (!this->rollback_notice_.empty() && now > 60000) {
    const std::string v = this->rollback_notice_;
    this->rollback_notice_.clear();
    const std::string msg = "The update to " + v + " didn't pass its checks after installing, so the controller went "
                            "back to " + ESPHOME_PROJECT_VERSION + ". Automatic updates will skip " + v +
                            "; you can still install it by hand.";
    if (this->cook_ != nullptr)
      this->cook_->notify("Update rolled back", msg, 1, "update");
    else
      this->notify("Update rolled back", msg, 1, "update");
  }
#if defined(USE_ESP32) && defined(USE_OTA_ROLLBACK)
  if (!this->on_trial_)
    return;
  bool wifi = false;
#ifdef USE_WIFI
  wifi = wifi::global_wifi_component != nullptr && wifi::global_wifi_component->is_connected();
#endif
  if (wifi) {
    if (this->trial_wifi_since_ == 0)
      this->trial_wifi_since_ = now ? now : 1;
    if (now - this->trial_wifi_since_ > 60000 && now > 90000) {
      this->on_trial_ = false;
      esp_ota_mark_app_valid_cancel_rollback();
      ESP_LOGI(TAG, "New firmware confirmed (Wi-Fi up for a minute, no crash)");
      if (!this->skip_version_.empty() && this->skip_version_ == ESPHOME_PROJECT_VERSION) {
        GuardBlob b{};
        this->guard_pref_.load(&b);
        b.skip[0] = 0;  // installed by hand and working: no need to skip it any more
        this->guard_pref_.save(&b);
        this->skip_version_.clear();
      }
    }
  } else {
    this->trial_wifi_since_ = 0;
    if (now > 10 * 60000) {
      ESP_LOGE(TAG, "New firmware hasn't kept a Wi-Fi connection in 10 min: going back to the previous one");
      this->on_trial_ = false;
      esp_ota_mark_app_invalid_rollback_and_reboot();
    }
  }
#endif
}

}  // namespace standalone
}  // namespace esphome
