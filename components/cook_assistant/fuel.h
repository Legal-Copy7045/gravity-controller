#pragma once
// Charcoal fuel gauge (no hopper sensor). Pure C++, unit tested in tests/.
//
// You tell it what you see; it estimates the burn in between:
//   * level(fraction)          "the hopper is at 3/4" (a check: no fuel added)  -> calibrates
//   * refill_to(fraction)      "topped up, it's now at 1/2"  (amount added unknown: estimated)
//   * add(fraction)            "added a quarter of a hopper" (exact amount added)
//   * end(fraction)            "finished, 1/8 left"          -> calibrates, closes the cook
//
// Burn model (kg/h):  rate = k · max(0, T_pit − T_ambient) · (0.3 + 0.7 · fan_fraction)
// k is learned per fuel type from every calibrated stretch (known fuel at the start, known adds, observed level at
// the end), so after a few cooks "2.5 h left" means 2.5 h on *your* grill with *your* charcoal.

#include <cmath>
#include <cstdint>

namespace cook {

class FuelGauge {
 public:
  enum Fuel : uint8_t { BRIQUETTES = 0, LUMP = 1, FUEL_COUNT = 2 };

  void set_capacity_kg(float kg) { capacity_kg_ = kg; }
  float capacity_kg() const { return capacity_kg_; }
  void set_fuel(Fuel f) { fuel_ = f < FUEL_COUNT ? f : BRIQUETTES; }
  Fuel fuel() const { return fuel_; }
  /// Learned burn coefficients (persisted by the caller).
  void set_k(Fuel f, float k, float weight) {
    if (f < FUEL_COUNT && k > 0) {
      k_[f] = k;
      k_weight_[f] = weight;
    }
  }
  float k(Fuel f) const { return k_[f]; }
  float k_weight(Fuel f) const { return k_weight_[f]; }

  // --- observations (fractions of a full hopper, 0..1) ---
  void level(double now_h, float fraction);
  void refill_to(double now_h, float fraction);
  void add(double now_h, float fraction);
  void end(double now_h, float fraction);
  /// Forget the current cook's fuel state (not the learned k).
  void clear();

  /// Integrate the burn since the last call. Call about once a minute.
  void update(double now_h, float pit_c, float ambient_c, float fan_fraction);

  bool known() const { return known_; }
  float level_fraction() const;   // estimated now, NAN if unknown
  float kg_left() const;
  float rate_kg_h() const { return rate_; }
  /// Hours of fuel left at `rate_kg_h` (or a given rate), NAN if unknown.
  float hours_left(float rate_kg_h = NAN) const;
  /// Last calibration result (ratio actual / predicted burn), for display.
  float last_ratio() const { return last_ratio_; }
  /// True once after a calibration updated k (caller persists).
  bool take_k_updated() {
    bool r = k_updated_;
    k_updated_ = false;
    return r;
  }
  /// Burn rate the model predicts for given conditions.
  float model_rate(float pit_c, float ambient_c, float fan_fraction) const;

 protected:
  void calibrate_(float observed_kg);

  float capacity_kg_{7.3f};  // Gravity 980: 16 lb hopper
  Fuel fuel_{BRIQUETTES};
  float k_[FUEL_COUNT]{0.012f, 0.009f};  // kg/h per °C of pit-over-ambient at full fan weighting
  float k_weight_[FUEL_COUNT]{0, 0};

  bool known_{false};
  float kg_{0};             // estimated fuel now
  double last_h_{-1};
  double last_burn_h_{-1};  // last time the model burned fuel
  float rate_{NAN};
  // Calibration stretch: fuel known at its start + known additions, model burn integrated over it.
  bool stretch_open_{false};
  float stretch_start_kg_{0};
  float stretch_added_kg_{0};
  float stretch_model_kg_{0};  // model burn with k = 1 (so actual = k_true · this)
  float last_ratio_{NAN};
  bool k_updated_{false};
};

}  // namespace cook
