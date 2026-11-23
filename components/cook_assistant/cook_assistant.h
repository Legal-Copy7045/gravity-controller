#pragma once
// ESPHome glue for the cook assistant: per-probe cook-time prediction with
// learning from past cooks, stall detection, cook programs, alerts.
// Transport-agnostic: it reads ordinary ESPHome sensors and sets the pit
// target through an automation (`on_set_pit`), so it works with the stock
// controller bridge today and the replacement controller later.

#include <algorithm>
#include <cmath>
#include <functional>
#include <string>
#include <vector>

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/preferences.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/number/number.h"
#include "esphome/components/select/select.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/button/button.h"
#include "esphome/components/text/text.h"
#ifdef USE_TIME
#include "esphome/components/time/real_time_clock.h"
#endif

#include "fuel.h"
#include "history.h"
#include "predictor.h"
#include "program.h"

namespace esphome {
namespace cook_assistant {

class CookAssistant;

// ---- small entity helpers that call back into the assistant ----

// How much history before an estimate stops being "Experimental".
static const int ETA_TRUSTED_COOKS = 3;     // similar past cooks for finish-time predictions
static const int PULL_TRUSTED_RESTS = 2;    // measured rests for the pull-at temperature
static const float FUEL_TRUSTED_KG = 3.0f;  // charcoal burned in calibrated stretches (about one cook)

class CANumber : public number::Number, public Component {
 public:
  void setup() override;
  void set_on_change(std::function<void(float)> &&f) { this->on_change_ = std::move(f); }
  void set_initial(float v) { this->initial_ = v; }

 protected:
  void control(float value) override;
  std::function<void(float)> on_change_;
  ESPPreferenceObject pref_;
  float initial_{NAN};
};

class CASelect : public select::Select, public Component {
 public:
  void setup() override;
  void set_on_change(std::function<void(size_t)> &&f) { this->on_change_ = std::move(f); }
  void set_restore(bool r) { this->restore_ = r; }
  void set_initial_index(size_t i) { this->initial_ = i; }

 protected:
  void control(size_t index) override;
  std::function<void(size_t)> on_change_;
  ESPPreferenceObject pref_;
  bool restore_{true};
  size_t initial_{0};
};

class CASwitch : public switch_::Switch, public Component {
 public:
  void setup() override;
  void set_on_change(std::function<void(bool)> &&f) { this->on_change_ = std::move(f); }

 protected:
  void write_state(bool state) override;
  std::function<void(bool)> on_change_;
};

class CAButton : public button::Button {
 public:
  void set_on_press(std::function<void()> &&f) { this->on_press_ = std::move(f); }

 protected:
  void press_action() override {
    if (this->on_press_)
      this->on_press_();
  }
  std::function<void()> on_press_;
};

class CAText : public text::Text, public Component {
 public:
  void set_on_change(std::function<void(const std::string &)> &&f) { this->on_change_ = std::move(f); }

 protected:
  void control(const std::string &value) override;
  std::function<void(const std::string &)> on_change_;
};

// ---- per probe ----

/// One place a probe temperature can come from (a grill probe, a Bluetooth thermometer, a Home Assistant entity).
struct ProbeSource {
  std::string name;
  sensor::Sensor *temperature{nullptr};
  bool fahrenheit{true};               // unit of `temperature` and `target`
  sensor::Sensor *target{nullptr};     // the source's own target (e.g. the grill's probe target), optional
  number::Number *sync{nullptr};       // set this when the slot's target changes (e.g. the grill's probe target)
};

struct FoodProbe {
  std::string key;   // "food1"
  std::string name;  // "Brisket"
  std::vector<ProbeSource> sources;  // choose with `source`
  CASelect *source{nullptr};
  size_t active{0};
  CANumber *target_number{nullptr};  // the slot's target (synced to the source's own target when it has one)
  float last_source_target{NAN};     // to notice target changes made on the source (grill panel)
  float pushed_target{NAN};          // a target sent to the source, not yet reported back (source units)
  uint32_t push_ms{0};
  CASelect *profile{nullptr};
  CANumber *weight{nullptr};
  CASwitch *wrapped{nullptr};

