#pragma once
// Everything the controller needs to run without Home Assistant (docs/standalone.md):
//  - the device page's PIN (pin_auth.h): once set, every change made through the device page needs it. The first one
//    can only be set within 15 minutes of a restart or of clearing it; without one the page stays open to changes
//    (the owner's choice), but keys and settings can't be stored;
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
#include "esphome/components/json/json_util.h"

#ifdef USE_SENSOR
#include "esphome/components/sensor/sensor.h"
#endif

#include "pin_auth.h"

namespace esphome {
namespace cook_assistant {
class CookAssistant;
}
namespace binary_sensor {
class BinarySensor;
}
namespace sensor {
class Sensor;
}
namespace text_sensor {
class TextSensor;
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

// Stage 2 settings (a separate record: changing Settings' size would wipe the keys on upgrade).
struct Settings2 {
  uint32_t version{1};
  uint32_t serve_by{0};       // epoch (UTC), 0 = no plan
  uint16_t rest_min{60};
  uint8_t share_enabled{0};   // Open Pitmaster sharing from the controller: off unless turned on
  uint8_t share_auto{0};
  uint32_t auto_since{0};     // automatic sharing covers cooks that end after this
  uint32_t light_notified_for{0};
};

// One finished cook in the controller's journal (flash; JOURNAL_SLOTS kept).
struct JEntry {
  uint32_t id{0};             // random, 0 = empty slot
  uint32_t seq{0};            // order
  uint32_t ended{0};          // epoch, 0 = clock wasn't set
  char profile[16]{};
  float weight_kg{NAN}, pit_c{NAN}, target_c{NAN}, stall_h{NAN}, total_h{NAN}, ambient_c{NAN};
  uint8_t wrapped{2};         // 0 no, 1 yes, 2 unknown
  uint8_t rating{0};          // 0 = none
  uint16_t tags{0};           // bit i = TAGS[i]
  uint8_t share{0};           // 0 pending, 1 shared, 2 declined
  char share_id[33]{};
  char share_key[49]{};       // deletion key: never leaves except to delete
  char notes[100]{};
};
static constexpr size_t JOURNAL_SLOTS = 24;
static constexpr size_t HIST_SERIES = 8;  // pit, pit target, food 1-6
static constexpr size_t HIST_LEN = 1440;  // 24 h at one a minute

// Something that happened during a cook, for the device page's replay (standalone_replay.cpp).
struct CookEvent {
  uint32_t t{0};     // epoch
  uint8_t k{0};      // 1 lid opened, 2 wrapped, 3 unwrapped, 4 stall began, 5 stall ended, 6 program step,
                     // 7 charcoal topped up, 8 off the grill (pulled)
  uint8_t slot{0};   // food slot 1-6 (0: not a food's)
  uint16_t v{0};     // lid: seconds it was open; program step: its number; charcoal: the level (%)
};
static constexpr size_t CURVE_LEN = 120;
static constexpr size_t CURVE_EVENTS = 24;
// One journal entry's curves and events (flash, one record per journal slot, beside its JEntry; a separate record so
// the journal's own stays as it was). id 0, or another entry's id: none (a cook from before replays were kept).
struct JCurve {
  uint32_t id{0};          // the journal entry's id
  uint32_t start{0};       // epoch of the first point
  uint16_t step_s{0};      // seconds between points
  uint8_t n{0};            // points
  uint8_t slot{0};         // the food's slot (1-6), 0 = not known
  uint8_t ne{0};           // events
  uint8_t unit_f{1};       // temperatures in °F (else °C)
  uint8_t pad_[2]{};
  int16_t pit[CURVE_LEN]{};   // tenths of a degree, INT16_MIN = no reading
  int16_t food[CURVE_LEN]{};
  CookEvent ev[CURVE_EVENTS]{};
};

// The AI on the controller (a separate record, for the same reason as Settings2).
struct AiSettings {
  uint32_t version{1};
  uint8_t auto_advise{0};   // the AI pitmaster every interval_min during a cook: off unless turned on
  uint8_t interval_min{30};
};

struct Job {
  std::string what;  // "ntfy" / "pushover" / "telegram" / "weather"
  std::string method, url, body, content_type;
  std::vector<std::pair<std::string, std::string>> headers;
  uint8_t lane{0};  // 0: notifications, weather, sharing; 1: AI (slow: never holds up an alarm)
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
#ifdef USE_SENSOR
  void set_pit_sensors(sensor::Sensor *pit, sensor::Sensor *target) { this->pit_ = pit; this->pit_target_ = target; }
#endif
  /// A finished cook (the cook assistant's on_cook_complete JSON): into the journal.
  void add_cook(const std::string &summary_json);

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
  /// Home Assistant's "Clear the device page PIN" button: only once Home Assistant has adopted the controller (its
  /// API has a key). Until then anyone on the Wi-Fi could connect to the API and press it, reopening the first
  /// PIN's window for themselves; the BOOT button still works.
  void clear_pin_from_ha();
  /// Home Assistant's set_device_pin action: set or replace the device page's PIN whenever ("" clears it), without the
  /// first PIN's window. Only once Home Assistant has adopted the controller (its API has a key), like the Clear
  /// button. Hashing takes a second or two, so it's handed to the API task (never the main loop); the result goes to
  /// the log and pin_status().
  void set_pin_from_ha(const std::string &pin);
  /// For the "Device page PIN" sensor: "set" or "not set", and why Home Assistant's last PIN was refused. Never the PIN.
  std::string pin_status();

