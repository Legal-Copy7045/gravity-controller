#pragma once
// Cook-time predictor for one food probe. Pure C++ (no ESPHome), unit tested in tests/.
//
// Model (all temperatures in °C, time in hours):
//
//   Warming / finishing:   dT/dt = k · (T_pit − T)                    (lumped heat transfer)
//   Stall:                 dT/dt ≈ small, for a duration D            (evaporative plateau)
//
// * k is fitted online from the probe's own history (weighted least squares
//   with exponential forgetting, seeded by a per-profile prior). Pre- and
//   post-stall k are tracked separately (wrapping / bark formation changes it).
// * Starting assumptions (k, stall length, stall onset) come from Priors built
//   by CookHistory from similar past cooks (protein, weight, pit, wrapped) –
//   see history.h. The online fit then takes over as the cook's own data
//   accumulates; the more similar cooks there are, the longer the prior holds.
// * The stall is detected from the measured rate; its remaining length is
//   predicted from the priors, adjusted for the pit temperature, the fitted k
//   (bigger cuts stall longer) and wrapping.
// * When the probe reaches its target, a CookRecord is produced for the history.
// * The ETA comes from simulating that model forward minute by minute, with the
//   pit temperature following the active cook program's plan when one exists,
//   so "pit 250 until 165 for 30 min, then 300" is taken into account.
// * Optimistic and pessimistic variants give an ETA range.

#include <cmath>
#include <cstdint>
#include <vector>

#include "history.h"

namespace cook {

enum class Phase : uint8_t { NO_PROBE, WAITING, WARMING, STALL, FINISHING, DONE, RESTING };
const char *phase_name(Phase p);

struct Profile {
  const char *name;
  bool stalls;           // expect an evaporative stall
  float stall_onset_c;   // where the forward model enters the stall
  float stall_hours;     // typical stall duration at a 107 °C (225 °F) pit
  float k_prior;         // typical warming coefficient, 1/h
};

/// Built-in profiles. Index 0 is "Auto".
const Profile *profiles();
int profile_count();
int profile_index(const char *name);  // -1 if unknown

/// One segment of a pit-temperature plan used by the forward simulation.
struct PlanSegment {
  enum Until : uint8_t { FOREVER, FOOD_GTE, FOOD_LTE, AFTER_MIN, UNKNOWN };
  float pit_c{NAN};       // NAN = keep the previous pit temperature
  Until until{FOREVER};
  float value{0};         // °C for FOOD_*, minutes for AFTER_MIN
  float hold_min{0};      // condition must hold this long
  float elapsed_min{0};   // for the first (current) segment: time already spent
  float held_min{0};      // for the first segment: time the condition has already held
};

struct Prediction {
  bool valid{false};
  float minutes{NAN};       // best estimate, from now
  float minutes_low{NAN};   // optimistic
  float minutes_high{NAN};  // pessimistic
  float stall_start_in_min{NAN};  // predicted start of the stall (if still warming)
  float stall_remaining_min{NAN}; // predicted remaining stall (if in stall)
  const char *reason{""};   // why invalid, e.g. "pit below target"
};

class Predictor {
 public:
  void set_profile(int index);
  int profile() const { return profile_; }
  void set_target(float target_c) { target_c_ = target_c; }
  float target() const { return target_c_; }
  /// Priors from CookHistory::priors() for this cook (refresh when profile,
  /// weight, pit setpoint or wrap state change).
  void set_priors(const Priors &p) { priors_ = p; }
  const Priors &priors() const { return priors_; }
  void set_weight(float kg) { weight_kg_ = kg; }
  /// Outdoor conditions (stored with the cook record; used by CookHistory::priors).
  void set_environment(const Environment &e) { env_ = e; }
  /// Hourly outdoor forecast as (minutes from now, °C). Colder hours ahead widen the pit's shortfall
  /// (forecast_beta °C of pit deficit per °C colder, applied to the forecast part of the simulation).
  void set_ambient_forecast(const std::vector<std::pair<float, float>> &f) { forecast_ = f; }
  float forecast_beta{0.15f};

  // ---- rest coach ----
  /// The meat came off the grill (probe still in it). Starts tracking carryover and cooling.
  void set_pulled(double now_h, bool pulled);
  bool pulled() const { return phase_ == Phase::RESTING; }
  /// Recommended pull temperature (target minus the expected carryover), NAN without a target.
  float pull_at() const;
  float carryover_so_far() const { return std::isnan(rest_peak_c_) ? NAN : rest_peak_c_ - rest_pull_c_; }
  /// Minutes until the resting meat cools to `slice_c` (room temperature `room_c`), NAN if unknown.
  float rest_minutes_to(float slice_c, float room_c) const;
  /// Rest results once the peak has passed and cooling is measurable (once per rest).
  bool take_rest_result(float &carryover_c, float &cool_k);
  const Environment &environment() const { return env_; }
  /// Average (setpoint - measured pit) over the last 30 min, °C. Positive = running cold.
  float pit_deficit() const;
  /// Mark the food as wrapped (foil / butcher paper). Shortens the remaining stall.
  void set_wrapped(bool w);
  bool wrapped() const { return wrapped_; }