  sensor::Sensor *remaining{nullptr};
  sensor::Sensor *remaining_low{nullptr};
  sensor::Sensor *remaining_high{nullptr};
  sensor::Sensor *estimated_total{nullptr};
  sensor::Sensor *rate{nullptr};
  sensor::Sensor *reading{nullptr};    // the active source's temperature
  uint32_t reading_ms{0};
  sensor::Sensor *stall_remaining{nullptr};
  text_sensor::TextSensor *finish_time{nullptr};
  // The cook's plan: the predicted food temperature curve, taken at the first sound prediction of each cook (so the
  // graph can show actual vs plan). "1;<start epoch>;<step min>;<F|C>;t0,t1,...", whole degrees.
  text_sensor::TextSensor *plan{nullptr};
  bool plan_taken{false};
  text_sensor::TextSensor *phase{nullptr};
  text_sensor::TextSensor *estimate_info{nullptr};
  binary_sensor::BinarySensor *stall{nullptr};
  binary_sensor::BinarySensor *probe_warning{nullptr};
  CASwitch *pulled{nullptr};            // the meat is off the grill, resting
  sensor::Sensor *pull_at{nullptr};     // recommended pull temperature
  sensor::Sensor *rest_ready{nullptr};  // minutes until it cools to the slice temperature
  uint32_t last_record_seq{0};
  bool pull_notified{false};
  bool rest_notified{false};

  cook::Predictor predictor;
  bool approach_notified{false};
  bool done_notified{false};
  bool suspect_notified{false};
  bool stall_started_tick{false};
  bool stall_ended_tick{false};
  float last_priors_pit{NAN};
  float last_target_c{NAN};
};

class NotifyTrigger;
class SetPitTrigger;
class CookCompleteTrigger;

class CookAssistant : public Component {
 public:
  // configuration
  void set_fahrenheit(bool f) { this->fahrenheit_ = f; }
  bool is_fahrenheit() const { return this->fahrenheit_; }
  void set_pit_temperature(sensor::Sensor *s) { this->pit_temp_ = s; }
  void set_pit_setpoint(sensor::Sensor *s) { this->pit_setpoint_ = s; }
  void set_lid(binary_sensor::BinarySensor *b) { this->lid_ = b; }
  void set_link(binary_sensor::BinarySensor *b) { this->link_ = b; }
  void set_fan(binary_sensor::BinarySensor *b) { this->fan_ = b; }
  // fuel gauge entities
  void set_fuel_level_sensor(sensor::Sensor *s) { this->fuel_level_ = s; }
  void set_fuel_left_sensor(sensor::Sensor *s) { this->fuel_left_ = s; }
  void set_fuel_hours_sensor(sensor::Sensor *s) { this->fuel_hours_ = s; }
  void set_fuel_rate_sensor(sensor::Sensor *s) { this->fuel_rate_ = s; }
  void set_fuel_basis_text_sensor(text_sensor::TextSensor *s) { this->fuel_basis_ = s; }
  void set_fuel_empty_text_sensor(text_sensor::TextSensor *t) { this->fuel_empty_ = t; }
  void set_fuel_type_select(CASelect *s) { this->fuel_type_ = s; }
  void set_hopper_capacity_kg(float kg) { this->fuel_.set_capacity_kg(kg); }
  void set_slice_number(CANumber *n) { this->slice_ = n; }
  /// Outdoor conditions (e.g. from the HA weather entity). Temperature in the configured unit, wind in km/h (or mph if °F).
  void set_ambient_temperature(sensor::Sensor *s) { this->ambient_ = s; }
  void set_ambient_humidity(sensor::Sensor *s) { this->humidity_ = s; }
  void set_wind_speed(sensor::Sensor *s) { this->wind_ = s; }
  void set_ambient_fahrenheit(bool f) { this->ambient_fahrenheit_ = f; }
  void set_wind_to_kmh(float k) { this->wind_to_kmh_ = k; }
#ifdef USE_TIME
  void set_time(time::RealTimeClock *t) { this->time_ = t; }
#endif
  void add_probe(FoodProbe *p) { this->probes_.push_back(p); }
  void add_preset(const std::string &name, const std::string &program) { this->presets_.push_back({name, program}); }

  // entities
  void set_cook_active_binary_sensor(binary_sensor::BinarySensor *b) { this->cook_active_bs_ = b; }
  void set_cook_elapsed_sensor(sensor::Sensor *s) { this->cook_elapsed_ = s; }
  void set_history_count_sensor(sensor::Sensor *s) { this->history_count_ = s; }
  void set_grill_factor_sensor(sensor::Sensor *s) { this->grill_factor_ = s; }
  void set_program_status_text_sensor(text_sensor::TextSensor *t) { this->program_status_ = t; }
  void set_program_state_text_sensor(text_sensor::TextSensor *t) { this->program_state_ = t; }
  void set_program_error_text_sensor(text_sensor::TextSensor *t) { this->program_error_ = t; }
  void set_program_text(CAText *t) { this->program_text_ = t; }
  void set_preset_select(CASelect *s) { this->preset_select_ = s; }
  void set_alerts_switch(CASwitch *s) { this->alerts_switch_ = s; }