  // --- factory reset: wipes everything the controller stores (Wi-Fi, API key, PIN and sessions, keys, settings, the
  // journal, learned cooks) and restarts. Never on one press: a second press within 10 s does it.
  /// Home Assistant's "Factory reset" button (refused until Home Assistant has adopted the controller, like Clear).
  void factory_reset_from_ha();
  /// The BOOT button held 30 s (someone at the controller): no second press needed.
  void factory_reset_now(const char *why);
  /// For the "Factory reset status" sensor: "Press again...", "Erasing..." or why the last press was refused.
  std::string factory_reset_prompt();

  // --- the secret Home Assistant's Smoker integration sets (action set_event_secret) and checks on every event the
  // controller fires (smoker_notify, smoker_context, smoker_cook_complete): so a forged event is told apart. Stored
  // in flash, never shown in an entity, /local/ or the log. "" = none (the events then carry no secret).
  bool set_event_secret(const std::string &secret);
  const std::string &event_secret() const { return this->event_secret_; }

  // --- one-time move of the old "ntfy topic" text entity into the secret store ---
  bool migrate_ntfy_topic(const std::string &topic);

  // --- used by the web handler (httpd task; everything below takes the lock) ---
  /// client: the browser's IP address (the PIN's lockout is per client).
  std::string api(const std::string &method, const std::string &path, const std::string &body, const std::string &token,
                  const std::string &client, int &status);
  /// api() on the controller's API task (a roomy stack), waiting for the answer. Used by the web handler.
  std::string api_call(const char *method, const std::string &path, const std::string &body, const std::string &token,
                       const std::string &client, int &status);
  bool write_allowed(const std::string &token);
  bool pin_set();

 protected:
  void save_();
  void apply_tz_();
  void queue_(Job j);
  void worker_();
  static void worker_task_(void *arg);
  static void worker_task_ai_(void *arg);
  void worker_lane_(int lane);
  void fetch_weather_();
  // stage 2 (standalone_cook.cpp)
  void setup_cook_();
  void loop_cook_(uint32_t now);
  void sample_history_();
  void save_journal_(size_t slot);
  std::string history_json_(int hours);
  std::string journal_json_(bool authed);
  std::string community_json_();
  std::string record_json_(const JEntry &e, const char *id);  // the anonymous Open Pitmaster record
  bool share_entry_(JEntry &e, std::string &why);
  int light_by_(uint32_t now_epoch, float *est_min);
  void put_on_reminders_(uint32_t now_epoch);  // serve together: "put it on now", food by food
  uint32_t put_on_for_{0};                     // the serve-by time put_on_sent_ is for
  uint8_t put_on_sent_{0};                     // bit per food slot
  // cook replays (standalone_replay.cpp)
  void setup_replay_();
  void watch_events_(uint32_t now);
  void note_event_(uint32_t t, uint8_t k, uint8_t slot, uint16_t v);
  void keep_curve_(size_t slot, const JEntry &e, const std::string &probe_key);
  std::string curve_json_(const std::string &id_hex, int &status);
  JCurve *curves_{nullptr};  // JOURNAL_SLOTS of them, beside journal_ (PSRAM)
  ESPPreferenceObject cpref_[JOURNAL_SLOTS];
  uint32_t curve_dirty_{0};  // bit per slot: saved from the main loop
  static constexpr size_t EVENT_RING = 64;
  CookEvent events_[EVENT_RING]{};
  size_t ev_head_{0}, ev_count_{0}, ev_lid_at_{SIZE_MAX};
  uint32_t ev_polled_{0};
  bool ev_looked_{false}, ev_primed_{false};
  int8_t ev_lid_{-1};
  int ev_step_{-1};
  uint8_t ev_wrap_{0}, ev_stall_{0}, ev_pulled_{0};
  float ev_fuel_{NAN};
  binary_sensor::BinarySensor *ev_lid_bs_{nullptr};  // "Lid"
  sensor::Sensor *ev_fuel_s_{nullptr};               // "Charcoal level"
  text_sensor::TextSensor *ev_prog_ts_{nullptr};     // "Program status"
  std::string api_cook_(const std::string &path, JsonDocument &in, bool authed, int &status);
  std::string status_json_(bool authed);
  bool direct_configured_() const;
  std::string api_pin_(const std::string &path, const std::string &body, const std::string &token,
                       const std::string &client, int &status);
  // The PIN's state for the request being answered (API task only; read from guard_ under guard_lock_).
  bool req_pin_{false};
  uint32_t req_locked_{0}, req_first_pin_{0};

