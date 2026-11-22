#include "fuel.h"

#include <algorithm>

namespace cook {

static float clamp01(float f) { return std::max(0.0f, std::min(1.0f, f)); }

float FuelGauge::model_rate(float pit_c, float ambient_c, float fan_fraction) const {
  if (std::isnan(pit_c))
    return 0;
  float amb = std::isnan(ambient_c) ? 15.0f : ambient_c;
  float fan = std::isnan(fan_fraction) ? 0.4f : clamp01(fan_fraction);
  return k_[fuel_] * std::max(0.0f, pit_c - amb) * (0.3f + 0.7f * fan);
}

void FuelGauge::clear() {
  known_ = false;
  kg_ = 0;
  stretch_open_ = false;
  rate_ = NAN;
}

void FuelGauge::level(double now_h, float fraction) {
  float kg = clamp01(fraction) * capacity_kg_;
  if (stretch_open_)
    calibrate_(kg);
  kg_ = kg;
  known_ = true;
  last_h_ = now_h;
  stretch_open_ = true;
  stretch_start_kg_ = kg;
  stretch_added_kg_ = 0;
  stretch_model_kg_ = 0;
}

void FuelGauge::refill_to(double now_h, float fraction) {
  // The level before the top-up isn't known, so the stretch so far can't be calibrated: start a new one.
  float kg = clamp01(fraction) * capacity_kg_;
  kg_ = kg;
  known_ = true;
  last_h_ = now_h;
  stretch_open_ = true;
  stretch_start_kg_ = kg;
  stretch_added_kg_ = 0;
  stretch_model_kg_ = 0;
}

void FuelGauge::add(double now_h, float fraction) {
  float kg = clamp01(fraction) * capacity_kg_;
  if (!known_) {
    // Nothing known yet: the addition is the whole content.
    refill_to(now_h, fraction);
    return;
  }
  kg_ = std::min(capacity_kg_, kg_ + kg);
  stretch_added_kg_ += kg;
  last_h_ = now_h;
}

void FuelGauge::end(double now_h, float fraction) {
  level(now_h, fraction);
  stretch_open_ = false;
  known_ = false;  // cook over
}

void FuelGauge::calibrate_(float observed_kg) {
  float burned = stretch_start_kg_ + stretch_added_kg_ - observed_kg;
  if (stretch_model_kg_ < 0.05f || burned <= 0.05f) {
    stretch_open_ = false;
    return;  // too little burn to learn from (or a refill reported as a check)
  }
  float k_obs = burned / stretch_model_kg_;
  float k_pred = k_[fuel_];
  last_ratio_ = k_obs / k_pred;
  // Weighted average in log space; each stretch counts by how much fuel it burned (in kg), prior worth ~2 kg.
  float w_new = std::min(5.0f, burned);
  float w_old = 2.0f + k_weight_[fuel_];
  float lk = (std::log(k_pred) * w_old + std::log(std::max(0.001f, std::min(0.2f, k_obs))) * w_new) / (w_old + w_new);
  k_[fuel_] = std::exp(lk);
  k_weight_[fuel_] = std::min(30.0f, k_weight_[fuel_] + w_new);
  k_updated_ = true;
  stretch_open_ = false;
}

void FuelGauge::update(double now_h, float pit_c, float ambient_c, float fan_fraction) {
  rate_ = model_rate(pit_c, ambient_c, fan_fraction);
  if (!known_) {
    last_h_ = now_h;
    return;
  }
  if (last_h_ < 0 || now_h <= last_h_) {
    last_h_ = now_h;
    return;
  }
  double dt = std::min(1.0, now_h - last_h_);  // ignore gaps > 1 h (controller off)
  last_h_ = now_h;
  float burn = rate_ * float(dt);
  kg_ = std::max(0.0f, kg_ - burn);
  if (stretch_open_ && k_[fuel_] > 0)
    stretch_model_kg_ += burn / k_[fuel_];
}

float FuelGauge::level_fraction() const { return known_ ? kg_ / capacity_kg_ : NAN; }
float FuelGauge::kg_left() const { return known_ ? kg_ : NAN; }

float FuelGauge::hours_left(float rate) const {
  if (!known_)
    return NAN;
  float r = std::isnan(rate) ? rate_ : rate;
  if (std::isnan(r) || r < 0.01f)
    return NAN;
  return kg_ / r;
}

}  // namespace cook
