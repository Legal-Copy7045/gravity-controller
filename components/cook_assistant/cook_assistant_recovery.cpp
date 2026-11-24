// Power-cut recovery: pick a cook up again after the power was cut, to the controller, the grill, or both.
//
// During a cook the controller writes a small record every 2 minutes (and when something it holds changes): the cook
// is on, the grill is on, the pit target, the clock. After a cut:
//  * the controller restarted (its own power, or both): at boot it reads the record and, if the cook was live and
//    the controller was off for at most an hour, it restores the cook session and the program and recovers;
//  * only the grill lost power (the controller stayed up): its link drops during a cook while the grill was on, and
//    comes back within an hour.
// Recovering: wait for the grill's link; if the grill was on before the cut and is off now, turn it back on (the one
// place the controller does that without a person's second press: only here, and only twice); then send the pit
// target again (a rebooted grill forgets it; food targets re-sync on their own) and resume the program, counting the
// time the controller was off towards a timed step. Then one notification says what happened.
// A grill turned off with its own button or from a page keeps its link, so it's never mistaken for a cut: the
// controller sees it go off while connected and won't turn it back on. "Resume after a power cut" turns it all off.

#include "cook_assistant.h"

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#ifdef USE_ESP32
#include <esp_system.h>
#endif

namespace esphome {
namespace cook_assistant {

static const char *const TAG = "cook_assistant.recovery";

static const uint32_t SAVE_EVERY_MS = 120000;     // the record during a cook
static const float MAX_OUTAGE_MIN = 60.0f;        // longer than this: the fire is probably out; alert instead
static const uint32_t LINK_WAIT_MS = 10 * 60000;  // reconnecting to the grill after a restart
static const uint32_t SETTLE_MS = 5000;           // after the link is back, before judging the grill's state
static const uint32_t POWER_WAIT_MS = 25000;      // after a power-on press, before trying again
static const uint32_t TARGETS_AFTER_MS = 8000;    // after the grill is on, before sending targets
static const uint32_t OVERRIDE_HOLD_MS = 120000;  // the rebooted grill's own setpoint isn't a manual change

uint32_t CookAssistant::epoch_now_() {
#ifdef USE_TIME
  if (this->time_ != nullptr) {
    auto t = this->time_->now();
    if (t.is_valid())
      return uint32_t(t.timestamp);
  }
#endif
  return 0;
}

void CookAssistant::recovery_setup_() {
  this->recovery_pref_ = global_preferences->make_preference<RecoveryBlob>(fnv1_hash("cook_recovery_v1"));
  RecoveryBlob b{};
  if (this->recovery_pref_.load(&b) && b.version == 1) {
    this->rec_boot_ = b;
    this->rec_last_ = b;
    this->rec_boot_pending_ = b.cook_active != 0;
  }
}

void CookAssistant::recovery_save_(bool force) {
  RecoveryBlob b{};
  b.cook_active = this->cook_active_ ? 1 : 0;
  b.grill_on = this->grill_was_on_ ? 1 : 0;
  const uint32_t ep = this->epoch_now_();
  b.heartbeat = ep;
  b.cook_min = this->cook_active_ ? float(this->now_min_() - this->cook_start_min_) : 0;
  b.cook_start = ep != 0 && this->cook_active_ ? ep - uint32_t(b.cook_min * 60.0f) : 0;
  const float sp = this->pit_setpoint_c_();
  b.pit_sp_c = !std::isnan(sp) ? sp : this->rec_last_.pit_sp_c;
  // Idle: write once when the cook ends, then nothing (no flash wear while the grill sits).
  if (!b.cook_active && !this->rec_last_.cook_active && !force)
    return;
  const bool changed = b.cook_active != this->rec_last_.cook_active || b.grill_on != this->rec_last_.grill_on ||
                       (std::isnan(b.pit_sp_c) != std::isnan(this->rec_last_.pit_sp_c)) ||
                       (!std::isnan(b.pit_sp_c) && std::fabs(b.pit_sp_c - this->rec_last_.pit_sp_c) > 0.5f);
  if (!changed && !force && millis() - this->rec_saved_ms_ < SAVE_EVERY_MS)
    return;
  this->rec_saved_ms_ = millis();
  this->rec_last_ = b;
  // The program's place, written with the record, so a timed step resumes from the same moment.
  const auto rs = this->runner_.state();
  if (rs == cook::ProgramRunner::State::RUNNING || rs == cook::ProgramRunner::State::PAUSED ||
      this->runner_.keep_probe() >= 0)
    this->save_program_state_(false);
  this->recovery_pref_.save(&b);
  if (changed)
    global_preferences->sync();  // a cut right after a change shouldn't lose it
}

// The controller's own reset was a loss of power (a cut or a dip), not a restart, an update or a crash.
static bool reset_was_power_loss() {
#ifdef USE_ESP32
  const auto r = esp_reset_reason();
  return r == ESP_RST_POWERON || r == ESP_RST_BROWNOUT;
#else
  return true;  // (the host test build: a restart stands in for a power cut)
#endif
}

static std::string reset_reason_text() {
#ifdef USE_ESP32
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:
      return "the power was cut";
    case ESP_RST_BROWNOUT:
      return "the power dipped";
    case ESP_RST_PANIC:
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:
      return "it crashed";
    case ESP_RST_SW:
      return "it restarted";
    default:
      break;
  }
#endif
  return "it restarted";
}

void CookAssistant::begin_recovery_(bool controller, float outage_min, bool grill_was_on, float pit_c) {
  this->rec_ = Rec::WAIT_LINK;
  // Turning the grill back on needs a measured outage within the limit, and (for a restart of the controller) a
  // restart caused by a loss of power. Then, at the grill, evidence that it lost power too (see Rec::CHECK).
  this->rec_may_power_on_ = !std::isnan(outage_min) && outage_min <= MAX_OUTAGE_MIN && (!controller || reset_was_power_loss());
  this->rec_controller_ = controller;
  this->rec_grill_was_on_ = grill_was_on;
  this->rec_turned_on_ = this->rec_pit_changed_ = false;
  this->rec_food_sent_ = 0;
  this->rec_power_tries_ = 0;
  this->rec_outage_min_ = outage_min;
  this->rec_began_min_ = this->now_min_();
  this->rec_pit_c_ = pit_c;
  this->rec_pre_sp_c_ = this->rec_last_.pit_sp_c;
  this->rec_sp_at_link_ = NAN;
  this->rec_since_ms_ = this->rec_step_ms_ = millis();
  this->override_hold_until_ = millis() + OVERRIDE_HOLD_MS;
  ESP_LOGW(TAG, "Recovering the cook after %s (outage %.0f min, grill was %s)",
           controller ? "a controller restart" : "the grill's link dropped", outage_min, grill_was_on ? "on" : "off");
}

static std::string fmt_outage(float min) {
  if (std::isnan(min))
    return "for a while";
  if (min < 1.5f)
    return "for about a minute";
  return "for about " + std::to_string(int(std::lround(min))) + " min";
}

void CookAssistant::finish_recovery_(int priority, const std::string &problem) {
  const auto st = this->runner_.state();
  const bool prog = st == cook::ProgramRunner::State::RUNNING || st == cook::ProgramRunner::State::PAUSED;
  const bool controller = this->rec_controller_;
  this->rec_ = Rec::NONE;
  if (this->prog_restored_)
    this->restore_turbo_(false);  // left paused: no Turbo
  this->prog_restored_ = false;  // a program left paused stays paused; never resumed later by a stale record
  if (!problem.empty())
    this->grill_was_on_ = false;  // no automatic power-on for the rest of this cook until the grill is seen on again
  // A Wi-Fi/Bluetooth dropout with the grill fine (on, same target): nothing happened; the link note covers it, and
  // a target changed by hand right after it is a manual change as usual.
  if (!controller && !this->rec_turned_on_ && !this->rec_pit_changed_ && this->rec_food_sent_ == 0 && problem.empty()) {
    this->override_hold_until_ = millis();
    return;
  }
  this->override_hold_until_ = millis() + OVERRIDE_HOLD_MS;
  std::string title, msg;
  if (controller) {
    const char *what = reset_was_power_loss() ? "Power cut" : "Controller restarted";
    title = std::string(what) + (problem.empty() ? ": cook resumed" : ": cook needs you");
    msg = "The controller was off " + fmt_outage(this->rec_outage_min_) + " (" + reset_reason_text() + ").";
  } else {
    title = problem.empty() ? "The grill lost power: cook resumed" : "The grill lost power";
    msg = "The grill dropped off " + fmt_outage(this->rec_outage_min_) + ".";
  }
  if (this->rec_turned_on_)
    msg += " It came back off, so it was turned back on.";
  if (this->rec_pit_changed_ && !std::isnan(this->rec_pit_c_))
    msg += " Pit set back to " + this->fmt_temp_(this->rec_pit_c_) + ".";
  if (this->rec_food_sent_ > 0)
    msg += this->rec_food_sent_ == 1 ? " The food target was sent again." : " The food targets were sent again.";
  if (prog && problem.empty()) {
    msg += st == cook::ProgramRunner::State::RUNNING
               ? " The program carries on at step " + std::to_string(this->runner_.step() + 1) + " of " +
                     std::to_string(this->runner_.program().steps.size()) + "."
               : " The program is paused (it was paused before).";
  }
  const float pit = this->pit_c_();
  if (!std::isnan(pit) && problem.empty())
    msg += " Pit is " + this->fmt_temp_(pit) + " now.";
  if (!problem.empty())
    msg += " " + problem;
  this->notify(title, msg, priority, "power_cut");
}

void CookAssistant::recovery_tick_() {
  const uint32_t now = millis();
  const bool link = this->link_up_();

  // ---- after a restart: decide once the clock is known (Home Assistant can take a while to come back after a power
  // cut: up to 10 min). Without a clock the outage can't be measured: the cook is picked up, the grill never turned on.
  if (this->rec_boot_pending_) {
    const uint32_t ep = this->epoch_now_();
    if (ep == 0 && now < 600000)
      return;
    this->rec_boot_pending_ = false;
    const RecoveryBlob &b = this->rec_boot_;
    const float outage = ep != 0 && b.heartbeat != 0 && ep >= b.heartbeat ? (ep - b.heartbeat) / 60.0f : NAN;
    const bool fresh = std::isnan(outage) || outage <= MAX_OUTAGE_MIN + 3.0f;  // (saved every 2 min)
    if (fresh && this->resume_enabled_()) {
      // The same cook: its start, and the program counting the time the controller was off.
      this->cook_active_ = true;
      float in_cook = ep != 0 && b.cook_start != 0 ? (ep - b.cook_start) / 60.0f
                                                   : b.cook_min + (std::isnan(outage) ? 0.0f : outage);
      this->cook_start_min_ = this->now_min_() - std::max(0.0f, in_cook);
      this->cool_since_min_ = -1;
      if (this->cook_active_bs_ != nullptr)
        this->cook_active_bs_->publish_state(true);
      this->grill_was_on_ = b.grill_on != 0;
      const float pit = this->prog_restored_ && this->prog_restored_running_ ? this->runner_.commanded_pit() : b.pit_sp_c;
      this->begin_recovery_(true, outage, b.grill_on != 0,
                            std::isnan(pit) ? b.pit_sp_c : pit);
      if (this->keep_restored_ && this->runner_.keep_probe() >= 0)
        // (Not titled "...restarted": that title gets a Resume button, and there's nothing to resume.)
        this->notify("Still keeping the food warm",
                     "The controller restarted and goes on keeping the food at its temperature (step " +
                         std::to_string(this->runner_.step() + 1) + ").",
                     1, "program");
      this->keep_restored_ = false;
    } else {
      // The cook isn't resumed: a keep-warm program restored with it ends too.
      if (this->keep_restored_ && this->runner_.keep_probe() >= 0) {
        this->runner_.stop();
        this->save_program_state_();
      }
      this->keep_restored_ = false;
      std::string why = !this->resume_enabled_() ? "\"Resume after a power cut\" is off"
                                                 : "it was off " + fmt_outage(outage) + ", so the fire may be out";
      this->notify("Controller restarted during a cook",
                   "The controller was off (" + reset_reason_text() + ") and didn't resume the cook: " + why +
                       ". Check the grill and the food." +
                       (this->prog_restored_ ? " The program is paused at step " +
                                                    std::to_string(this->runner_.step() + 1) + "; resume it to continue."
                                              : ""),
                   2, "power_cut");
      if (this->prog_restored_)
        this->restore_turbo_(false);
      this->prog_restored_ = false;
    }
  }

  // ---- live: the grill's link during a cook
  if (this->rec_ == Rec::NONE) {
    if (!link) {
      if (this->link_down_ms_ == 0 && this->cook_active_)
        this->link_down_ms_ = now;
    } else {
      if (this->link_down_ms_ != 0) {
        const float down = (now - this->link_down_ms_) / 60000.0f;
        this->link_down_ms_ = 0;
        this->resync_until_ = now + 600000;
        if (this->cook_active_ && this->grill_was_on_ && down <= MAX_OUTAGE_MIN && this->resume_enabled_()) {
          const auto st = this->runner_.state();
          const float pit = st == cook::ProgramRunner::State::RUNNING ? this->runner_.commanded_pit()
                                                                      : this->rec_last_.pit_sp_c;
          this->begin_recovery_(false, down, true, pit);
        }
      }
      // Track whether the grill is on while connected (turned off with its button: it stays connected, so
      // it isn't a power cut and won't be turned back on).
      if (this->rec_ == Rec::NONE && this->grill_on_ != nullptr && this->grill_on_->has_state()) {
        // Just switched on (by hand, or from a page): it may report its own default target for a moment; that isn't
        // a manual change of the program's target, which goes to it again (the program's retry).
        if (this->grill_on_->state && !this->grill_was_on_ && this->cook_active_) {
          this->override_hold_until_ = now + OVERRIDE_HOLD_MS;
          this->resync_until_ = now + 600000;
        }
        this->grill_was_on_ = this->grill_on_->state;
      }
    }
    if (this->rec_ == Rec::NONE) {
      this->recovery_save_();
      return;
    }
  }

  // ---- recovering
  switch (this->rec_) {
    case Rec::WAIT_LINK:
      if (link) {
        this->resync_until_ = now + 600000;
        this->rec_ = Rec::CHECK;
        this->rec_step_ms_ = now;
        this->rec_sp_at_link_ = this->pit_setpoint_c_();  // from the first status after reconnecting
      } else if (now - this->rec_since_ms_ > LINK_WAIT_MS) {
        this->finish_recovery_(2, "The controller couldn't reconnect to the grill within 10 minutes: check the grill "
                                  "and the food.");
      }
      break;
    case Rec::CHECK:
      if (!link) {
        this->rec_ = Rec::WAIT_LINK;
        break;
      }
      if (now - this->rec_step_ms_ < SETTLE_MS)
        break;
      {
        // Evidence that the grill itself lost power: it came back with a different pit target than before (its
        // default), or with no target on a probe that had one. A grill turned off with its button keeps its targets.
        bool reset = !std::isnan(this->rec_pre_sp_c_) &&
                     (std::isnan(this->rec_sp_at_link_) || std::fabs(this->rec_sp_at_link_ - this->rec_pre_sp_c_) > 1.0f);
        for (auto *p : this->probes_) {
          if (p->active >= p->sources.size())
            continue;
          auto &src = p->sources[p->active];
          if (src.sync != nullptr && src.target != nullptr && this->sync_owner_(p, src) &&
              !std::isnan(this->slot_in_source_(p, src)) && !(src.target->has_state() && !std::isnan(src.target->state)))
            reset = true;
        }
        this->rec_grill_reset_ = reset;
        // Only the link dropped (the grill kept its power): it's on and reports the same targets as before.
        if (!this->rec_controller_ && this->grill_reports_on_() && !reset) {
          this->finish_recovery_(1, "");
          break;
        }
      }
      if (this->grill_reports_on_() || this->grill_on_ == nullptr) {
        this->rec_ = Rec::TARGETS;
        this->rec_step_ms_ = now;
      } else if (this->rec_grill_was_on_ && !(this->rec_may_power_on_ && this->rec_grill_reset_)) {
        // Off, but no proof it was a power cut (or the outage couldn't be measured, or was too long): never turned on.
        this->finish_recovery_(2, !this->rec_may_power_on_
                                      ? "The grill is off. It wasn't turned back on: the controller couldn't tell how "
                                        "long the power was off. Check the fire and the food, then turn it on if all's well."
                                      : "The grill is off and its settings look unchanged (turned off at the grill?). "
                                        "It wasn't turned back on: turn it on if you want to carry on.");
        break;
      } else if (this->rec_grill_was_on_) {
        if (this->rec_power_tries_ >= 2) {
          this->finish_recovery_(2, "The grill is still off: it didn't turn back on. Turn it on at the grill.");
          break;
        }
        this->rec_power_tries_++;
        ESP_LOGW(TAG, "The grill was on before the cut and is off now: turning it back on (try %u)",
                 unsigned(this->rec_power_tries_));
        for (auto *t : this->power_on_triggers_)
          t->trigger();
        this->rec_ = Rec::POWERING;
        this->rec_step_ms_ = now;
      } else {
        this->finish_recovery_(1, "The grill is off, as it was before (it isn't turned on automatically).");
      }
      break;
    case Rec::POWERING:
      if (this->grill_reports_on_()) {
        this->rec_turned_on_ = true;
        this->rec_ = Rec::TARGETS;
        this->rec_step_ms_ = now;
      } else if (now - this->rec_step_ms_ > POWER_WAIT_MS) {
        this->rec_ = Rec::CHECK;
        this->rec_step_ms_ = now - SETTLE_MS;
      }
      break;
    case Rec::TARGETS: {
      if (now - this->rec_step_ms_ < TARGETS_AFTER_MS)
        break;
      // The program: resumed where it was (it was restored paused), counting the time the controller was off.
      if (this->prog_restored_) {
        this->prog_restored_ = false;
        if (this->prog_restored_running_) {
          // The outage, plus the time spent here getting the grill back (link, power-on, settling): the
          // program was paused through it, and a timed step should still end when it would have.
          const float off = (std::isnan(this->rec_outage_min_) ? 0.0f : this->rec_outage_min_) +
                            float(std::max(0.0, this->now_min_() - this->rec_began_min_));
          this->runner_.restore(this->prog_restored_step_, this->prog_restored_elapsed_ + off, this->now_min_(), true);
          this->save_program_state_();
        }
        this->restore_turbo_(this->prog_restored_running_);  // a sear resumes with its Turbo; paused, it's off
      }
      const auto st = this->runner_.state();
      float want = st == cook::ProgramRunner::State::RUNNING ? this->runner_.commanded_pit() : this->rec_pit_c_;
      const float rep = this->pit_setpoint_c_();
      if (!std::isnan(want) && (std::isnan(rep) || std::fabs(rep - want) > 1.0f)) {
        this->rec_pit_c_ = want;
        this->rec_pit_changed_ = true;
        this->set_pit_(want);
      }
      // Food targets: a rebooted grill reports none for its probes, which the normal sync leaves alone (it can't tell
      // that from a link with nothing to say): send each slot's target to the grill probe it reads.
      for (auto *p : this->probes_) {
        if (p->active >= p->sources.size())
          continue;
        auto &src = p->sources[p->active];
        if (src.sync == nullptr || src.target == nullptr || !this->sync_owner_(p, src))
          continue;
        const float v = this->slot_in_source_(p, src);
        const float st = src.target->has_state() ? src.target->state : NAN;
        if (!std::isnan(v) && (std::isnan(st) || std::round(st) != v)) {
          this->push_target_(p, src, v);
          this->rec_food_sent_++;
        }
      }
      this->finish_recovery_(1, "");
      break;
    }
    case Rec::NONE:
      break;
  }
}

}  // namespace cook_assistant
}  // namespace esphome