  /// Feed a sample. `now_h` is a monotonic time in hours. Call at any rate;
  /// samples are bucketed to one per minute internally.
  /// `food_c` NAN means the probe is absent; `pit_c` NAN means unknown.
  void add_sample(double now_h, float food_c, float pit_c, float pit_setpoint_c = NAN);

  /// Compute the prediction. `plan` describes the pit temperature from now on
  /// (first element = current state). If empty, the current pit temperature
  /// (setpoint if `pit_setpoint_c` given, else measured average) is assumed.
  Prediction predict(const std::vector<PlanSegment> &plan, float pit_setpoint_c) const;

  /// Whole-cook estimate before (or regardless of) live data: from `start_c`
  /// (e.g. fridge temperature) to the target at `pit_c`, using only the priors.
  float estimate_total_minutes(float start_c, float pit_c, const std::vector<PlanSegment> &plan) const;

  Phase phase() const { return phase_; }
  float rate_c_per_h() const { return rate_; }        // °C/h over the rate window
  float k_pre() const { return k_estimate_(false); }
  float k_post() const { return k_estimate_(true); }
  float stall_elapsed_h() const;
  float stall_duration_prior_h(float pit_c) const;     // at a given pit temperature
  float current_temp() const { return last_food_; }
  /// True when the probe looks like it slipped out of the meat (sudden jump towards pit temp).
  bool probe_suspect() const { return suspect_; }
  /// Stall events since the last call (for notifications).
  bool take_stall_started() { bool r = ev_stall_start_; ev_stall_start_ = false; return r; }
  bool take_stall_ended() { bool r = ev_stall_end_; ev_stall_end_ = false; return r; }
  bool take_done() { bool r = ev_done_; ev_done_ = false; return r; }
  /// A completed cook (probe reached target). Returns true once per cook.
  bool take_completed(CookRecord &out);
  /// Fitted k from this cook's data only (NAN if not enough data).
  float k_data(bool post) const;

  void reset();

  // Tunables (°C, °C/h, minutes)
  float stall_band_low{57.0f};
  float stall_band_high{82.0f};
  float stall_enter_rate{1.7f};   // 3 °F/h
  float stall_exit_rate{3.3f};    // 6 °F/h
  float stall_enter_min{20.0f};
  float stall_exit_min{10.0f};
  float min_rise_before_stall{10.0f};
  int rate_window_min{20};

 protected:
  struct Sample {
    float food;
    float pit;
  };
  void process_minute_(float food, float pit);
  void update_rate_();
  void update_fit_();
  void update_phase_();
  float k_estimate_(bool post) const;
  float pit_average_(int minutes) const;
  float simulate_(float start_t, Phase start_phase, const std::vector<PlanSegment> &plan, float pit_now,
                  float k_scale, float stall_scale, float *stall_start_in) const;
  float forecast_offset_(float minutes) const;
  void update_rest_();
  float stall_left_h_(float stall_scale) const;
  double cook_minutes_() const;
  void commit_candidate_();

  int profile_{0};
  float target_c_{NAN};
  Priors priors_{};
  float weight_kg_{NAN};
  std::vector<std::pair<float, float>> forecast_;
  double rest_start_min_{-1};
  float rest_pull_c_{NAN};
  float rest_peak_c_{NAN};
  double rest_peak_min_{-1};
  float rest_cool_k_{NAN};
  bool rest_result_pending_{false};
  bool rest_result_taken_{false};
  Environment env_{};
  double env_sum_[3]{0, 0, 0};
  int env_n_[3]{0, 0, 0};
  float last_setpoint_{NAN};
  std::vector<float> deficit_;  // per minute, last 30
  bool wrapped_{false};
  bool wrapped_in_stall_{false};

  std::vector<Sample> hist_;   // one per minute, capped
  static constexpr size_t HIST_MAX = 24 * 60;
  double bucket_start_h_{-1};
  double bucket_food_sum_{0}, bucket_pit_sum_{0};
  int bucket_food_n_{0}, bucket_pit_n_{0};
  double minutes_{0};          // minutes of history since the probe appeared

  Phase phase_{Phase::NO_PROBE};
  float rate_{NAN};
  float last_food_{NAN};
  float start_food_{NAN};
  float below_min_{0};         // minutes the stall-entry condition has held
  float above_min_{0};         // minutes the stall-exit condition has held
  double stall_start_min_{-1};
  double stall_end_min_{-1};
  double cook_start_min_{-1};
  bool cand_valid_{false};
  CookRecord cand_{};
  double cand_since_min_{0};
  float cand_target_c_{NAN};
  bool done_from_cook_{false};
  float deficit_setpoint_{NAN};
  float stall_onset_temp_{NAN};
  double pit_sum_{0};
  int pit_n_{0};
  bool completed_pending_{false};
  bool completed_taken_{false};
  CookRecord completed_{};
  bool stalled_once_{false};
  bool suspect_{false};

  // Weighted least squares sums for k (pre / post stall), with forgetting.
  double sxy_[2]{0, 0}, sxx_[2]{0, 0};

  bool ev_stall_start_{false}, ev_stall_end_{false}, ev_done_{false};
};

}  // namespace cook
