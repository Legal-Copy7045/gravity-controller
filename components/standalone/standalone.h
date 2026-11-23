#pragma once
// Everything the controller needs to run without Home Assistant (docs/standalone.md):
//  - the device page's PIN (pin_auth.h): once set, every change made through the device page needs it;
//  - write-only secrets (notification keys, AI key): stored in flash, never sent back out, only "set / not set";
//  - notifications straight to a phone (ntfy, Pushover, Telegram), routed via Home Assistant, direct, or both;
//  - weather and the forecast from Open-Meteo for a location stored only here;
//  - the time zone (sent by the device page, worked out by the browser) for internet time without Home Assistant.
// HTTP calls run in a worker task so the grill link never waits on the internet.

#include <atomic>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <vector>

#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/preferences.h"

#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif

#include "pin_auth.h"

namespace esphome {
namespace cook_assistant {
class CookAssistant;
}
namespace standalone {

// Fixed-size settings in flash. Secret fields are never returned by the web API.
struct Settings {
  uint32_t version{1};
  char route[8]{"auto"};       // notifications: auto | ha | direct | both
  char ntfy_server[96]{"https://ntfy.sh"};
  char ntfy_topic[72]{};       // secret: anyone with the topic can read it
  char pushover_user[48]{};    // secret
  char pushover_token[48]{};   // secret
  char telegram_token[80]{};   // secret
  char telegram_chat[32]{};    // secret
  char ai_provider[12]{};      // gemini | claude | openai (stage 3)
  char ai_model[48]{};
  char ai_key[232]{};          // secret
  float lat{NAN}, lon{NAN};    // private: rounded to 0.01° (about 1 km) when saved
  uint8_t tz_set{0};
  uint8_t tz_raw[32]{};        // a time::ParsedTimezone, as sent by the device page
};

struct Job {
  std::string what;  // "ntfy" / "pushover" / "telegram" / "weather"
  std::string method, url, body, content_type;
  std::vector<std::pair<std::string, std::string>> headers;
};

class Standalone : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override;  // before web_server: our check sees every request first

  void set_fahrenheit(bool f) { this->fahrenheit_ = f; }
  void set_wind_unit(const char *u) { this->wind_unit_ = u; }  // Open-Meteo's name: mph, kmh, ms
#ifdef USE_SENSOR
  void set_weather_sensors(sensor::Sensor *t, sensor::Sensor *h, sensor::Sensor *w) {
    this->wx_temp_ = t; this->wx_hum_ = h; this->wx_wind_ = w;
  }
#endif
  void set_cook_assistant(cook_assistant::CookAssistant *c) { this->cook_ = c; }

  // --- notifications (called from the cook assistant's on_notify) ---
  /// Should this notification also go out as a Home Assistant event?
  bool send_via_ha() const;
  /// Send straight to the phone when the route says so. priority: 0 normal, 1 high, 2 critical.
  void notify(const std::string &title, const std::string &message, int priority, const std::string &tag);
  void test_notify();

  // --- weather ---
  bool weather_here() const { return !std::isnan(this->s_.lat) && !std::isnan(this->s_.lon); }

  // --- recovery (BOOT button held, or Home Assistant) ---
  void clear_pin();

  // --- one-time move of the old "ntfy topic" text entity into the secret store ---
  bool migrate_ntfy_topic(const std::string &topic);

  // --- used by the web handler (httpd task; everything below takes the lock) ---
  std::string api(const std::string &method, const std::string &path, const std::string &body, const std::string &token,
                  int &status);
  bool write_allowed(const std::string &token);
  bool pin_set();

 protected:
  void save_();
  void apply_tz_();
  void queue_(Job j);
  void worker_();
  static void worker_task_(void *arg);
  void fetch_weather_();
  std::string status_json_(bool authed);
  bool direct_configured_() const;

  Settings s_{};
  ESPPreferenceObject pref_, pin_pref_;
  pinauth::Guard *guard_{nullptr};
  std::recursive_mutex lock_;
  bool fahrenheit_{true};
  const char *wind_unit_{"mph"};
  cook_assistant::CookAssistant *cook_{nullptr};
#ifdef USE_SENSOR
  sensor::Sensor *wx_temp_{nullptr}, *wx_hum_{nullptr}, *wx_wind_{nullptr};
#endif

  // worker
  std::deque<Job> jobs_;
  std::mutex jobs_lock_;
  void *jobs_sem_{nullptr};
  // results handed back to the main loop
  std::mutex results_lock_;
  std::string last_result_[3];  // ntfy, pushover, telegram
  bool wx_ready_{false};
  float wx_t_{NAN}, wx_h_{NAN}, wx_w_{NAN};
  std::vector<float> fc_min_, fc_t_;
  uint32_t wx_at_{0}, wx_fetched_{0};
  std::atomic<bool> save_pending_{false};
};

}  // namespace standalone
}  // namespace esphome
