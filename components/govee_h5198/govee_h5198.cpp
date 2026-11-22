#include "govee_h5198.h"

#include <cstdio>
#include <cstdlib>

#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

namespace esphome {
namespace govee_h5198 {

static const char *const TAG = "govee_h5198";
static const uint32_t STALE_MS = 60000;  // a probe not heard for a minute reads unknown

bool GoveeH5198::parse_device(const ble_device_base::ESPBTDevice &device) {
  if (this->address_ != 0 && device.address_uint64() != this->address_)
    return false;
  for (const auto &md : device.get_manufacturer_datas()) {
    if (!(md.uuid == ble_device_base::ESPBTUUID::from_uint16(h5198::COMPANY_ID)))
      continue;
    if (this->address_ == 0) {
      this->address_ = device.address_uint64();
      ESP_LOGI(TAG, "Found a Govee H5198 (RSSI %d); using it", device.get_rssi());
    }
    const auto &d = md.data;
    if (this->log_raw_) {
      char hex[3 * 32 + 1] = {0};
      size_t n = std::min<size_t>(d.size(), 32);
      for (size_t i = 0; i < n; i++)
        std::snprintf(hex + 3 * i, 4, "%02X ", d[i]);
      ESP_LOGD(TAG, "H5198 adv (%u): %s", (unsigned) d.size(), hex);
    }
    auto r = h5198::decode(d.data(), d.size());
    if (r.first_probe < 0)
      return true;
    const uint32_t now = millis();
    this->last_packet_ = now;
    for (int k = 0; k < 2; k++) {
      int i = r.first_probe + k;
      auto *s = this->probes_[i];
      float c = r.temp_c[k];
      if (!std::isnan(c))
        this->last_seen_[i] = now;
      if (s == nullptr)
        continue;
      float v = std::isnan(c) ? NAN : (this->fahrenheit_ ? c * 1.8f + 32.0f : c);
      v = std::isnan(v) ? NAN : std::round(v * 10.0f) / 10.0f;
      if (!s->has_state() || (std::isnan(v) != std::isnan(s->state)) || (!std::isnan(v) && v != s->state))
        s->publish_state(v);
    }
    // Signal strength: on a real change or every 30 s (the thermometer advertises several times a second).
    int rssi = device.get_rssi();
    if (this->rssi_ != nullptr && (!this->rssi_->has_state() || std::abs(rssi - this->last_rssi_) >= 3 ||
                                   now - this->rssi_ms_ > 30000)) {
      this->rssi_->publish_state(rssi);
      this->last_rssi_ = rssi;
      this->rssi_ms_ = now;
    }
    if (this->connected_ != nullptr && !this->seen_)
      this->connected_->publish_state(true);
    this->seen_ = true;
    return true;
  }
  return false;
}

void GoveeH5198::setup() {
  if (this->connected_ != nullptr)
    this->connected_->publish_state(false);  // not heard yet
}

void GoveeH5198::loop() {
  const uint32_t now = millis();
  for (int i = 0; i < 4; i++) {
    auto *s = this->probes_[i];
    if (s != nullptr && s->has_state() && !std::isnan(s->state) && now - this->last_seen_[i] > STALE_MS)
      s->publish_state(NAN);
  }
  if (this->seen_ && now - this->last_packet_ > STALE_MS) {
    this->seen_ = false;
    if (this->connected_ != nullptr)
      this->connected_->publish_state(false);
  }
}

void GoveeH5198::dump_config() {
  ESP_LOGCONFIG(TAG, "Govee H5198: %s, unit %s", this->address_ ? "fixed address" : "first one heard",
                this->fahrenheit_ ? "°F" : "°C");
}

}  // namespace govee_h5198
}  // namespace esphome
