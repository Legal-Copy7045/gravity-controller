#include "predictor.h"

#include <algorithm>
#include <cstring>

namespace cook {

static const Profile PROFILES[] = {
    // name            stalls onset  stall_h k_prior
    {"Auto", true, 65.0f, 2.5f, 0.15f},
    {"Pork shoulder", true, 66.0f, 3.0f, 0.12f},
    {"Brisket", true, 66.0f, 4.0f, 0.10f},
    {"Ribs", true, 68.0f, 1.0f, 0.30f},
    {"Beef roast", false, 70.0f, 0.5f, 0.20f},
    {"Poultry", false, 70.0f, 0.3f, 0.35f},
    {"Sausage", false, 70.0f, 0.2f, 0.60f},
    {"Fish", false, 70.0f, 0.0f, 0.60f},
};

const Profile *profiles() { return PROFILES; }
int profile_count() { return sizeof(PROFILES) / sizeof(PROFILES[0]); }
int profile_index(const char *name) {
  for (int i = 0; i < profile_count(); i++)
    if (strcmp(PROFILES[i].name, name) == 0)
      return i;
  return -1;
}

const char *phase_name(Phase p) {
  switch (p) {
    case Phase::NO_PROBE:
      return "No probe";
    case Phase::WAITING:
      return "Waiting";
    case Phase::WARMING:
      return "Warming";
    case Phase::STALL:
      return "Stall";
    case Phase::FINISHING:
      return "Finishing";
    case Phase::DONE:
      return "Done";
  }
  return "?";
}

void Predictor::set_profile(int index) {
  if (index < 0 || index >= profile_count())
    index = 0;
  profile_ = index;
}

void Predictor::reset() {
  hist_.clear();
  bucket_start_h_ = -1;
  bucket_food_sum_ = bucket_pit_sum_ = 0;
  bucket_food_n_ = bucket_pit_n_ = 0;
  minutes_ = 0;
  phase_ = Phase::NO_PROBE;
  rate_ = NAN;
  last_food_ = NAN;
  start_food_ = NAN;
  below_min_ = above_min_ = 0;
  stall_start_min_ = -1;
  stalled_once_ = false;
  suspect_ = false;
  for (int i = 0; i < 2; i++)
    sxy_[i] = sxx_[i] = 0;
  stall_end_min_ = -1;
  pit_sum_ = 0;
  pit_n_ = 0;
  wrapped_in_stall_ = false;
  completed_pending_ = false;
  completed_taken_ = false;
}

void Predictor::set_wrapped(bool w) {
  if (w && !wrapped_ && phase_ == Phase::STALL)
    wrapped_in_stall_ = true;
  wrapped_ = w;
}

void Predictor::add_sample(double now_h, float food_c, float pit_c) {
  if (std::isnan(food_c)) {
    // Probe unplugged: a gap of more than a few minutes resets the cook.
    if (phase_ != Phase::NO_PROBE && bucket_start_h_ >= 0 && now_h - bucket_start_h_ > 5.0 / 60.0) {
      reset();
    }
    if (hist_.empty())
      phase_ = Phase::NO_PROBE;
    return;
  }
  if (bucket_start_h_ < 0)
    bucket_start_h_ = now_h;
  bucket_food_sum_ += food_c;
  bucket_food_n_++;
  if (!std::isnan(pit_c)) {
    bucket_pit_sum_ += pit_c;
    bucket_pit_n_++;
  }
  // Close every complete minute bucket (handles gaps by repeating the value).
  while (now_h - bucket_start_h_ >= 1.0 / 60.0) {
    float food = float(bucket_food_sum_ / bucket_food_n_);
    float pit = bucket_pit_n_ ? float(bucket_pit_sum_ / bucket_pit_n_) : NAN;
    process_minute_(food, pit);
    bucket_start_h_ += 1.0 / 60.0;
    if (now_h - bucket_start_h_ >= 1.0 / 60.0)
      continue;  // gap: reuse the same averages
    bucket_food_sum_ = bucket_pit_sum_ = 0;
    bucket_food_n_ = bucket_pit_n_ = 0;
  }
}

void Predictor::process_minute_(float food, float pit) {
  // Probe sanity: a jump of > 8 °C in a minute towards the pit temperature
  // while the food was below 90 °C usually means it slipped out of the meat.
  if (!hist_.empty()) {
    float prev = hist_.back().food;
    if (food - prev > 8.0f && !std::isnan(pit) && std::fabs(pit - food) < 25.0f && prev < 90.0f)
      suspect_ = true;
    else if (std::fabs(food - prev) < 1.0f && !std::isnan(pit) && pit - food > 25.0f)
      suspect_ = false;
  }
  if (hist_.size() >= HIST_MAX)
    hist_.erase(hist_.begin());
  hist_.push_back({food, pit});
  minutes_ += 1;
  if (!std::isnan(pit) && phase_ != Phase::WAITING && phase_ != Phase::NO_PROBE && phase_ != Phase::DONE) {
    pit_sum_ += pit;
    pit_n_++;
  }
  last_food_ = food;
  if (std::isnan(start_food_))
    start_food_ = food;
  update_rate_();
  update_fit_();
  update_phase_();
}

void Predictor::update_rate_() {
  int n = std::min<int>(rate_window_min, hist_.size());
  if (n < 5) {
    rate_ = NAN;
    return;
  }
  // Least-squares slope over the last n minutes, °C per hour.
  double sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (int i = 0; i < n; i++) {
    double x = i / 60.0;
    double y = hist_[hist_.size() - n + i].food;
    sx += x;
    sy += y;
    sxx += x * x;
    sxy += x * y;
  }
  double den = n * sxx - sx * sx;
  rate_ = den > 0 ? float((n * sxy - sx * sy) / den) : NAN;
}

float Predictor::pit_average_(int minutes) const {
  double s = 0;
  int n = 0;
  for (int i = int(hist_.size()) - 1; i >= 0 && n < minutes; i--) {
    if (!std::isnan(hist_[i].pit)) {
      s += hist_[i].pit;
      n++;
    }
  }
  return n ? float(s / n) : NAN;
}

void Predictor::update_fit_() {
  // Use a 10-minute slope against the average driving temperature difference.
  const int W = 10;
  if (hist_.size() < size_t(W) || phase_ == Phase::STALL || phase_ == Phase::DONE)
    return;
  double sx = 0, sy = 0, sxx = 0, sxy = 0, dsum = 0, pit_min = 1e9, pit_max = -1e9;
  int np = 0;
  for (int i = 0; i < W; i++) {
    const auto &s = hist_[hist_.size() - W + i];
    double x = i / 60.0;
    sx += x;
    sy += s.food;
    sxx += x * x;
    sxy += x * s.food;
    if (!std::isnan(s.pit)) {
      dsum += s.pit - s.food;
      np++;
      pit_min = std::min<double>(pit_min, s.pit);
      pit_max = std::max<double>(pit_max, s.pit);
    }
  }
  if (np < W / 2)
    return;
  // Skip unsettled periods (lid open, pit far from steady).
  if (pit_max - pit_min > 20.0)
    return;
  double den = W * sxx - sx * sx;
  double slope = (W * sxy - sx * sy) / den;
  double d = dsum / np;
  if (d < 10.0)
    return;
  // The early part of a cook (surface heating before the core responds) and the
  // evaporative onset just below the stall band both under-read k; skip them.
  if (minutes_ < 30)
    return;
  if (!stalled_once_ && last_food_ > priors_.stall_onset_c - 8.0f && profiles()[profile_].stalls)
    return;
  int idx = stalled_once_ ? 1 : 0;
  const double forget = std::pow(0.5, 1.0 / 60.0);  // one-hour half-life per minute
  sxy_[idx] = sxy_[idx] * forget + slope * d;
  sxx_[idx] = sxx_[idx] * forget + d * d;
}

float Predictor::k_data(bool post) const {
  int idx = post ? 1 : 0;
  // Need roughly 45 minutes of usable data at a 50 °C difference.
  if (sxx_[idx] < 45.0 * 50.0 * 50.0 * 0.5)
    return NAN;
  return float(sxy_[idx] / sxx_[idx]);
}

float Predictor::k_estimate_(bool post) const {
  // Prior worth ~30 minutes of observations at a 60 °C difference, more when
  // several similar past cooks agree.
  const double w0 = 30.0 * 60.0 * 60.0 * 0.5 * (1.0 + std::min(4.0f, priors_.confidence));
  double prior = priors_.k;
  if (post) {
    double pre = k_estimate_(false);
    prior = pre * priors_.k_post_ratio * (wrapped_ ? 1.2 : 1.0);
  }
  int idx = post ? 1 : 0;
  double k = (sxy_[idx] + w0 * prior) / (sxx_[idx] + w0);
  return float(std::max(0.02, std::min(2.0, k)));
}

float Predictor::stall_elapsed_h() const {
  if (phase_ != Phase::STALL || stall_start_min_ < 0)
    return 0;
  return float((minutes_ - stall_start_min_) / 60.0);
}

float Predictor::stall_duration_prior_h(float pit_c) const {
  const Profile &p = profiles()[profile_];
  float pit = std::isnan(pit_c) ? priors_.pit_c : std::max(80.0f, pit_c);
  float d = priors_.stall_h * std::pow(priors_.pit_c / pit, 1.5f);
  if (!p.stalls)
    return d;
  // If this cook heats slower than the priors expected, it is probably bigger
  // or wetter than assumed: stall longer (and vice versa).
  float kd = k_data(false);
  if (!std::isnan(kd) && kd > 0)
    d *= std::sqrt(std::max(0.4f, std::min(2.5f, priors_.k / kd)));
  if (wrapped_)
    d *= 0.6f;
  return std::max(0.0f, std::min(10.0f, d));
}

float Predictor::stall_left_h_(float stall_scale) const {
  float elapsed = stall_elapsed_h();
  float pred = stall_duration_prior_h(pit_average_(30)) * stall_scale;
  if (wrapped_in_stall_)
    pred = std::min(pred, elapsed + 0.75f * stall_scale);  // wrapping usually breaks the stall within ~45 min
  // Overdue stalls: assume we are near the end, but not instantly.
  return std::max(pred - elapsed, std::max(0.25f, 0.2f * elapsed) * stall_scale);
}

void Predictor::update_phase_() {
  const Profile &p = profiles()[profile_];
  float t = last_food_;
  if (phase_ == Phase::NO_PROBE)
    phase_ = Phase::WAITING;
  if (!std::isnan(target_c_) && t >= target_c_) {
    if (phase_ != Phase::DONE) {
      if (phase_ == Phase::STALL) {
        ev_stall_end_ = true;
        stall_end_min_ = minutes_;
      }
      bool was_cooking = phase_ != Phase::WAITING;
      phase_ = Phase::DONE;
      ev_done_ = true;
      if (was_cooking && !completed_taken_) {
        CookRecord r;
        r.profile = uint8_t(profile_);
        r.flags = (wrapped_ ? 1 : 0) | (stalled_once_ ? 2 : 0);
        r.weight_kg = weight_kg_;
        r.pit_c = pit_n_ ? float(pit_sum_ / pit_n_) : NAN;
        r.start_c = start_food_;
        r.target_c = target_c_;
        r.k_pre = k_data(false);
        r.k_post = k_data(true);
        r.stall_h = stalled_once_ && stall_end_min_ > stall_start_min_
                        ? float((stall_end_min_ - stall_start_min_) / 60.0)
                        : (p.stalls ? 0.0f : NAN);
        r.total_h = float(cook_minutes_() / 60.0);
        r.stall_onset_c = stall_onset_temp_;
        completed_ = r;
        completed_pending_ = true;
      }
    }
    return;
  }
  if (phase_ == Phase::DONE) {
    // Fell back below target (e.g. new target set): resume.
    phase_ = stalled_once_ ? Phase::FINISHING : Phase::WARMING;
  }
  if (phase_ == Phase::WAITING) {
    float pit = pit_average_(5);
    // A probe is "in a cook" once the pit is meaningfully hotter than the food.
    if (!std::isnan(pit) && pit - t > 20.0f && hist_.size() >= 5) {
      phase_ = Phase::WARMING;
      cook_start_min_ = minutes_;
      start_food_ = t;
    }
    return;
  }
  if (std::isnan(rate_))
    return;
  if (phase_ == Phase::WARMING) {
    bool in_band = t >= stall_band_low && t <= stall_band_high;
    bool rose = !std::isnan(start_food_) && t - start_food_ >= min_rise_before_stall;
    if (in_band && rose && rate_ < stall_enter_rate && p.stalls) {
      below_min_ += 1;
    } else {
      below_min_ = 0;
    }
    if (below_min_ >= stall_enter_min && !stalled_once_) {
      phase_ = Phase::STALL;
      stall_start_min_ = minutes_ - stall_enter_min;
      stall_onset_temp_ = hist_.size() > size_t(stall_enter_min) ? hist_[hist_.size() - 1 - size_t(stall_enter_min)].food : t;
      stalled_once_ = true;
      above_min_ = 0;
      ev_stall_start_ = true;
      if (wrapped_)
        wrapped_in_stall_ = true;
    }
    return;
  }
  if (phase_ == Phase::STALL) {
    if (rate_ > stall_exit_rate || t > stall_band_high) {
      above_min_ += 1;
    } else {
      above_min_ = 0;
    }
    if (above_min_ >= stall_exit_min || t > stall_band_high) {
      phase_ = Phase::FINISHING;
      ev_stall_end_ = true;
      stall_end_min_ = minutes_ - std::min<float>(above_min_, stall_exit_min);
    }
  }
}

bool Predictor::take_completed(CookRecord &out) {
  if (!completed_pending_)
    return false;
  completed_pending_ = false;
  completed_taken_ = true;
  out = completed_;
  return true;
}

float Predictor::simulate_(float start_t, Phase start_phase, const std::vector<PlanSegment> &plan_in, float pit_now,
                           float k_scale, float stall_scale, float *stall_start_in) const {
  const Profile &p = profiles()[profile_];
  std::vector<PlanSegment> plan = plan_in;
  if (plan.empty()) {
    PlanSegment s;
    s.pit_c = pit_now;
    plan.push_back(s);
  }
  float T = start_t;
  Phase ph = (start_phase == Phase::WAITING || start_phase == Phase::NO_PROBE) ? Phase::WARMING : start_phase;
  bool will_stall = p.stalls && !(stalled_once_ && start_phase != Phase::WAITING) && !std::isnan(target_c_) &&
                    target_c_ > priors_.stall_onset_c + 3.0f && priors_.stall_h > 0.05f;
  if (ph == Phase::FINISHING)
    will_stall = false;
  float stall_left_h = ph == Phase::STALL ? stall_left_h_(stall_scale) : 0;
  const float kpre = k_estimate_(false) * k_scale;
  const float kpost = k_estimate_(true) * k_scale;
  const float dt = 1.0f / 60.0f;
  size_t seg = 0;
  float pit = std::isnan(plan[0].pit_c) ? pit_now : plan[0].pit_c;
  float seg_elapsed = plan[0].elapsed_min;
  float seg_held = plan[0].held_min;
  if (stall_start_in)
    *stall_start_in = NAN;
  for (int m = 0; m < 48 * 60; m++) {
    if (T >= target_c_)
      return float(m);
    // Plan advancement.
    const PlanSegment &s = plan[seg];
    bool cond = false;
    switch (s.until) {
      case PlanSegment::FOOD_GTE:
        cond = T >= s.value;
        break;
      case PlanSegment::FOOD_LTE:
        cond = T <= s.value;
        break;
      case PlanSegment::AFTER_MIN:
        cond = seg_elapsed >= s.value;
        break;
      default:
        break;
    }
    seg_held = cond ? seg_held + 1 : 0;
    seg_elapsed += 1;
    if (cond && seg_held >= s.hold_min && seg + 1 < plan.size()) {
      seg++;
      if (!std::isnan(plan[seg].pit_c))
        pit = plan[seg].pit_c;
      seg_elapsed = 0;
      seg_held = 0;
    }
    // Phase dynamics.
    if (ph == Phase::WARMING && will_stall && T >= priors_.stall_onset_c) {
      ph = Phase::STALL;
      stall_left_h = stall_duration_prior_h(pit) * stall_scale;
      if (stall_start_in && std::isnan(*stall_start_in))
        *stall_start_in = float(m);
    }
    if (ph == Phase::STALL) {
      T += 0.8f * dt;
      stall_left_h -= dt;
      if (stall_left_h <= 0)
        ph = Phase::FINISHING;
      continue;
    }
    float k = (ph == Phase::FINISHING) ? kpost : kpre;
    T += k * (pit - T) * dt;
  }
  return NAN;
}

Prediction Predictor::predict(const std::vector<PlanSegment> &plan, float pit_setpoint_c) const {
  Prediction r;
  if (phase_ == Phase::NO_PROBE) {
    r.reason = "no probe";
    return r;
  }
  if (std::isnan(target_c_)) {
    r.reason = "no target";
    return r;
  }
  if (phase_ == Phase::DONE) {
    r.valid = true;
    r.minutes = r.minutes_low = r.minutes_high = 0;
    return r;
  }
  if (hist_.size() < 10) {
    r.reason = "collecting data";
    return r;
  }
  float pit_now = !std::isnan(pit_setpoint_c) ? pit_setpoint_c : pit_average_(15);
  if (std::isnan(pit_now)) {
    r.reason = "no pit temperature";
    return r;
  }
  float stall_in = NAN;
  float best = simulate_(last_food_, phase_, plan, pit_now, 1.0f, 1.0f, &stall_in);
  if (std::isnan(best)) {
    r.reason = "pit too low for target";
    return r;
  }
  // Uncertainty narrows as this cook's own data accumulates and with more similar cooks.
  float spread = 0.25f / (1.0f + 0.3f * std::min(4.0f, priors_.confidence));
  if (!std::isnan(k_data(false)))
    spread *= 0.7f;
  r.valid = true;
  r.minutes = best;
  r.minutes_low = simulate_(last_food_, phase_, plan, pit_now, 1.0f + spread, 1.0f - 1.6f * spread, nullptr);
  r.minutes_high = simulate_(last_food_, phase_, plan, pit_now, 1.0f - 0.8f * spread, 1.0f + 2.0f * spread, nullptr);
  if (std::isnan(r.minutes_high))
    r.minutes_high = best * 1.5f;
  r.stall_start_in_min = stall_in;
  if (phase_ == Phase::STALL)
    r.stall_remaining_min = 60.0f * stall_left_h_(1.0f);
  return r;
}

float Predictor::estimate_total_minutes(float start_c, float pit_c, const std::vector<PlanSegment> &plan) const {
  if (std::isnan(target_c_) || std::isnan(pit_c))
    return NAN;
  return simulate_(std::isnan(start_c) ? 4.0f : start_c, Phase::WAITING, plan, pit_c, 1.0f, 1.0f, nullptr);
}

double Predictor::cook_minutes_() const { return cook_start_min_ >= 0 ? minutes_ - cook_start_min_ : minutes_; }

}  // namespace cook
