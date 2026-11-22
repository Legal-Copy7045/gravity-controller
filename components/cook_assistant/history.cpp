#include "history.h"

#include <algorithm>

#include "predictor.h"

namespace cook {

CookHistory::CookHistory() { records_.reserve(CAPACITY); }

size_t CookHistory::count() const { return records_.size(); }

void CookHistory::clear() {
  records_.clear();
  next_seq_ = 1;
}

uint32_t CookHistory::add(CookRecord r) {
  r.seq = next_seq_++;
  if (records_.size() >= CAPACITY)
    records_.erase(records_.begin());  // oldest first
  records_.push_back(r);
  return r.seq;
}

bool CookHistory::set_rest(uint32_t seq, float carryover_c, float cool_k) {
  for (auto &r : records_)
    if (r.seq == seq) {
      r.carryover_c = carryover_c;
      r.rest_cool_k = cool_k;
      return true;
    }
  return false;
}

void CookHistory::load(const CookRecord *data, size_t n) {
  records_.clear();
  next_seq_ = 1;
  std::vector<CookRecord> v;
  for (size_t i = 0; i < n; i++)
    if (data[i].seq != 0)
      v.push_back(data[i]);
  std::sort(v.begin(), v.end(), [](const CookRecord &a, const CookRecord &b) { return a.seq < b.seq; });
  for (auto &r : v) {
    if (records_.size() >= CAPACITY)
      records_.erase(records_.begin());
    records_.push_back(r);
    next_seq_ = std::max(next_seq_, r.seq + 1);
  }
}

void CookHistory::save(CookRecord *data, size_t n) const {
  for (size_t i = 0; i < n; i++)
    data[i] = i < records_.size() ? records_[i] : CookRecord{};
}

static float ref_weight(int profile) {
  // Typical weights for the built-in profiles (kg).
  static const float W[] = {3.0f, 3.6f, 6.0f, 1.5f, 2.0f, 2.0f, 0.15f, 0.6f};
  return profile >= 0 && profile < int(sizeof(W) / sizeof(W[0])) ? W[profile] : 3.0f;
}

float CookHistory::grill_factor() const {
  // Weighted geometric mean of observed k / expected default k (weight-scaled).
  double s = 0, n = 0;
  for (const auto &r : records_) {
    if (std::isnan(r.k_pre) || r.k_pre <= 0 || r.profile >= profile_count())
      continue;
    float w = std::isnan(r.weight_kg) ? ref_weight(r.profile) : r.weight_kg;
    float expected = profiles()[r.profile].k_prior * std::pow(ref_weight(r.profile) / w, 2.0f / 3.0f);
    s += std::log(r.k_pre / expected);
    n += 1;
  }
  if (n == 0)
    return 1.0f;
  // Shrink towards 1.0 with few cooks.
  double g = std::exp(s / (n + 1.0));
  return float(std::max(0.4, std::min(2.5, g)));
}

Priors CookHistory::priors(int profile, float weight_kg, float pit_c, bool wrapped, const Environment &env) const {
  if (profile < 0 || profile >= profile_count())
    profile = 0;
  const Profile &pr = profiles()[profile];
  float W = std::isnan(weight_kg) || weight_kg <= 0 ? ref_weight(profile) : weight_kg;
  float pit = std::isnan(pit_c) ? 107.0f : std::max(80.0f, pit_c);

  // Defaults, scaled by weight and the grill factor.
  Priors p;
  float wscale = std::pow(ref_weight(profile) / W, 2.0f / 3.0f);
  p.k = pr.k_prior * wscale * grill_factor();
  p.stall_h = pr.stall_hours * std::pow(W / ref_weight(profile), 1.0f / 3.0f) * std::pow(107.0f / pit, 1.5f);
  if (wrapped && pr.stalls)
    p.stall_h *= 0.6f;
  // Dry air evaporates faster and stretches the stall; humid air shortens it.
  if (pr.stalls && !std::isnan(env.humidity))
    p.stall_h *= std::max(0.75f, std::min(1.3f, 1.0f + 0.3f * (50.0f - env.humidity) / 50.0f));
  // Cold and wind cool the meat surface a little even at the same pit temperature.
  if (!std::isnan(env.ambient_c))
    p.k *= std::max(0.85f, std::min(1.05f, 1.0f - 0.004f * (15.0f - env.ambient_c)));
  if (!std::isnan(env.wind_kmh))
    p.k *= std::max(0.9f, 1.0f - 0.002f * env.wind_kmh);
  p.pit_c = pit;
  p.stall_onset_c = pr.stall_onset_c;
  // Rest defaults: big cuts coast more and cool slower.
  static const float CARRY[] = {2.5f, 3.0f, 3.0f, 1.0f, 3.0f, 2.5f, 0.5f, 1.0f};
  p.carryover_c = profile < int(sizeof(CARRY) / sizeof(CARRY[0])) ? CARRY[profile] : 2.5f;
  p.carryover_c *= std::max(0.5f, std::min(1.6f, std::pow(W / ref_weight(profile), 0.33f)));
  p.rest_cool_k = 0.35f * std::pow(ref_weight(profile) / W, 2.0f / 3.0f);

  // Similar cooks.
  double sw = 0, sk = 0, sstall = 0, swstall = 0, sratio = 0, swratio = 0, sonset = 0, swonset = 0;
  double scarry = 0, swcarry = 0, scool = 0, swcool = 0;
  int similar = 0;
  for (const auto &r : records_) {
    if (r.profile != profile)
      continue;
    float rw = std::isnan(r.weight_kg) ? ref_weight(profile) : r.weight_kg;
    float rpit = std::isnan(r.pit_c) ? 107.0f : std::max(80.0f, r.pit_c);
    double lw = std::log(W / rw);
    double sim = std::exp(-(lw * lw) / (2 * 0.35 * 0.35)) * std::exp(-std::pow((pit - rpit) / 25.0, 2) / 2);
    if (bool(r.flags & 1) != wrapped)
      sim *= 0.5;
    // Outdoor conditions (only when known for both cooks).
    if (!std::isnan(env.ambient_c) && !std::isnan(r.ambient_c))
      sim *= std::exp(-std::pow((env.ambient_c - r.ambient_c) / 12.0, 2) / 2);
    if (!std::isnan(env.humidity) && r.humidity != 255)
      sim *= std::exp(-std::pow((env.humidity - r.humidity) / 30.0, 2) / 2);
    if (!std::isnan(env.wind_kmh) && r.wind_kmh != 255)
      sim *= std::exp(-std::pow((env.wind_kmh - r.wind_kmh) / 20.0, 2) / 2);
    if (sim < 0.02)
      continue;
    similar++;
    if (!std::isnan(r.k_pre) && r.k_pre > 0) {
      sk += sim * std::log(r.k_pre * std::pow(rw / W, 2.0f / 3.0f));
      sw += sim;
    }
    if (!std::isnan(r.k_post) && !std::isnan(r.k_pre) && r.k_pre > 0) {
      sratio += sim * (r.k_post / r.k_pre);
      swratio += sim;
    }
    if (pr.stalls && !std::isnan(r.stall_h) && (r.flags & 2)) {
      sstall += sim * r.stall_h * std::pow(W / rw, 1.0f / 3.0f) * std::pow(rpit / pit, 1.5f);
      swstall += sim;
    }
    if (!std::isnan(r.carryover_c)) {
      scarry += sim * r.carryover_c * std::pow(W / rw, 0.33f);
      swcarry += sim;
    }
    if (!std::isnan(r.rest_cool_k) && r.rest_cool_k > 0) {
      scool += sim * std::log(r.rest_cool_k * std::pow(rw / W, 2.0f / 3.0f));
      swcool += sim;
    }
    if (!std::isnan(r.stall_onset_c) && (r.flags & 2)) {
      sonset += sim * r.stall_onset_c;
      swonset += sim;
    }
  }
  // Blend: each similar cook counts as one pseudo-observation against a
  // default worth one.
  if (sw > 0) {
    double kh = std::exp(sk / sw);
    p.k = float((p.k + kh * sw) / (1.0 + sw));
  }
  if (swratio > 0)
    p.k_post_ratio = float(std::max(0.7, std::min(2.5, (p.k_post_ratio + sratio) / (1.0 + swratio))));
  if (swstall > 0)
    p.stall_h = float((p.stall_h + sstall) / (1.0 + swstall));
  if (swcarry > 0)
    p.carryover_c = float((p.carryover_c + scarry) / (1.0 + swcarry));
  if (swcool > 0)
    p.rest_cool_k = float(std::exp((std::log(p.rest_cool_k) + scool) / (1.0 + swcool)));
  if (swonset > 0)
    p.stall_onset_c = float((p.stall_onset_c + sonset) / (1.0 + swonset));
  p.confidence = float(sw);
  p.similar = similar;
  p.k = std::max(0.02f, std::min(2.0f, p.k));
  p.stall_h = std::max(0.0f, std::min(10.0f, p.stall_h));
  return p;
}

}  // namespace cook