  // triggers
  void add_notify_trigger(NotifyTrigger *t) { this->notify_triggers_.push_back(t); }
  void add_set_pit_trigger(SetPitTrigger *t) { this->set_pit_triggers_.push_back(t); }
  void add_cook_complete_trigger(CookCompleteTrigger *t) { this->complete_triggers_.push_back(t); }

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  // ---- API (buttons, HA actions, lambdas) ----
  /// Load a program from text. Returns false and publishes the error if invalid.
  bool load_program(const std::string &text, bool persist = true);
  bool cook_active() const { return this->cook_active_; }
  /// A program from elsewhere (the AI): parse it and move any pit temperature into the grill's range. Returns false
  /// (with why) if it can't be read; otherwise `fixed` is the program in this controller's syntax and `note` says
  /// what was changed ("" if nothing).
  bool fit_program(const std::string &text, std::string &fixed, std::string &note, std::string &why);
  /// The grill's pit range, in this controller's unit, for prompts: "200-700°F".
  std::string pit_range_text() const { return this->fmt_temp_(this->pit_min_c_) + " to " + this->fmt_temp_(this->pit_max_c_); }
  /// The loaded program as this controller parsed it, in its own syntax ("" = none), so Home Assistant can check
  /// what the controller actually runs (the "Program (as parsed)" text sensor).
  std::string parsed_program() const;
  /// The range an AI-written program may use: the grill's, capped at the "AI max pit" number.
  std::string ai_pit_range_text() const { return this->fmt_temp_(this->pit_min_c_) + " to " + this->fmt_temp_(this->ai_max_c_()); }
  /// The highest pit an AI-written program may ask for (fit_program brings hotter steps down to it, with a note).
  void set_ai_max_pit_c(float c) { if (std::isfinite(c)) this->ai_max_pit_c_ = c; }
  /// Report the outcome of an on_set_pit write (call from the on_set_pit automation).
  void pit_write_result(bool ok);
  void set_pit_range(float min_c, float max_c) {
    this->pit_min_c_ = min_c;
    this->pit_max_c_ = max_c;
  }
  void start_program();
  void pause_program();
  void resume_program();
  void skip_step();
  void stop_program();
  void select_preset(size_t index);
  void clear_history();
  /// Record a manual note that the user wrapped/unwrapped a probe's food.
  void set_wrapped(size_t probe, bool wrapped);
  /// Send a notification through on_notify (title, message, priority 0-2, tag).
  void notify(const std::string &title, const std::string &message, int priority, const std::string &tag);
  /// JSON with the live state of every probe: used by the HA AI advisor.
  std::string state_json();
  /// JSON with the cook history (for HA / AI context).
  std::string history_json();

  // ---- fuel gauge (levels in percent of a full hopper) ----
  void fuel_level(float percent);       // looked in: no fuel added since the last entry
  void fuel_refilled(float percent);    // topped up; it's now at `percent`
  void fuel_added(float percent);       // added this much (fraction of a full hopper)
  void fuel_end(float percent);         // cook over: this much left
  // ---- forecast from Home Assistant: minutes from now, outdoor temperature (ambient unit) ----
  void set_forecast(const std::vector<float> &minutes, const std::vector<float> &temps);
  // ---- rest coach ----
  void set_pulled(size_t probe, bool pulled);

  std::vector<std::string> probe_keys() const;
  const std::vector<FoodProbe *> &probes() const { return this->probes_; }
  const std::vector<std::pair<std::string, std::string>> &presets() const { return this->presets_; }

 protected:
  float to_c_(float v) const { return this->fahrenheit_ ? (v - 32.0f) * 5.0f / 9.0f : v; }
  float from_c_(float c) const { return this->fahrenheit_ ? c * 9.0f / 5.0f + 32.0f : c; }
  float rate_from_c_(float r) const { return this->fahrenheit_ ? r * 9.0f / 5.0f : r; }
  std::string fmt_temp_(float c) const;
  void take_plan_(FoodProbe *p, const std::vector<cook::PlanSegment> &plan, float sp, const cook::Prediction &pr);
  std::string fmt_minutes_(float m) const;
  double now_min_() const;
  int minute_of_day_();
  void tick_second_();
  void tick_minute_();
  void apply_outputs_(const cook::RunnerOutputs &o);
  void set_pit_(float c);
  void refresh_priors_(FoodProbe *p, bool force);
  float probe_target_c_(FoodProbe *p) const;
  float pit_c_() const;
  float pit_setpoint_c_() const;
  cook::Environment environment_() const;
  void publish_program_();
  void save_program_state_(bool sync = true);
  void restore_program_state_();
  void save_history_();
  void update_cook_session_();
  void check_alerts_();

