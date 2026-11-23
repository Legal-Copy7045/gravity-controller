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
  // An H5198 advertises service 0x9851 (company id varies by unit; 0x3022 on some), or "H5198" in its name.
  bool is_h5198 = device.get_name().find("H5198") != std::string::npos;
  for (const auto &u : device.get_service_uuids())
    if (u == ble_device_base::ESPBTUUID::from_uint16(h5198::SERVICE_UUID))
      is_h5198 = true;
  for (const auto &md : device.get_manufacturer_datas())
    if (md.uuid == ble_device_base::ESPBTUUID::from_uint16(h5198::COMPANY_ID_ALT))
      is_h5198 = true;
  if (!is_h5198)
    return false;
  for (const auto &md : device.get_manufacturer_datas()) {
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
      return this->address_ != 0;  // not a probe packet (other Govee devices share the company id)
    const uint32_t now = millis();
    if (this->address_ == 0) {
      // Use the first device that sends real probe packets, and remember it once it has been heard steadily for a
      // minute (a look-alike passing by isn't remembered for good).
      const uint64_t a = device.address_uint64();
      const auto v = this->cand_.heard(a, now);
      if (v == h5198::Candidate::IGNORE)
        return false;
      if (a != this->cand_used_) {
        this->cand_used_ = a;
        for (auto &f : this->filter_)
          f.reset();
        ESP_LOGI(TAG, "Hearing a Govee H5198 (RSSI %d); remembered once it's been heard for a minute",
                 device.get_rssi());
      }
      if (v == h5198::Candidate::LOCK) {
        this->address_ = a;
        this->cand_.reset();
        ESP_LOGI(TAG, "Using this H5198 from now on");
        if (!this->fixed_) {
          uint64_t sa = a;
          this->pref_.save(&sa);
        }
      }
    }
    this->last_packet_ = now;
    for (int k = 0; k < 2; k++) {
      int i = r.first_probe + k;
      auto *s = this->probes_[i];
      float c = r.temp_c[k];
      // A reading that jumps 15 °C within 10 s counts only once it repeats (3 advertisements in a row).
      if (!this->filter_[i].accept(c, now)) {
        ESP_LOGD(TAG, "Probe %d: ignoring a sudden jump to %.1f °C (waiting for it to repeat)", i + 1, c);
        continue;
      }
      if (!std::isnan(c))
        this->last_seen_[i] = now;
      if (s == nullptr)
        continue;
      float v = std::isnan(c) ? NAN : (this->fahrenheit_ ? c * 1.8f + 32.0f : c);
      v = std::isnan(v) ? NAN : std::round(v * 10.0f) / 10.0f;
      if (!s->has_state() || (std::isnan(v) != std::isnan(s->state)) || (!std::isnan(v) && v != s->state))
        s->publish_state(v);
      // The probe's alarm on the thermometer (its own target), when set.
      auto *a = this->alarms_[i];
      if (a != nullptr) {
        float ac = r.alarm_high_c[k];
        float av = std::isnan(ac) ? NAN : std::round((this->fahrenheit_ ? ac * 1.8f + 32.0f : ac) * 10.0f) / 10.0f;
        if (!a->has_state() || (std::isnan(av) != std::isnan(a->state)) || (!std::isnan(av) && av != a->state))
          a->publish_state(av);
      }
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
  // The thermometer found last time, so a neighbour's H5198 (or a look-alike) is never picked up instead of yours.
  this->pref_ = global_preferences->make_preference<uint64_t>(fnv1_hash("govee_h5198_address_v1"), true);
  uint64_t saved = 0;
  if (!this->fixed_ && this->pref_.load(&saved) && saved != 0) {
    this->address_ = saved;
    ESP_LOGI(TAG, "Using the remembered H5198");
  }
  if (this->connected_ != nullptr)
    this->connected_->publish_state(false);  // not heard yet
}

void GoveeH5198::forget() {
  if (this->fixed_) {
    ESP_LOGW(TAG, "The H5198's address is set in the YAML (mac_address): nothing to forget");
    return;
  }
  this->address_ = 0;
  this->cand_.reset();
  this->cand_used_ = 0;
  for (auto &f : this->filter_)
    f.reset();
  uint64_t z = 0;
  this->pref_.save(&z);
  ESP_LOGI(TAG, "Forgot the H5198: the next one heard is used");
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
