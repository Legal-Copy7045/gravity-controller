// `keep foodN T` (hold mode): keep a food at T by moving the pit target, e.g. to hold a finished cut warm.
//
// Every 4 minutes at most, the pit target becomes T + 10 °C (18 °F) + a correction for how far the food is from T now
// (4× the error) + a slowly learned offset (what this grill and this cut need), inside the grill's range and rounded to
// 5 °F / 2 °C so the grill isn't nudged by a degree at a time. The stock 980 can't go below 200 °F (93 °C), which is
// above any holding temperature: with the pit at its minimum the food still creeps up, slowly. When that happens the
// controller says so once (wrap it and move it to a cooler, or take it off).

#include "cook_assistant.h"

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome {
namespace cook_assistant {

static const char *const TAG = "cook_assistant.keep";

void CookAssistant::keep_tick_(const cook::RunnerInputs &in) {
  const int kp = this->runner_.keep_probe();
  const float want = this->runner_.keep_c();
  if (kp < 1 || std::isnan(want) || size_t(kp) >= in.temp_c.size()) {
    this->keep_probe_active_ = -1;
    return;
  }
  const uint32_t now = millis();
  if (kp != this->keep_probe_active_ || std::fabs(want - this->keep_target_c_) > 0.1f) {
    this->keep_probe_active_ = kp;
    this->keep_target_c_ = want;
    this->keep_i_ = 0;
    this->keep_last_ms_ = now - 600000;  // act now
    this->keep_warned_ = false;
    this->keep_low_since_ = 0;
  }
  const float food = in.temp_c[kp];
  if (std::isnan(food) || now - this->keep_last_ms_ < 240000)
    return;
  const float dt_min = (now - this->keep_last_ms_) / 60000.0f;
  this->keep_last_ms_ = now;
  const float err = want - food;  // °C; positive = the food is too cool
  // Far below what it's kept at (25 °C / 45 °F): a probe that fell out, or food just put on cold. Not a reason to
  // fire the grill up: the pit stays at its lowest and the controller says so once.
  const bool suspect = err > 25.0f;
  if (suspect && !this->keep_probe_warned_) {
    this->keep_probe_warned_ = true;
    std::string name = size_t(kp - 1) < this->probes_.size() ? this->probes_[kp - 1]->label() : "The food";
    this->notify("Check the probe", name + " reads " + this->fmt_temp_(food) + ", far below the " + this->fmt_temp_(want) +
                                        " it's kept at: is the probe still in the food? The pit stays at its lowest "
                                        "until the reading makes sense.",
                 1, "keep");
  } else if (!suspect) {
    this->keep_probe_warned_ = false;
  }
  if (!suspect)
    this->keep_i_ = std::max(-15.0f, std::min(30.0f, this->keep_i_ + 0.05f * err * std::min(dt_min, 10.0f)));
  float pit = suspect ? this->pit_min_c_ : want + 10.0f + 4.0f * err + this->keep_i_;
  // Never more than 40 °C (72 °F) above the food's temperature: keeping warm isn't cooking.
  pit = std::max(this->pit_min_c_, std::min({this->pit_max_c_, want + 40.0f, pit}));
  const float step = this->fahrenheit_ ? 5.0f * 5.0f / 9.0f : 2.0f;
  pit = std::max(this->pit_min_c_, std::min({this->pit_max_c_, want + 40.0f, std::round(pit / step) * step}));
  // Send when it changes, or when the grill doesn't have it (it restarted, or a change at the grill).
  const float rep = this->pit_setpoint_c_();
  const bool grill_differs = !std::isnan(rep) && std::fabs(rep - pit) >= step * 0.9f;
  if (std::isnan(this->last_commanded_c_) || std::fabs(pit - this->last_commanded_c_) >= step * 0.9f || grill_differs) {
    ESP_LOGI(TAG, "Keeping probe %d at %.1f °C (now %.1f): pit to %.0f °C", kp, want, food, pit);
    this->set_pit_(pit);
  }
  // At the grill's minimum and still too hot: say so once.
  const bool at_min = pit <= this->pit_min_c_ + 0.5f;
  if (at_min && food > want + 2.8f) {
    if (this->keep_low_since_ == 0)
      this->keep_low_since_ = now;
    if (!this->keep_warned_ && now - this->keep_low_since_ > 600000) {
      this->keep_warned_ = true;
      std::string name = size_t(kp - 1) < this->probes_.size() ? this->probes_[kp - 1]->label() : "The food";
      this->notify("Can't hold it that low",
                   name + " is " + this->fmt_temp_(food) + ", over the " + this->fmt_temp_(want) +
                       " you asked to keep it at, with the pit already at the grill's lowest (" +
                       this->fmt_temp_(this->pit_min_c_) + "). It will keep creeping up: to hold it longer, wrap it "
                       "and rest it in a cooler, or take it off.",
                   1, "keep");
    }
  } else {
    this->keep_low_since_ = 0;
  }
}

}  // namespace cook_assistant
}  // namespace esphome