  bool fahrenheit_{true};
  sensor::Sensor *pit_temp_{nullptr};
  sensor::Sensor *pit_setpoint_{nullptr};
  binary_sensor::BinarySensor *lid_{nullptr};
  binary_sensor::BinarySensor *link_{nullptr};
  sensor::Sensor *ambient_{nullptr};
  sensor::Sensor *humidity_{nullptr};
  sensor::Sensor *wind_{nullptr};
  bool ambient_fahrenheit_{true};
  float wind_to_kmh_{1.609344f};
  binary_sensor::BinarySensor *fan_{nullptr};
  sensor::Sensor *fuel_level_{nullptr};
  sensor::Sensor *fuel_left_{nullptr};
  sensor::Sensor *fuel_hours_{nullptr};
  sensor::Sensor *fuel_rate_{nullptr};
  text_sensor::TextSensor *fuel_basis_{nullptr};
  bool fuel_learned_() const { return this->fuel_.k_weight(this->fuel_.fuel()) >= FUEL_TRUSTED_KG; }
  text_sensor::TextSensor *fuel_empty_{nullptr};
  CASelect *fuel_type_{nullptr};
  CANumber *slice_{nullptr};
  cook::FuelGauge fuel_;
  std::vector<uint8_t> fan_hist_;  // fan on/off, one sample a minute (last 10)
  bool fuel_low_notified_{false};
  bool fuel_short_notified_{false};
  void save_fuel_();
  void select_source_(FoodProbe *p, size_t idx);
  void sync_target_(FoodProbe *p, float value);
  float slice_c_() const;
  ESPPreferenceObject fuel_pref_;
  void tick_fuel_(bool minute = false);
  bool sync_owner_(const FoodProbe *p, const ProbeSource &src) const;
  float slot_in_source_(const FoodProbe *p, const ProbeSource &src) const;
  void push_target_(FoodProbe *p, const ProbeSource &src, float v);
  void sync_tick_(FoodProbe *p, const ProbeSource &src);
#ifdef USE_TIME
  time::RealTimeClock *time_{nullptr};
#endif
  std::vector<FoodProbe *> probes_;
  std::vector<std::pair<std::string, std::string>> presets_;

  binary_sensor::BinarySensor *cook_active_bs_{nullptr};
  sensor::Sensor *cook_elapsed_{nullptr};
  sensor::Sensor *history_count_{nullptr};
  sensor::Sensor *grill_factor_{nullptr};
  text_sensor::TextSensor *program_status_{nullptr};
  text_sensor::TextSensor *program_state_{nullptr};
  text_sensor::TextSensor *program_error_{nullptr};
  CAText *program_text_{nullptr};
  CASelect *preset_select_{nullptr};
  CASwitch *alerts_switch_{nullptr};

  std::vector<NotifyTrigger *> notify_triggers_;
  std::vector<SetPitTrigger *> set_pit_triggers_;
  std::vector<CookCompleteTrigger *> complete_triggers_;

  cook::CookHistory history_;
  cook::ProgramRunner runner_;
  std::string program_source_;

  uint32_t last_second_{0};
  uint32_t last_minute_{0};
  uint32_t last_state_save_{0};

  // cook session
  bool cook_active_{false};
  double cook_start_min_{0};
  double cool_since_min_{-1};
  bool pit_reached_{false};
  double pit_off_since_{-1};
  double fire_low_since_{-1};
  double lid_open_since_{-1};
  double link_lost_since_{-1};
  bool pit_band_notified_{false};
  bool fire_notified_{false};
  bool fire_dying_notified_{false};
  bool lid_notified_{false};
  bool link_notified_{false};
  float last_pit_c_{NAN};
  double override_since_{-1};
  float last_commanded_c_{NAN};
  uint32_t last_set_pit_ms_{0};
  float rep_at_write_c_{NAN};
  bool pit_write_failed_{false};
  int write_retries_{0};
  float alert_sp_c_{NAN};
  std::vector<float> pit_hist_;
  double pit_hist_last_min_{-1e9};
  float pit_min_c_{93.333f};   // 200 °F: the stock controller's minimum
  float pit_max_c_{371.111f};  // 700 °F
  float ai_max_pit_c_{204.444f};  // 400 °F: AI-written programs (the "AI max pit" number)
  float ai_max_c_() const { return std::max(this->pit_min_c_, std::min(this->pit_max_c_, this->ai_max_pit_c_)); }
  ESPPreferenceObject state_pref_;
};

class NotifyTrigger : public Trigger<std::string, std::string, int, std::string> {
 public:
  explicit NotifyTrigger(CookAssistant *parent) { parent->add_notify_trigger(this); }
};
class SetPitTrigger : public Trigger<float> {
 public:
  explicit SetPitTrigger(CookAssistant *parent) { parent->add_set_pit_trigger(this); }
};
class CookCompleteTrigger : public Trigger<std::string> {
 public:
  explicit CookCompleteTrigger(CookAssistant *parent) { parent->add_cook_complete_trigger(this); }
};

}  // namespace cook_assistant
}  // namespace esphome