  Settings s_{};
  ESPPreferenceObject pref_, pin_pref_, evsec_pref_;
  struct EventSecret { uint8_t set; char s[65]; };
  std::string event_secret_;
  pinauth::Guard *guard_{nullptr};
  std::recursive_mutex lock_;
  std::mutex guard_lock_;
  bool clear_pin_pending_{false};  // the PIN and sessions (guard_): never held by the main loop while waiting
  // Home Assistant's PIN (set_pin_from_ha), waiting for the API task. Wiped once used.
  std::mutex ha_pin_lock_;
  std::string ha_pin_;
  bool ha_pin_has_{false};
  std::atomic<bool> ha_pin_pending_{false};  // the main loop still has to hand it to the API task
  std::atomic<bool> pin_cached_{false};      // guard_->pin_set(), for pin_status() without waiting on the lock
  std::string pin_note_;                     // why Home Assistant's last PIN was refused (under results_lock_)
  void set_pin_work_();                      // on the API task
  // Factory reset (under results_lock_): two presses within 10 s; done by the main loop a second later.
  pinauth::ConfirmTwice reset_confirm_{};
  std::string reset_refused_;
  uint32_t reset_refused_at_{0};
  std::atomic<bool> reset_pending_{false};
  uint32_t reset_at_{0};
  bool factory_reset_press_(const char *who);  // true: confirmed
  bool fahrenheit_{true};
  const char *wind_unit_{"mph"};
  cook_assistant::CookAssistant *cook_{nullptr};
#ifdef USE_SENSOR
  sensor::Sensor *wx_temp_{nullptr}, *wx_hum_{nullptr}, *wx_wind_{nullptr};
#endif

  // worker
  std::deque<Job> jobs_[2];
  std::mutex jobs_lock_[2];
  void *jobs_sem_[2]{nullptr, nullptr};
  bool ai_task_{false};  // the AI lane's task, started on first use
  // Unlocked browsers survive a restart (pin_auth.h Guard::tokens/restore).
  struct SavedSessions { uint8_t n; char tok[4][65]; };  // before 0.2.51: tokens only (each got a fresh 12 h)
  struct SavedSessions2 { uint8_t n; char tok[4][65]; uint32_t left_s[4]; uint32_t epoch_expires[4]; };
  ESPPreferenceObject sess_pref_;
  uint32_t sess_gen_{0};
  uint32_t sess_saved_at_{0};  // last save while sessions were live (their time left is saved again every 30 min)
  // Setup window (ESPHome's provisioning): closed early on a software restart and once the first PIN is set, while
  // the native API has no key (an unadopted controller), see setup()/loop().
  bool hw_reset_{true};
  bool prov_checked_{false};
  std::atomic<bool> close_prov_{false};
  void close_provisioning_(const char *why);
  static void api_task_(void *arg);
  void *api_q_{nullptr}, *api_done_{nullptr}, *api_mutex_{nullptr};
  // results handed back to the main loop
  std::mutex results_lock_;
  std::string last_result_[3];  // ntfy, pushover, telegram
  bool wx_ready_{false};
  float wx_t_{NAN}, wx_h_{NAN}, wx_w_{NAN};
  std::vector<float> fc_min_, fc_t_;
  uint32_t wx_at_{0}, wx_fetched_{0};
  std::atomic<bool> save_pending_{false};

