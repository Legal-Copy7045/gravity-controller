#pragma once
// Cook history and similar-cook priors. Pure C++ (unit tested).
//
// Every completed cook leaves a compact record (protein profile, weight, pit
// temperature, fitted heating coefficients, stall length, total time). A new
// cook's starting assumptions come from the most similar past cooks:
//
//   similarity = same profile × weight closeness (log ratio) × pit closeness × wrap match
//
// Each past cook's numbers are rescaled to the new cook's weight and pit
// temperature before averaging:
//   k     ∝ weight^(-2/3)                 (heating time ∝ thickness² ∝ mass^(2/3))
//   stall ∝ weight^(1/3) · pit^(-1.5)
//   plus outdoor temperature / humidity / wind closeness when known.
// With no similar cooks, profile defaults are used, corrected by a grill
// factor learned from *all* past cooks (how this grill compares to typical).

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace cook {

struct CookRecord {
  uint32_t seq{0};       // increasing id; 0 = empty slot
  uint8_t profile{0};
  uint8_t flags{0};      // bit0 wrapped, bit1 stalled
  uint8_t humidity{255};    // outdoor relative humidity %, 255 = unknown
  uint8_t wind_kmh{255};    // outdoor wind speed km/h, 255 = unknown
  float weight_kg{NAN};
  float pit_c{NAN};      // average pit temperature during the cook
  float start_c{NAN};
  float target_c{NAN};
  float k_pre{NAN};      // fitted, 1/h (data only)
  float k_post{NAN};
  float stall_h{NAN};
  float total_h{NAN};
  float stall_onset_c{NAN};
  float ambient_c{NAN};  // outdoor temperature
  float carryover_c{NAN};   // rise after pulling (filled in after the rest)
  float rest_cool_k{NAN};   // cooling coefficient during the rest, 1/h (towards room temperature)
};
static_assert(sizeof(CookRecord) == 56, "CookRecord layout is persisted; keep it stable");
// 0.1.x saved the first 48 bytes (up to ambient_c); the loader converts those.
static_assert(offsetof(CookRecord, carryover_c) == 48, "new fields must stay after the 0.1.x layout");

struct Environment {
  float ambient_c{NAN};
  float humidity{NAN};  // %
  float wind_kmh{NAN};
};

struct Priors {
  float carryover_c{2.5f};   // expected rise after pulling
  float rest_cool_k{0.3f};   // expected cooling coefficient in the rest, 1/h
  float k{0.15f};            // warming coefficient, 1/h
  float k_post_ratio{1.15f}; // k_post / k_pre
  float stall_h{2.5f};       // stall duration at `pit_c`
  float pit_c{107.0f};
  float stall_onset_c{65.0f};
  float confidence{0.0f};    // effective number of similar cooks
  int similar{0};            // count with non-negligible similarity
};

class CookHistory {
 public:
  static constexpr size_t CAPACITY = 40;

  CookHistory();
  /// Adds a record; returns its sequence id.
  uint32_t add(CookRecord r);
  /// Fill in the rest results of a stored record (after the meat has rested).
  bool set_rest(uint32_t seq, float carryover_c, float cool_k);
  const std::vector<CookRecord> &records() const { return records_; }
  size_t count() const;
  void clear();

  /// Priors for a new cook. `weight_kg` NAN = unknown (profile reference weight).
  Priors priors(int profile, float weight_kg, float pit_c, bool wrapped, const Environment &env = {}) const;

  /// How this grill heats compared with the profile defaults (1.0 = typical).
  float grill_factor() const;

  // Persistence: fixed-size blob.
  void load(const CookRecord *data, size_t n);
  void save(CookRecord *data, size_t n) const;

 protected:
  std::vector<CookRecord> records_;
  uint32_t next_seq_{1};
};

}  // namespace cook
