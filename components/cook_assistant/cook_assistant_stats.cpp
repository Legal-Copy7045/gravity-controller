// Lid-open cost and pit stability, per cook.
//
// Lid: when the lid opens, the soonest food's predicted finish is noted; once the lid is closed and the pit is back
// near its target (or after 30 minutes), the new prediction says what the opening cost: "Lid open 3 min: pit back
// after 9 min, about +12 min on Food 1". The predictor already follows the real pit, so later estimates include it.
//
// Stability: each minute of the cook once the pit has first reached its target, leaving out lid openings and the
// 10 minutes after each one: how often the pit was within 10 °F (5.6 °C) of target, how far off it was on average,
// and the biggest overshoot and dip. Shown live ("Pit stability") and kept until the next cook starts.

#include "cook_assistant.h"

#include "esphome/core/log.h"

namespace esphome {
namespace cook_assistant {

static const char *const TAG = "cook_assistant.stats";

std::string CookAssistant::fmt_temp_delta_(float dc) const {
  const float d = this->fahrenheit_ ? dc * 9.0f / 5.0f : dc;
  char b[16];
  std::snprintf(b, sizeof(b), "%.0f°%s", std::fabs(d), this->fahrenheit_ ? "F" : "C");
  return b;
}

float CookAssistant::earliest_finish_min_() {
  float best = NAN;
  const double now = this->now_min_();
  for (auto *p : this->probes_) {
    if (p->remaining == nullptr || !p->remaining->has_state() || std::isnan(p->remaining->state))
      continue;
    const float f = float(now) + p->remaining->state;
    if (std::isnan(best) || f < best)
      best = f;
  }
  return best;
}

void CookAssistant::reset_cook_stats_() {
  this->lid_count_ = 0;
  this->lid_cost_total_ = 0;
  this->lid_measuring_ = false;
  this->lid_closed_at_ = -1;
  this->st_n_ = this->st_in_ = 0;
  this->st_abs_sum_ = this->st_max_over_ = this->st_max_under_ = 0;
  this->st_last_min_ = -1;
  this->last_lid_.clear();
  if (this->last_lid_ts_ != nullptr)
    this->last_lid_ts_->publish_state("");
}

void CookAssistant::track_lid_(bool lid_open, double now, float pit, float sp) {
  if (!this->cook_active_)
    return;
  if (lid_open) {
    if (this->lid_opened_at_ < 0) {
      this->lid_opened_at_ = now;
      this->lid_finish_before_ = this->earliest_finish_min_();
      // Each food's predicted finish now (absolute minutes), to compare food by food afterwards.
      this->lid_before_.assign(this->probes_.size(), NAN);
      for (size_t i = 0; i < this->probes_.size(); i++) {
        auto *p = this->probes_[i];
        if (p->remaining != nullptr && p->remaining->has_state() && !std::isnan(p->remaining->state) &&
            !(p->pulled != nullptr && p->pulled->state))
          this->lid_before_[i] = float(now) + p->remaining->state;
      }
      this->lid_measuring_ = false;
    }
    return;
  }
  if (this->lid_opened_at_ >= 0) {  // just closed
    this->lid_open_min_ = float(now - this->lid_opened_at_);
    this->lid_opened_at_ = -1;
    this->lid_closed_at_ = now;
    if (this->lid_open_min_ >= 0.25f) {  // a real opening, not a bounce of the switch
      this->lid_count_++;
      this->lid_measuring_ = true;
    }
    return;
  }
  if (!this->lid_measuring_)
    return;
  const float back_min = float(now - this->lid_closed_at_);
  const bool back = !std::isnan(pit) && !std::isnan(sp) && std::fabs(pit - sp) < 3.0f;
  if (!back && back_min < 30.0f)
    return;
  this->lid_measuring_ = false;
  // The cost: how much later the foods that had an estimate before and still have one now (not pulled, not added
  // during the opening) are predicted to finish; the largest of those delays.
  float cost = NAN;
  for (size_t i = 0; i < this->probes_.size() && i < this->lid_before_.size(); i++) {
    auto *p = this->probes_[i];
    if (std::isnan(this->lid_before_[i]) || p->remaining == nullptr || !p->remaining->has_state() ||
        std::isnan(p->remaining->state) || (p->pulled != nullptr && p->pulled->state))
      continue;
    const float d = std::max(0.0f, float(now) + p->remaining->state - this->lid_before_[i]);
    if (d > 6 * 60.0f)
      continue;  // not a lid's doing (a new cook in that slot, a target changed): left out
    cost = std::isnan(cost) ? d : std::max(cost, d);
  }
  if (!std::isnan(cost))
    this->lid_cost_total_ += cost;
  char b[160];
  std::snprintf(b, sizeof(b), "Open %s; pit back %s", this->fmt_minutes_(std::max(1.0f, this->lid_open_min_)).c_str(),
                back ? ("after " + this->fmt_minutes_(std::max(1.0f, back_min))).c_str() : "slowly (over 30 min)");
  std::string txt = b;
  if (!std::isnan(cost) && cost >= 1.0f)
    txt += "; about +" + this->fmt_minutes_(cost) + " on the finish";
  this->last_lid_ = txt;
  if (this->last_lid_ts_ != nullptr)
    this->last_lid_ts_->publish_state(txt);
  ESP_LOGI(TAG, "Lid opening: %s", txt.c_str());
  if (!std::isnan(cost) && cost >= 5.0f)
    this->notify("That lid opening cost about " + this->fmt_minutes_(cost),
                 "The lid was open " + this->fmt_minutes_(std::max(1.0f, this->lid_open_min_)) + " and the pit took " +
                     this->fmt_minutes_(std::max(1.0f, back_min)) + " to get back, so the food should be done about " +
                     this->fmt_minutes_(cost) + " later than before.",
                 0, "lid_cost");
}

void CookAssistant::track_stability_(bool lid_open, double now, float pit, float sp) {
  if (!this->cook_active_ || !this->pit_reached_ || std::isnan(pit) || std::isnan(sp))
    return;
  if (now - this->st_last_min_ < this->w_(1.0f))
    return;
  this->st_last_min_ = now;
  const bool grace = lid_open || (this->lid_closed_at_ >= 0 && now - this->lid_closed_at_ < this->w_(10));
  if (grace)
    return;
  const float d = pit - sp;
  this->st_n_++;
  if (std::fabs(d) <= 5.56f)
    this->st_in_++;
  this->st_abs_sum_ += std::fabs(d);
  this->st_max_over_ = std::max(this->st_max_over_, d);
  this->st_max_under_ = std::max(this->st_max_under_, -d);
  if (this->st_n_ % 5 == 0 || this->st_n_ == 1) {
    if (this->stability_pct_ != nullptr)
      this->stability_pct_->publish_state(std::round(100.0f * this->st_in_ / this->st_n_));
    if (this->stability_ts_ != nullptr)
      this->stability_ts_->publish_state(this->stability_text_());
  }
}

std::string CookAssistant::stability_text_() const {
  if (this->st_n_ < 5)
    return "";
  char b[64];
  std::snprintf(b, sizeof(b), "Within %s of target %u%% of the time",
                this->fahrenheit_ ? "10°F" : "5°C", unsigned(std::lround(100.0f * this->st_in_ / this->st_n_)));
  std::string s = b;
  s += " · average " + this->fmt_temp_delta_(this->st_abs_sum_ / this->st_n_) + " off";
  if (this->st_max_over_ >= 2.8f)
    s += " · peak +" + this->fmt_temp_delta_(this->st_max_over_);
  if (this->st_max_under_ >= 2.8f)
    s += " · dip −" + this->fmt_temp_delta_(this->st_max_under_);
  if (this->lid_count_ > 0) {
    s += " · lid opened " + std::to_string(this->lid_count_) + (this->lid_count_ == 1 ? " time" : " times");
    if (this->lid_cost_total_ >= 1.0f)
      s += " (+" + this->fmt_minutes_(this->lid_cost_total_) + ")";
  }
  return s;
}

}  // namespace cook_assistant
}  // namespace esphome
