#include "cook_assistant.h"

#include <cmath>
#include <cstdio>
#include <cstring>

#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

namespace esphome {
namespace cook_assistant {

static const char *const TAG = "cook_assistant";

static const size_t PROGRAM_MAX = 1024;
struct ProgramBlob {
  char text[PROGRAM_MAX];
};
struct StateBlob {
  uint8_t running;  // 0 none, 1 running, 2 paused
  uint8_t step;
  uint16_t reserved;
  float step_elapsed_min;
  float pit_c;
  uint32_t saved_at_s;  // uptime at save (for sanity only)
};
struct HistoryBlob {
  cook::CookRecord r[cook::CookHistory::CAPACITY];
};

// ------------------------------------------------------------ entity helpers

void CANumber::setup() {
  this->pref_ = this->make_entity_preference<float>();
  float v;
  if (!this->pref_.load(&v) || std::isnan(v))
    v = this->initial_;
  if (!std::isnan(v)) {
    this->publish_state(v);
    if (this->on_change_)
      this->on_change_(v);
  }
}
void CANumber::control(float value) {
  this->publish_state(value);
  this->pref_.save(&value);
  if (this->on_change_)
    this->on_change_(value);
}

void CASelect::setup() {
  this->pref_ = this->make_entity_preference<uint32_t>();
  uint32_t idx = 0;
  if (!this->restore_ || !this->pref_.load(&idx) || idx >= this->size())
    idx = 0;
  this->publish_state(size_t(idx));
  if (this->on_change_ && this->restore_)
    this->on_change_(idx);
}
void CASelect::control(size_t index) {
  this->publish_state(index);
  uint32_t v = index;
  this->pref_.save(&v);
  if (this->on_change_)
    this->on_change_(index);
}

void CASwitch::setup() {
  auto initial = this->get_initial_state_with_restore_mode();
  bool on = initial.has_value() ? *initial : false;
  this->publish_state(on);
  if (this->on_change_)
    this->on_change_(on);
}
void CASwitch::write_state(bool state) {
  this->publish_state(state);
  if (this->on_change_)
    this->on_change_(state);
}

void CAText::control(const std::string &value) {
  if (this->on_change_)
    this->on_change_(value);
}

// ------------------------------------------------------------ formatting

std::string CookAssistant::fmt_temp_(float c) const {
  char b[16];
  std::snprintf(b, sizeof(b), "%.0f°%s", this->from_c_(c), this->fahrenheit_ ? "F" : "C");
  return b;
}

std::string CookAssistant::fmt_minutes_(float m) const {
  if (std::isnan(m))
    return "--";
  char b[24];
  int mm = int(std::lround(m));
  if (mm >= 60)
    std::snprintf(b, sizeof(b), "%dh %02dm", mm / 60, mm % 60);
  else
    std::snprintf(b, sizeof(b), "%d min", mm);
  return b;
}

double CookAssistant::now_min_() const { return millis() / 60000.0; }

int CookAssistant::minute_of_day_() {
#ifdef USE_TIME
  if (this->time_ != nullptr) {
    auto t = this->time_->now();
    if (t.is_valid())
      return t.hour * 60 + t.minute;
  }
#endif
  return -1;
}

std::vector<std::string> CookAssistant::probe_keys() const {
  std::vector<std::string> k = {"pit"};
  for (auto *p : this->probes_)
    k.push_back(p->key);
  return k;
}

// ------------------------------------------------------------ setup

void CookAssistant::setup() {
  // History
  this->history_pref_ = global_preferences->make_preference<HistoryBlob>(fnv1_hash("cook_history_v1"), true);
  {
    auto *blob = new HistoryBlob();  // NOLINT: 1.9 kB, keep off the stack
    if (this->history_pref_.load(blob))
      this->history_.load(blob->r, cook::CookHistory::CAPACITY);
    delete blob;
  }
  // Program
  this->program_pref_ = global_preferences->make_preference<ProgramBlob>(fnv1_hash("cook_program_v1"), true);
  this->state_pref_ = global_preferences->make_preference<StateBlob>(fnv1_hash("cook_program_state_v1"));
  {
    auto *blob = new ProgramBlob();  // NOLINT
    if (this->program_pref_.load(blob)) {
      blob->text[PROGRAM_MAX - 1] = 0;
      if (blob->text[0] != 0)
        this->load_program(blob->text);
    }
    delete blob;
  }
  this->restore_program_state_();

  for (size_t i = 0; i < this->probes_.size(); i++) {
    auto *p = this->probes_[i];
    if (p->profile != nullptr)
      p->profile->set_on_change([this, p](size_t idx) {
        p->predictor.set_profile(int(idx));
        this->refresh_priors_(p, true);
      });
    if (p->weight != nullptr)
      p->weight->set_on_change([this, p](float w) {
        float kg = this->fahrenheit_ ? w * 0.4536f : w;
        p->predictor.set_weight(kg > 0 ? kg : NAN);
        this->refresh_priors_(p, true);
      });
    if (p->wrapped != nullptr)
      p->wrapped->set_on_change([this, i](bool w) { this->set_wrapped(i, w); });
    this->refresh_priors_(p, true);
  }
  if (this->program_text_ != nullptr)
    this->program_text_->set_on_change([this](const std::string &t) { this->load_program(t); });
  if (this->preset_select_ != nullptr)
    this->preset_select_->set_on_change([this](size_t idx) { this->select_preset(idx); });

  if (this->history_count_ != nullptr)
    this->history_count_->publish_state(this->history_.count());
  if (this->grill_factor_ != nullptr)
    this->grill_factor_->publish_state(this->history_.grill_factor());
  if (this->cook_active_bs_ != nullptr)
    this->cook_active_bs_->publish_state(false);
  this->publish_program_();
}

void CookAssistant::dump_config() {
  ESP_LOGCONFIG(TAG, "Cook assistant: %u food probe(s), %u preset(s), %u past cook(s), unit %s",
                (unsigned) this->probes_.size(), (unsigned) this->presets_.size(), (unsigned) this->history_.count(),
                this->fahrenheit_ ? "°F" : "°C");
}

void CookAssistant::loop() {
  uint32_t now = millis();
  if (now - this->last_second_ >= 1000) {
    this->last_second_ = now;
    this->tick_second_();
  }
  if (this->last_minute_ == 0 || now - this->last_minute_ >= 60000) {
    this->last_minute_ = now | 1;
    this->tick_minute_();
  }
}

// ------------------------------------------------------------ data

float CookAssistant::pit_c_() const {
  if (this->pit_temp_ == nullptr || !this->pit_temp_->has_state())
    return NAN;
  float v = this->pit_temp_->state;
  return std::isnan(v) ? NAN : this->to_c_(v);
}

float CookAssistant::pit_setpoint_c_() const {
  if (this->pit_setpoint_ != nullptr && this->pit_setpoint_->has_state() && !std::isnan(this->pit_setpoint_->state))
    return this->to_c_(this->pit_setpoint_->state);
  return this->runner_.commanded_pit();
}

cook::Environment CookAssistant::environment_() const {
  cook::Environment e;
  auto val = [](sensor::Sensor *s) { return s != nullptr && s->has_state() ? s->state : NAN; };
  float a = val(this->ambient_);
  e.ambient_c = std::isnan(a) ? NAN : this->to_c_(a);
  e.humidity = val(this->humidity_);
  float w = val(this->wind_);
  e.wind_kmh = std::isnan(w) ? NAN : (this->fahrenheit_ ? w * 1.609f : w);
  return e;
}

float CookAssistant::probe_target_c_(FoodProbe *p) const {
  if (p->target_number != nullptr && p->target_number->has_state() && !std::isnan(p->target_number->state))
    return this->to_c_(p->target_number->state);
  if (p->target != nullptr && p->target->has_state() && !std::isnan(p->target->state))
    return this->to_c_(p->target->state);
  return NAN;
}

void CookAssistant::refresh_priors_(FoodProbe *p, bool force) {
  float pit = this->runner_.commanded_pit();
  if (std::isnan(pit))
    pit = this->pit_setpoint_c_();
  if (std::isnan(pit))
    pit = this->pit_c_();
  if (!force && !std::isnan(p->last_priors_pit) && !std::isnan(pit) && std::fabs(pit - p->last_priors_pit) < 3.0f)
    return;
  p->last_priors_pit = pit;
  float kg = NAN;
  if (p->weight != nullptr && p->weight->has_state() && p->weight->state > 0)
    kg = this->fahrenheit_ ? p->weight->state * 0.4536f : p->weight->state;
  auto env = this->environment_();
  p->predictor.set_environment(env);
  auto pri = this->history_.priors(p->predictor.profile(), kg, pit, p->predictor.wrapped(), env);
  p->predictor.set_priors(pri);
  if (p->estimate_info != nullptr) {
    char b[128];
    std::snprintf(b, sizeof(b), "%s, %d similar past cook%s, grill factor %.2f%s",
                  cook::profiles()[p->predictor.profile()].name, pri.similar, pri.similar == 1 ? "" : "s",
                  this->history_.grill_factor(), std::isnan(env.ambient_c) ? "" : ", weather-adjusted");
    p->estimate_info->publish_state(b);
  }
}

void CookAssistant::tick_second_() {
  const double now = this->now_min_();
  const float pit = this->pit_c_();
  cook::RunnerInputs in;
  in.temp_c.push_back(pit);
  in.done.push_back(false);
  in.stall_started.push_back(false);
  in.stall_ended.push_back(false);
  in.minute_of_day = this->minute_of_day_();

  for (auto *p : this->probes_) {
    float t = NAN;
    if (p->temperature != nullptr && p->temperature->has_state() && !std::isnan(p->temperature->state))
      t = this->to_c_(p->temperature->state);
    p->predictor.set_target(this->probe_target_c_(p));
    p->predictor.add_sample(now / 60.0, t, pit, this->pit_setpoint_c_());
    p->stall_started_tick = p->predictor.take_stall_started();
    p->stall_ended_tick = p->predictor.take_stall_ended();
    bool done_ev = p->predictor.take_done();
    in.temp_c.push_back(t);
    in.done.push_back(p->predictor.phase() == cook::Phase::DONE);
    in.stall_started.push_back(p->stall_started_tick);
    in.stall_ended.push_back(p->stall_ended_tick);

    if (p->stall_started_tick) {
      this->notify(p->name + " stall", p->name + " has stalled at " + this->fmt_temp_(t) + ". Wrapping will push through it faster.",
                   0, "stall_" + p->key);
    }
    if (p->stall_ended_tick && p->predictor.phase() != cook::Phase::DONE) {
      this->notify(p->name + " stall over", p->name + " is climbing again (" + this->fmt_temp_(t) + ").", 0,
                   "stall_" + p->key);
    }
    if (done_ev && !p->done_notified) {
      p->done_notified = true;
      this->notify(p->name + " is done", p->name + " reached " + this->fmt_temp_(t) + ".", 1, "done_" + p->key);
    }
    float target = this->probe_target_c_(p);
    if (!std::isnan(t) && !std::isnan(target)) {
      if (!p->approach_notified && t >= target - 3.0f && t < target) {
        p->approach_notified = true;
        this->notify(p->name + " almost done", p->name + " is " + this->fmt_temp_(t) + ", target " + this->fmt_temp_(target) + ".",
                     0, "done_" + p->key);
      } else if (t < target - 6.0f) {
        p->approach_notified = false;
        p->done_notified = false;
      }
    }
    bool suspect = p->predictor.probe_suspect();
    if (suspect && !p->suspect_notified) {
      p->suspect_notified = true;
      this->notify(p->name + " probe check", p->name + " jumped to " + this->fmt_temp_(t) +
                       ", close to the pit temperature. Is the probe still in the meat?",
                   1, "probe_" + p->key);
    } else if (!suspect) {
      p->suspect_notified = false;
    }
    if (p->probe_warning != nullptr)
      p->probe_warning->publish_state(suspect);
    if (p->stall != nullptr)
      p->stall->publish_state(p->predictor.phase() == cook::Phase::STALL);

    cook::CookRecord rec;
    if (p->predictor.take_completed(rec)) {
      this->history_.add(rec);
      this->save_history_();
      ESP_LOGI(TAG, "%s: cook recorded (k=%.3f, stall %.1fh, total %.1fh)", p->name.c_str(), rec.k_pre, rec.stall_h,
               rec.total_h);
      char json[320];
      std::snprintf(json, sizeof(json),
                    "{\"probe\":\"%s\",\"name\":\"%s\",\"profile\":\"%s\",\"weight_kg\":%.2f,\"wrapped\":%s,"
                    "\"pit_c\":%.1f,\"start_c\":%.1f,\"target_c\":%.1f,\"k_pre\":%.4f,\"k_post\":%.4f,"
                    "\"stall_h\":%.2f,\"total_h\":%.2f,\"history_count\":%u}",
                    p->key.c_str(), p->name.c_str(), cook::profiles()[rec.profile].name,
                    std::isnan(rec.weight_kg) ? 0.0f : rec.weight_kg, (rec.flags & 1) ? "true" : "false", rec.pit_c,
                    rec.start_c, rec.target_c, std::isnan(rec.k_pre) ? 0.0f : rec.k_pre,
                    std::isnan(rec.k_post) ? 0.0f : rec.k_post, std::isnan(rec.stall_h) ? 0.0f : rec.stall_h,
                    rec.total_h, (unsigned) this->history_.count());
      std::string js = json;
      for (auto *tr : this->complete_triggers_)
        tr->trigger(js);
      if (this->history_count_ != nullptr)
        this->history_count_->publish_state(this->history_.count());
      if (this->grill_factor_ != nullptr)
        this->grill_factor_->publish_state(this->history_.grill_factor());
    }
  }

  // Program
  if (this->runner_.state() == cook::ProgramRunner::State::RUNNING) {
    // Manual override detection: the reported pit target no longer matches ours.
    float cmd = this->runner_.commanded_pit();
    float rep = this->pit_setpoint_ != nullptr && this->pit_setpoint_->has_state()
                    ? this->to_c_(this->pit_setpoint_->state)
                    : NAN;
    if (!std::isnan(cmd) && !std::isnan(rep) && std::fabs(cmd - rep) > 2.0f &&
        millis() - this->last_set_pit_ms_ > 20000) {
      if (this->override_since_ < 0)
        this->override_since_ = now;
      if (now - this->override_since_ > 0.5) {
        this->runner_.pause("pit target changed outside the program");
        this->notify("Program paused", "The pit target was changed to " + this->fmt_temp_(rep) +
                                           ". Resume the program to go back to " + this->fmt_temp_(cmd) + ".",
                     0, "program");
        this->override_since_ = -1;
        this->save_program_state_();
      }
    } else {
      this->override_since_ = -1;
    }
    auto out = this->runner_.tick(now, in);
    this->apply_outputs_(out);
  }
  if (this->program_status_ != nullptr) {
    std::string d = this->runner_.describe(now, in, this->probe_keys(), this->fahrenheit_);
    if (!this->program_status_->has_state() || this->program_status_->state != d)
      this->program_status_->publish_state(d);
  }
  if (this->program_state_ != nullptr) {
    std::string s = this->runner_.state_name();
    if (!this->program_state_->has_state() || this->program_state_->state != s)
      this->program_state_->publish_state(s);
  }
  this->update_cook_session_();
  this->check_alerts_();
  if (millis() - this->last_state_save_ > 300000) {
    this->last_state_save_ = millis();
    this->save_program_state_();
  }
}

void CookAssistant::tick_minute_() {
  const double now = this->now_min_();
  float sp = this->pit_setpoint_c_();
  bool env_known = this->ambient_ != nullptr || this->humidity_ != nullptr || this->wind_ != nullptr;
  for (auto *p : this->probes_) {
    this->refresh_priors_(p, env_known && p->predictor.phase() <= cook::Phase::WARMING);
    float target = this->probe_target_c_(p);
    // Program probe ids: 0 = pit, 1.. = food probes in config order.
    std::vector<cook::PlanSegment> plan;
    for (size_t i = 0; i < this->probes_.size(); i++)
      if (this->probes_[i] == p)
        plan = this->runner_.plan_for_probe(int(i) + 1, now, target);
    auto pr = p->predictor.predict(plan, sp);
    auto pub = [](sensor::Sensor *s, float v) {
      if (s != nullptr)
        s->publish_state(v);
    };
    pub(p->remaining, pr.valid ? std::round(pr.minutes) : NAN);
    pub(p->remaining_low, pr.valid ? std::round(pr.minutes_low) : NAN);
    pub(p->remaining_high, pr.valid ? std::round(pr.minutes_high) : NAN);
    pub(p->stall_remaining, std::isnan(pr.stall_remaining_min) ? NAN : std::round(pr.stall_remaining_min));
    float rate = p->predictor.rate_c_per_h();
    pub(p->rate, std::isnan(rate) ? NAN : std::round(this->rate_from_c_(rate) * 10.0f) / 10.0f);
    // Whole-cook estimate (works before the probe goes in).
    float pit_for_est = !std::isnan(sp) ? sp : this->pit_c_();
    float est = p->predictor.estimate_total_minutes(4.0f, pit_for_est, plan);
    pub(p->estimated_total, std::isnan(est) ? NAN : std::round(est));
    if (p->phase != nullptr) {
      std::string ph = cook::phase_name(p->predictor.phase());
      if (!pr.valid && pr.reason[0] && p->predictor.phase() != cook::Phase::NO_PROBE)
        ph += std::string(" (") + pr.reason + ")";
      if (!p->phase->has_state() || p->phase->state != ph)
        p->phase->publish_state(ph);
    }
    if (p->finish_time != nullptr) {
      std::string ft = "--";
#ifdef USE_TIME
      if (pr.valid && this->time_ != nullptr) {
        auto t = this->time_->now();
        if (t.is_valid()) {
          time_t ts = t.timestamp + time_t(pr.minutes * 60.0f);
          auto f = ESPTime::from_epoch_local(ts);
          char b[40];
          auto fl = ESPTime::from_epoch_local(t.timestamp + time_t(pr.minutes_low * 60.0f));
          auto fh = ESPTime::from_epoch_local(t.timestamp + time_t(pr.minutes_high * 60.0f));
          std::snprintf(b, sizeof(b), "%02d:%02d (%02d:%02d-%02d:%02d)", f.hour, f.minute, fl.hour, fl.minute, fh.hour,
                        fh.minute);
          ft = b;
        }
      }
#endif
      if (ft == "--" && pr.valid)
        ft = "in " + this->fmt_minutes_(pr.minutes);
      if (!p->finish_time->has_state() || p->finish_time->state != ft)
        p->finish_time->publish_state(ft);
    }
  }
  if (this->cook_elapsed_ != nullptr)
    this->cook_elapsed_->publish_state(this->cook_active_ ? std::round(now - this->cook_start_min_) : NAN);
}

// ------------------------------------------------------------ cook session & alerts

void CookAssistant::update_cook_session_() {
  const double now = this->now_min_();
  float pit = this->pit_c_();
  bool program = this->runner_.state() == cook::ProgramRunner::State::RUNNING;
  if (!this->cook_active_) {
    if ((!std::isnan(pit) && pit >= 65.0f) || program) {
      this->cook_active_ = true;
      this->cook_start_min_ = now;
      this->pit_reached_ = false;
      this->pit_band_notified_ = this->fire_notified_ = this->lid_notified_ = this->link_notified_ = false;
      this->cool_since_min_ = -1;
      ESP_LOGI(TAG, "Cook session started");
      if (this->cook_active_bs_ != nullptr)
        this->cook_active_bs_->publish_state(true);
    }
    return;
  }
  // End: pit below 49 °C (120 °F) for 20 min with no program running.
  if (!program && (std::isnan(pit) || pit < 49.0f)) {
    if (this->cool_since_min_ < 0)
      this->cool_since_min_ = now;
    if (now - this->cool_since_min_ > 20) {
      this->cook_active_ = false;
      ESP_LOGI(TAG, "Cook session ended after %.0f min", now - this->cook_start_min_);
      if (this->cook_active_bs_ != nullptr)
        this->cook_active_bs_->publish_state(false);
    }
  } else {
    this->cool_since_min_ = -1;
  }
}

void CookAssistant::check_alerts_() {
  if (!this->cook_active_)
    return;
  const double now = this->now_min_();
  float pit = this->pit_c_();
  float sp = this->pit_setpoint_c_();
  bool lid_open = this->lid_ != nullptr && this->lid_->has_state() && this->lid_->state;

  // Pit out of band (after it first reached the setpoint).
  if (!std::isnan(pit) && !std::isnan(sp)) {
    if (std::fabs(pit - sp) < 5.0f)
      this->pit_reached_ = true;
    bool out = this->pit_reached_ && !lid_open && std::fabs(pit - sp) > 14.0f;  // 25 °F
    if (out) {
      if (this->pit_off_since_ < 0)
        this->pit_off_since_ = now;
      if (now - this->pit_off_since_ > 10 && !this->pit_band_notified_) {
        this->pit_band_notified_ = true;
        this->notify("Pit temperature off", "Pit is " + this->fmt_temp_(pit) + ", target " + this->fmt_temp_(sp) + ".",
                     1, "pit_band");
      }
    } else {
      this->pit_off_since_ = -1;
      if (std::fabs(pit - sp) < 8.0f)
        this->pit_band_notified_ = false;
    }
    // Fire out: > 28 °C (50 °F) below target and still falling for 15 min.
    bool low = this->pit_reached_ && !lid_open && sp - pit > 28.0f &&
               (std::isnan(this->last_pit_c_) || pit <= this->last_pit_c_ + 0.5f);
    if (low) {
      if (this->fire_low_since_ < 0)
        this->fire_low_since_ = now;
      if (now - this->fire_low_since_ > 15 && !this->fire_notified_) {
        this->fire_notified_ = true;
        this->notify("Fire may be out", "Pit has dropped to " + this->fmt_temp_(pit) + " (target " +
                                            this->fmt_temp_(sp) + "). Check the charcoal hopper.",
                     2, "fire");
      }
    } else if (sp - pit < 14.0f) {
      this->fire_low_since_ = -1;
      this->fire_notified_ = false;
    }
  }
  if (!std::isnan(pit))
    this->last_pit_c_ = pit;

  // Lid open for more than 2 minutes.
  if (lid_open) {
    if (this->lid_open_since_ < 0)
      this->lid_open_since_ = now;
    if (now - this->lid_open_since_ > 2 && !this->lid_notified_) {
      this->lid_notified_ = true;
      this->notify("Lid open", "The grill lid has been open for more than 2 minutes.", 1, "lid");
    }
  } else {
    this->lid_open_since_ = -1;
    this->lid_notified_ = false;
  }

  // Link to the grill lost during a cook.
  bool link_down = this->link_ != nullptr && this->link_->has_state() && !this->link_->state;
  if (link_down) {
    if (this->link_lost_since_ < 0)
      this->link_lost_since_ = now;
    if (now - this->link_lost_since_ > 2 && !this->link_notified_) {
      this->link_notified_ = true;
      this->notify("Grill connection lost", "No data from the grill for 2 minutes during a cook.", 2, "link");
    }
  } else {
    if (this->link_notified_)
      this->notify("Grill connection restored", "Receiving data from the grill again.", 0, "link");
    this->link_lost_since_ = -1;
    this->link_notified_ = false;
  }
}

void CookAssistant::notify(const std::string &title, const std::string &message, int priority, const std::string &tag) {
  ESP_LOGI(TAG, "Notify [%d] %s: %s", priority, title.c_str(), message.c_str());
  if (this->alerts_switch_ != nullptr && !this->alerts_switch_->state && priority < 2)
    return;  // alerts muted (critical ones still go out)
  for (auto *t : this->notify_triggers_)
    t->trigger(title, message, priority, tag);
}

// ------------------------------------------------------------ programs

void CookAssistant::set_pit_(float c) {
  if (std::isnan(c))
    return;
  this->last_set_pit_ms_ = millis();
  this->last_commanded_c_ = c;
  float v = std::round(this->from_c_(c));
  for (auto *t : this->set_pit_triggers_)
    t->trigger(v);
  for (auto *p : this->probes_)
    this->refresh_priors_(p, true);
}

void CookAssistant::apply_outputs_(const cook::RunnerOutputs &o) {
  if (o.set_pit)
    this->set_pit_(o.pit_c);
  for (const auto &m : o.notifications)
    this->notify(this->runner_.program().name.empty() ? "Cook program" : this->runner_.program().name, m, 1, "program");
  if (o.step_changed && !o.finished) {
    char b[48];
    std::snprintf(b, sizeof(b), "Step %u of %u", unsigned(this->runner_.step() + 1),
                  unsigned(this->runner_.program().steps.size()));
    std::string msg = b;
    float cp = this->runner_.commanded_pit();
    if (!std::isnan(cp))
      msg += ": pit to " + this->fmt_temp_(cp);
    this->notify("Program step", msg, 0, "program");
  }
  if (o.finished)
    this->notify("Program finished", std::isnan(this->runner_.commanded_pit())
                                         ? std::string("The cook program has finished.")
                                         : "The cook program has finished; holding " +
                                               this->fmt_temp_(this->runner_.commanded_pit()) + ".",
                 1, "program");
  if (o.shutdown)
    this->notify("Shutdown", "Cook program requested shutdown. Let the fire burn out with the lid closed.", 1,
                 "program");
  if (o.step_changed || o.finished)
    this->save_program_state_();
}

bool CookAssistant::load_program(const std::string &text) {
  cook::Program prog;
  std::string err;
  if (!cook::parse_program(text, this->probe_keys(), this->fahrenheit_, prog, err)) {
    ESP_LOGW(TAG, "Program error: %s", err.c_str());
    if (this->program_error_ != nullptr)
      this->program_error_->publish_state(err);
    return false;
  }
  if (this->runner_.state() == cook::ProgramRunner::State::RUNNING ||
      this->runner_.state() == cook::ProgramRunner::State::PAUSED)
    this->runner_.stop();
  this->runner_.load(prog);
  this->program_source_ = text;
  if (this->program_error_ != nullptr)
    this->program_error_->publish_state("");
  auto *blob = new ProgramBlob();  // NOLINT
  std::strncpy(blob->text, text.c_str(), PROGRAM_MAX - 1);
  this->program_pref_.save(blob);
  delete blob;
  ESP_LOGI(TAG, "Loaded program '%s' with %u steps", prog.name.c_str(), (unsigned) prog.steps.size());
  this->publish_program_();
  this->save_program_state_();
  return true;
}

void CookAssistant::publish_program_() {
  if (this->program_text_ != nullptr) {
    std::string t = this->program_source_;
    if (t.size() > 255)
      t = t.substr(0, 252) + "...";
    this->program_text_->publish_state(t);
  }
}

void CookAssistant::select_preset(size_t index) {
  if (index >= this->presets_.size())
    return;  // "Custom" or out of range
  this->load_program(this->presets_[index].second);
}

void CookAssistant::start_program() {
  if (!this->runner_.loaded()) {
    this->notify("No program", "Load a program or pick a preset first.", 0, "program");
    return;
  }
  auto o = this->runner_.start(this->now_min_());
  this->apply_outputs_(o);
  this->save_program_state_();
}
void CookAssistant::pause_program() {
  this->runner_.pause("paused by user");
  this->save_program_state_();
}
void CookAssistant::resume_program() {
  auto o = this->runner_.resume(this->now_min_());
  this->apply_outputs_(o);
  this->save_program_state_();
}
void CookAssistant::skip_step() {
  auto o = this->runner_.skip(this->now_min_());
  this->apply_outputs_(o);
}
void CookAssistant::stop_program() {
  this->runner_.stop();
  this->save_program_state_();
}

void CookAssistant::save_program_state_() {
  StateBlob s{};
  auto st = this->runner_.state();
  s.running = st == cook::ProgramRunner::State::RUNNING ? 1 : st == cook::ProgramRunner::State::PAUSED ? 2 : 0;
  s.step = uint8_t(this->runner_.step());
  s.step_elapsed_min = float(this->runner_.step_elapsed_min(this->now_min_()));
  s.pit_c = this->runner_.commanded_pit();
  s.saved_at_s = millis() / 1000;
  this->state_pref_.save(&s);
}

void CookAssistant::restore_program_state_() {
  StateBlob s{};
  if (!this->state_pref_.load(&s) || s.running == 0 || !this->runner_.loaded())
    return;
  // Resume as paused: a reboot mid-cook should not silently change anything;
  // the user (or HA automation) resumes. The setpoint stays on the grill.
  this->runner_.restore(s.step, s.step_elapsed_min, this->now_min_(), false);
  ESP_LOGW(TAG, "Restored program at step %u (paused after restart)", s.step + 1);
  this->set_timeout(30000, [this]() {
    this->notify("Controller restarted", "The cook program was restored at step " +
                                             std::to_string(this->runner_.step() + 1) + " and is paused. Resume it to continue.",
                 1, "program");
  });
}

void CookAssistant::set_wrapped(size_t probe, bool wrapped) {
  if (probe >= this->probes_.size())
    return;
  auto *p = this->probes_[probe];
  p->predictor.set_wrapped(wrapped);
  this->refresh_priors_(p, true);
}

void CookAssistant::save_history_() {
  auto *blob = new HistoryBlob();  // NOLINT
  this->history_.save(blob->r, cook::CookHistory::CAPACITY);
  this->history_pref_.save(blob);
  delete blob;
  global_preferences->sync();
}

void CookAssistant::clear_history() {
  this->history_.clear();
  this->save_history_();
  if (this->history_count_ != nullptr)
    this->history_count_->publish_state(0);
  if (this->grill_factor_ != nullptr)
    this->grill_factor_->publish_state(1.0f);
  for (auto *p : this->probes_)
    this->refresh_priors_(p, true);
}

static void json_num(std::string &s, const char *key, float v, const char *fmt = "%.2f") {
  char b[48];
  if (std::isnan(v))
    std::snprintf(b, sizeof(b), "\"%s\":null", key);
  else {
    char f[16];
    std::snprintf(f, sizeof(f), "\"%%s\":%s", fmt);
    std::snprintf(b, sizeof(b), f, key, v);
  }
  s += b;
}

std::string CookAssistant::state_json() {
  std::string s = "{";
  s += std::string("\"unit\":\"") + (this->fahrenheit_ ? "F" : "C") + "\",";
  json_num(s, "pit", std::isnan(this->pit_c_()) ? NAN : this->from_c_(this->pit_c_()), "%.0f");
  s += ",";
  float sp = this->pit_setpoint_c_();
  json_num(s, "pit_target", std::isnan(sp) ? NAN : this->from_c_(sp), "%.0f");
  s += ",\"cook_minutes\":" + std::to_string(this->cook_active_ ? int(this->now_min_() - this->cook_start_min_) : 0);
  s += ",\"program\":\"" + std::string(this->runner_.state_name()) + "\",\"probes\":[";
  for (size_t i = 0; i < this->probes_.size(); i++) {
    auto *p = this->probes_[i];
    auto &pr = p->predictor;
    if (i)
      s += ",";
    s += "{\"key\":\"" + p->key + "\",\"name\":\"" + p->name + "\",\"profile\":\"" +
         cook::profiles()[pr.profile()].name + "\",\"phase\":\"" + cook::phase_name(pr.phase()) + "\",";
    float t = pr.current_temp();
    json_num(s, "temp", std::isnan(t) ? NAN : this->from_c_(t), "%.0f");
    s += ",";
    float tg = this->probe_target_c_(p);
    json_num(s, "target", std::isnan(tg) ? NAN : this->from_c_(tg), "%.0f");
    s += ",";
    json_num(s, "rate_per_h", std::isnan(pr.rate_c_per_h()) ? NAN : this->rate_from_c_(pr.rate_c_per_h()), "%.1f");
    s += ",";
    json_num(s, "weight", p->weight != nullptr && p->weight->has_state() ? p->weight->state : NAN, "%.1f");
    s += std::string(",\"wrapped\":") + (pr.wrapped() ? "true" : "false") + ",";
    json_num(s, "minutes_remaining", p->remaining != nullptr && p->remaining->has_state() ? p->remaining->state : NAN, "%.0f");
    s += ",";
    json_num(s, "minutes_low", p->remaining_low != nullptr && p->remaining_low->has_state() ? p->remaining_low->state : NAN, "%.0f");
    s += ",";
    json_num(s, "minutes_high", p->remaining_high != nullptr && p->remaining_high->has_state() ? p->remaining_high->state : NAN, "%.0f");
    s += ",";
    json_num(s, "stall_elapsed_h", pr.stall_elapsed_h());
    s += ",\"similar_cooks\":" + std::to_string(pr.priors().similar) + "}";
  }
  s += "]}";
  return s;
}

std::string CookAssistant::history_json() {
  std::string s = "[";
  bool first = true;
  for (const auto &r : this->history_.records()) {
    char b[256];
    std::snprintf(b, sizeof(b),
                  "%s{\"profile\":\"%s\",\"weight_kg\":%.2f,\"wrapped\":%s,\"pit_c\":%.0f,\"target_c\":%.0f,"
                  "\"stall_h\":%.2f,\"total_h\":%.2f}",
                  first ? "" : ",", r.profile < cook::profile_count() ? cook::profiles()[r.profile].name : "?",
                  std::isnan(r.weight_kg) ? 0.0f : r.weight_kg, (r.flags & 1) ? "true" : "false", r.pit_c, r.target_c,
                  std::isnan(r.stall_h) ? 0.0f : r.stall_h, r.total_h);
    s += b;
    first = false;
  }
  s += "]";
  return s;
}

}  // namespace cook_assistant
}  // namespace esphome