  // stage 2
  Settings2 s2_{};
  ESPPreferenceObject pref2_;
  ESPPreferenceObject jpref_[JOURNAL_SLOTS];
  JEntry journal_[JOURNAL_SLOTS];
  uint32_t journal_dirty_{0};  // bit per slot
  int16_t *hist_{nullptr};     // HIST_SERIES x HIST_LEN, tenths of a degree, INT16_MIN = no reading
  size_t hist_head_{0}, hist_count_{0};
  uint32_t hist_last_{0};
  std::mutex hist_lock_;
#ifdef USE_SENSOR
  sensor::Sensor *pit_{nullptr}, *pit_target_{nullptr};
#endif
  // community averages (Open Pitmaster aggregates.json), compact lines per group
  struct Group { std::string cut, line; };
  std::vector<Group> community_;
  uint32_t community_cooks_{0}, community_at_{0};
  std::string community_updated_;
  std::vector<std::pair<uint32_t, std::string>> share_results_;  // entry id, "shared"/"refused …"
  // Uploads and withdrawals waiting for share_pump_ (bit per journal slot), and its pause (Open Pitmaster's limits).
  uint32_t share_wait_{0}, unshare_wait_{0};
  uint32_t share_sent_at_{0}, share_hold_ms_{0};
  void share_pump_(uint32_t now);
  struct Done { std::string what; int code; std::string body; };
  std::vector<Done> done_;  // finished worker jobs for the main loop (under results_lock_)
  bool network_ready_();
  // stage 3: the AI (standalone_ai.cpp)
  void setup_ai_();
  void loop_ai_(uint32_t now);
  bool ai_ready_() const;
  std::string ai_model_() const;
  std::string ai_context_();
  // Whether the journal's notes go into the AI's context: not for a question from a locked page (the notes are only
  // shown to an unlocked page, and a prompt could ask the AI to repeat them).
  bool ai_ctx_notes_{true}, ai_req_authed_{true}, ai_defer_notes_{true};
  int ai_kind_(const std::string &k) const;
  bool ai_ask_(const std::string &kind, const std::string &system, const std::string &user, const std::string &image_b64,
               std::string &why);
  static bool community_group_ok_(JsonObject g);
  void ai_done_(const std::string &what, int code, const std::string &body);
  std::string ai_advise_();
  std::string ai_json_();  // settings (never the key), what the AI said and its errors
  std::string api_ai_(const std::string &path, JsonDocument &in, int &status);
  AiSettings ai_{};
  ESPPreferenceObject aipref_;
  bool ai_save_{false};
  uint8_t ai_busy_{0};  // bit per kind: advise, plan, label, test
  std::string ai_advice_, ai_plan_, ai_labels_, ai_error_, ai_test_, ai_program_, ai_assign_cut_;
  std::string ai_load_;
  std::string ai_defer_kind_, ai_defer_text_;  // a question from the page, asked in the main loop
  std::string ai_plan_ask_(const std::string &req);
  uint8_t ha_bounces_{0};  // Load as program: "loading", "loaded" or why not
  int ai_assign_probe_{0};
  float ai_assign_lb_{NAN};
  uint32_t ai_last_auto_{0};
  // Home Assistant dropped the controller (standalone_ai.cpp): reconnect Wi-Fi, then restart once.
  void loop_ha_watch_(uint32_t now);
  ESPPreferenceObject ha_pref_;
  uint8_t ha_state_{0};          // persisted: bit0 = Home Assistant has used this controller, bit1 = restarted for an outage
  bool ha_loaded_{false};
  uint32_t ha_lost_at_{0}, ha_bounced_at_{0};
  uint16_t ai_calls_today_{0};
  uint32_t ai_day_{0};
  bool ai_cook_on_();            // a cook underway, or one planned for the next two days
  int8_t fuel_mode_{-1};  // a charcoal log from the device page, applied in the main loop
  float fuel_pct_{NAN};
};

}  // namespace standalone
}  // namespace esphome
