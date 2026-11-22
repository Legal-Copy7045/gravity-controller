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
// With no similar cooks, profile defaults are used, corrected by a grill
// factor learned from *all* past cooks (how this grill compares to typical).

#include <cmath>
#include <cstdint>
#include <vector>

namespace cook {

struct CookRecord {
  uint32_t seq{0};       // increasing id; 0 = empty slot
  uint8_t profile{0};
  uint8_t flags{0};      // bit0 wrapped, bit1 stalled
  uint16_t reserved{0};
  float weight_kg{NAN};
  float pit_c{NAN};      // average pit temperature during the cook
  float start_c{NAN};
  float target_c{NAN};
  float k_pre{NAN};      // fitted, 1/h (data only)
  float k_post{NAN};
  float stall_h{NAN};
  float total_h{NAN};
  float stall_onset_c{NAN};
  float spare{NAN};
};
static_assert(sizeof(CookRecord) == 48, "CookRecord layout is persisted; keep it stable");

struct Priors {
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
  void add(CookRecord r);
  const std::vector<CookRecord> &records() const { return records_; }
  size_t count() const;
  void clear();

  /// Priors for a new cook. `weight_kg` NAN = unknown (profile reference weight).
  Priors priors(int profile, float weight_kg, float pit_c, bool wrapped) const;

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
