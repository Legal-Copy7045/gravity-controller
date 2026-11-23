// Stage 2 of running without Home Assistant (docs/standalone.md): what the device page needs to stand on its own.
//  - a 24 h history of the pit and food temperatures, one sample a minute, for the page's chart;
//  - the journal: every finished cook, with stars, "How was it?" tags and notes, kept in flash;
//  - the plan: a serve-by time; "light the grill by" from the controller's own estimate, with a reminder;
//  - Open Pitmaster (github.com/Legal-Copy7045/open-pitmaster): anonymous, opt-in sharing straight from the
//    controller, and the shared averages.
#include "standalone.h"

#include <cmath>
#include <cstring>
#include <ctime>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "../cook_assistant/cook_assistant.h"
#include "esphome/components/network/util.h"
#include <algorithm>

#ifdef USE_ESP32
#include <esp_heap_caps.h>
#endif

namespace esphome {
namespace standalone {

static std::string json_str(const std::string &v) {  // a JSON string literal, escaped
  JsonDocument d;
  d.set(v);
  std::string o;
  serializeJson(d, o);
  return o;
}

static const char *const TAG = "standalone";
static const char *const SHARE_URL = "https://api.open-pitmaster.workers.dev";
static const char *const AGGREGATES_URL =
    "https://raw.githubusercontent.com/Legal-Copy7045/open-pitmaster/main/data/aggregates.json";
// "How was it?": the same list, in the same order, as the integration and the Open Pitmaster format.
static const char *const TAGS[] = {"juicy",      "tender",      "dry",       "tough",          "undercooked",
                                   "just right", "overcooked",  "great bark", "soft bark",     "good smoke",
                                   "too smoky",  "too little smoke", "fat rendered", "fat not rendered"};
static constexpr size_t N_TAGS = sizeof(TAGS) / sizeof(TAGS[0]);
static const char *const CUTS[] = {"Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish", "Auto"};
static constexpr uint32_t SHARE_GAP_MS = 61000;            // Open Pitmaster: one stored upload a minute per client
static constexpr uint32_t SHARE_BUSY_429_MS = 5 * 60000;    // after "too many requests"
static constexpr uint32_t SHARE_BUSY_503_MS = 30 * 60000;   // after its daily cap ("unavailable")
static constexpr uint32_t READY_AFTER_S = 12 * 3600;  // a cook without feedback is offered this long after it ended

static uint32_t epoch_now() {
  time_t t = ::time(nullptr);
  return t > 1700000000 ? uint32_t(t) : 0;  // 0 until the clock has been set
}
static std::string hex32(uint32_t v) {
  char b[9];
  std::snprintf(b, sizeof(b), "%08x", unsigned(v));
  return b;
}

// A group from Open Pitmaster's aggregates.json, as its nightly build writes them: a known cut, band labels like
// "8-10 lb" / "225-255°F" / "any weather", and finite times. Anything else is someone else's text: dropped.
static bool band_ok_(const char *v, const char *any, const char *unit) {
  if (v == nullptr) return false;
  std::string s(v);
  if (s == any) return true;
  if (s.size() > 24) return false;
  size_t u = s.rfind(unit);
  if (u == std::string::npos || u + std::strlen(unit) != s.size()) return false;
  std::string n = s.substr(0, u);
  while (!n.empty() && n.back() == ' ') n.pop_back();
  if (n.rfind("under ", 0) == 0) n = n.substr(6);
  if (!n.empty() && n.back() == '+') n.pop_back();
  size_t dash = n.find('-', 1);
  auto digits = [](const std::string &x) {
    if (x.empty() || x.size() > 3) return false;
    for (char c : x) if (c < '0' || c > '9') return false;
    return true;
  };
  return dash == std::string::npos ? digits(n) : digits(n.substr(0, dash)) && digits(n.substr(dash + 1));
}

bool Standalone::community_group_ok_(JsonObject g) {
  static const char *const CUTS[] = {"Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish"};
  const char *cut = g["cut"] | "";
  bool known = false;
  for (const char *c : CUTS) known |= std::strcmp(cut, c) == 0;
  if (!known) return false;
  if (!band_ok_(g["weight"] | (const char *) nullptr, "any weight", "lb")) return false;
  if (!band_ok_(g["pit"] | (const char *) nullptr, "any pit", "\u00b0F")) return false;
  if (!band_ok_(g["outside"] | (const char *) nullptr, "any weather", "\u00b0F")) return false;
  int n = g["n"] | 0;
  if (n < 1 || n > 1000000) return false;
  for (const char *k : {"total_h", "total_p25", "total_p75", "stall_h"}) {
    JsonVariant v = g[k];
    if (v.isNull()) continue;
    float f = v.as<float>();
    if (!v.is<float>() || !std::isfinite(f) || f < 0 || f > 48) return false;
  }
  return !g["total_h"].isNull();
}

// ---------------------------------------------------------------- setup / loop

void Standalone::setup_cook_() {
  this->setup_ai_();
  this->pref2_ = global_preferences->make_preference<Settings2>(fnv1_hash("standalone_settings2_v1"), true);
  Settings2 s2{};
  if (this->pref2_.load(&s2) && s2.version == 1)
    this->s2_ = s2;
  for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
    this->jpref_[i] = global_preferences->make_preference<JEntry>(fnv1_hash("standalone_journal_v1_") + i, true);
    JEntry e{};
    if (this->jpref_[i].load(&e))
      this->journal_[i] = e;
    if (this->journal_[i].share == 3)
      this->journal_[i].share = 0;  // was being sent when the controller restarted
  }
  size_t n = HIST_SERIES * HIST_LEN;
#ifdef USE_ESP32
  this->hist_ = static_cast<int16_t *>(heap_caps_malloc(n * sizeof(int16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
#endif
  if (this->hist_ == nullptr)
    this->hist_ = static_cast<int16_t *>(malloc(n * sizeof(int16_t)));  // NOLINT
  if (this->hist_ != nullptr)
    for (size_t i = 0; i < n; i++) this->hist_[i] = INT16_MIN;
}

void Standalone::loop_cook_(uint32_t now) {
  if (now - this->hist_last_ >= 60000 || this->hist_last_ == 0) {
    this->hist_last_ = now ? now : 1;  // not "now | 1": 1 ms ahead, now - it wraps
    this->sample_history_();
  }
  this->loop_ai_(now);
  if (this->ai_save_) {
    this->ai_save_ = false;
    AiSettings a;
    {
      std::lock_guard<std::recursive_mutex> g(this->lock_);
      a = this->ai_;
    }
    this->aipref_.save(&a);
  }
  // A charcoal log from the device page (the cook assistant runs in this loop, not in the web server's task).
  if (this->fuel_mode_ >= 0 && this->cook_ != nullptr) {
    int8_t m;
    float pct;
    {
      std::lock_guard<std::recursive_mutex> g(this->lock_);
      m = this->fuel_mode_;
      pct = this->fuel_pct_;
      this->fuel_mode_ = -1;
    }
    if (m == 0 || m == 2) this->cook_->fuel_refilled(pct);  // started at / topped up to
    else if (m == 1) this->cook_->fuel_level(pct);
    else if (m == 3) this->cook_->fuel_added(pct);
    else if (m == 4) this->cook_->fuel_end(pct);
  }
  // Results of shares, withdrawals and the averages, from the worker.
  std::vector<Done> done;
  {
    std::lock_guard<std::mutex> g(this->results_lock_);
    done.swap(this->done_);
  }
  for (auto &d : done) {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    if (d.what.rfind("ai:", 0) == 0) {
      this->ai_done_(d.what, d.code, d.body);
      continue;
    }
    if (d.what.rfind("share:", 0) == 0 || d.what.rfind("unshare:", 0) == 0) {
      bool share = d.what[0] == 's';
      uint32_t id = strtoul(d.what.c_str() + (share ? 6 : 8), nullptr, 16);
      for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
        JEntry &e = this->journal_[i];
        if (e.id != id) continue;
        const bool busy = d.code == 429 || d.code == 503;  // Open Pitmaster's rate limit or daily cap: try later
        if (busy) {
          // Kept queued with the same id and key (a 409 later means it did arrive), sent again after a pause.
          if (share) { e.share = 3; this->share_wait_ |= 1u << i; }
          else if (e.share == 1 && e.share_id[0]) this->unshare_wait_ |= 1u << i;
          this->share_sent_at_ = now ? now : 1;
          this->share_hold_ms_ = d.code == 503 ? SHARE_BUSY_503_MS : SHARE_BUSY_429_MS;
          ESP_LOGI(TAG, "Open Pitmaster is busy (HTTP %d): %s again in %u min", d.code,
                   share ? "sharing" : "withdrawing", unsigned(this->share_hold_ms_ / 60000));
          this->share_results_.push_back({id, "Open Pitmaster is busy (HTTP " + std::to_string(d.code) + "): will try again"});
        } else if (share) {
          bool ok = d.code == 201 || d.code == 409;
          e.share = ok ? 1 : 0;
          if (!ok) { e.share_id[0] = 0; e.share_key[0] = 0; }
          this->share_results_.push_back({id, ok ? "shared" : (d.code ? "refused (HTTP " + std::to_string(d.code) + ")" : "couldn't reach Open Pitmaster")});
        } else if (d.code == 200 || d.code == 404) {
          // 200: deleted ({"already":true}: it had been already). 404: Open Pitmaster never stored it, though it had
          // answered 201/409 when it was shared: said in the log and on the page, not passed over in silence.
          if (d.code == 404) {
            ESP_LOGW(TAG, "Withdrawing cook %08x: Open Pitmaster has no record of it (HTTP 404), though it was shared",
                     unsigned(id));
            this->share_results_.push_back({id, "not found on Open Pitmaster (HTTP 404): nothing to remove there"});
          } else {
            JsonDocument r = json::parse_json(d.body);
            this->share_results_.push_back({id, (r["already"] | false) ? "already removed" : "removed"});
          }
          e.share = 2;
          e.share_id[0] = 0;
          e.share_key[0] = 0;
        } else {
          this->share_results_.push_back({id, d.code ? "couldn't remove (HTTP " + std::to_string(d.code) + "): try again"
                                                     : "couldn't reach Open Pitmaster to remove it: try again"});
        }
        this->journal_dirty_ |= 1u << i;
      }
      if (this->share_results_.size() > 8) this->share_results_.erase(this->share_results_.begin());
    } else if (d.what == "aggregates" && d.code == 200) {
      JsonDocument doc = json::parse_json(d.body);
      if ((doc["v"] | 0) == 1) {
        this->community_.clear();
        this->community_cooks_ = doc["cooks"] | 0;
        this->community_updated_ = doc["updated"] | "";
        for (JsonObject g : doc["groups"].as<JsonArray>()) {
          if (this->community_.size() >= 60) break;
          // The text goes into the AI's prompt: only the builder's own words and numbers, anything else is dropped.
          if (!community_group_ok_(g)) continue;
          char line[200];
          std::snprintf(line, sizeof(line), "%s %s at %s (%s outside): typically %.1f h (%.1f-%.1f), stall %.1f h; %d cooks",
                        g["cut"] | "", g["weight"] | "", g["pit"] | "", g["outside"] | "", double(g["total_h"] | 0.0f),
                        double(g["total_p25"] | 0.0f), double(g["total_p75"] | 0.0f), double(g["stall_h"] | 0.0f),
                        int(g["n"] | 0));
          this->community_.push_back({g["cut"] | "", line});
        }
        this->community_at_ = now ? now : 1;  // not "now | 1": 1 ms ahead, now - it wraps
      }
    }
  }
  this->share_pump_(now);
  // Averages: once at start-up, then twice a day.
  static uint32_t community_asked = 0;
  if (network_ready_() && (community_asked == 0 || now - community_asked > 12UL * 3600 * 1000)) {
    community_asked = now ? now : 1;  // not "now | 1": 1 ms ahead, now - it wraps
    this->queue_({"aggregates", "GET", AGGREGATES_URL, "", "", {}});
  }
  // Flash: journal entries changed in the web handler are saved here (in the main loop).
  if (this->journal_dirty_) {
    uint32_t dirty;
    {
      std::lock_guard<std::recursive_mutex> g(this->lock_);
      dirty = this->journal_dirty_;
      this->journal_dirty_ = 0;
    }
    for (size_t i = 0; i < JOURNAL_SLOTS; i++)
      if (dirty & (1u << i)) this->save_journal_(i);
  }
  // Every 30 s: the plan's reminder, and automatic sharing of cooks that became ready.
  static uint32_t every30 = 0;
  if (now - every30 < 30000) return;
  every30 = now;
  const uint32_t t = epoch_now();
  if (t == 0) return;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    float est = NAN;
    int light = this->light_by_(t, &est);
    if (light > 0 && uint32_t(light) <= t && this->s2_.light_notified_for != this->s2_.serve_by &&
        t < this->s2_.serve_by) {
      this->s2_.light_notified_for = this->s2_.serve_by;
      this->save_pending_ = true;
      time_t sb = this->s2_.serve_by;
      struct tm lt;
      localtime_r(&sb, &lt);
      char msg[120];
      std::snprintf(msg, sizeof(msg), "Light the grill now to serve at %02d:%02d (about %.0f h of cooking plus a %u min rest).",
                    lt.tm_hour, lt.tm_min, est / 60.0f, unsigned(this->s2_.rest_min));
      if (this->cook_ != nullptr) this->cook_->notify("Time to light the grill", msg, 1, "plan");  // re-enters lock_: fine
    }
    if (this->s2_.share_enabled && this->s2_.share_auto) {
      for (auto &e : this->journal_) {
        if (e.id && e.share == 0 && e.ended >= this->s2_.auto_since &&
            (e.rating || e.tags || (e.ended && t - e.ended >= READY_AFTER_S))) {
          std::string why;
          this->share_entry_(e, why);
          break;  // one at a time
        }
      }
    }
  }
}

bool Standalone::network_ready_() { return network::is_connected(); }

void Standalone::save_journal_(size_t i) {
  JEntry copy;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    copy = this->journal_[i];
  }
  this->jpref_[i].save(&copy);
}

// ---------------------------------------------------------------- history (chart)

void Standalone::sample_history_() {
  if (this->hist_ == nullptr) return;
  float v[HIST_SERIES];
  for (auto &x : v) x = NAN;
#ifdef USE_SENSOR
  if (this->pit_ && this->pit_->has_state()) v[0] = this->pit_->state;
  if (this->pit_target_ && this->pit_target_->has_state()) v[1] = this->pit_target_->state;
#endif
  if (this->cook_ != nullptr) {
    const auto &ps = this->cook_->probes();
    for (size_t i = 0; i < ps.size() && i + 2 < HIST_SERIES; i++)
      if (ps[i]->reading && ps[i]->reading->has_state() && millis() - ps[i]->reading_ms < 5 * 60000)
        v[i + 2] = ps[i]->reading->state;
  }
  std::lock_guard<std::mutex> g(this->hist_lock_);
  for (size_t s = 0; s < HIST_SERIES; s++)
    this->hist_[s * HIST_LEN + this->hist_head_] =
        std::isnan(v[s]) || std::fabs(v[s]) > 3000 ? INT16_MIN : int16_t(std::lround(v[s] * 10));
  this->hist_head_ = (this->hist_head_ + 1) % HIST_LEN;
  if (this->hist_count_ < HIST_LEN) this->hist_count_++;
}

std::string Standalone::history_json_(int hours) {
  if (hours < 1) hours = 1;
  if (hours > 24) hours = 24;
  std::string out = "{\"step_min\":";
  std::lock_guard<std::mutex> g(this->hist_lock_);
  size_t want = std::min<size_t>(size_t(hours) * 60, this->hist_count_);
  size_t step = std::max<size_t>(1, (want + 359) / 360);  // at most ~360 points a series
  out += std::to_string(step) + ",\"age_s\":" + std::to_string((millis() - this->hist_last_) / 1000) + ",\"names\":[\"Pit\",\"Pit target\"";
  if (this->cook_ != nullptr)
    for (size_t i = 0; i < this->cook_->probes().size() && i + 2 < HIST_SERIES; i++)
      out += "," + json_str(this->cook_->probes()[i]->name);
  out += "],\"series\":[";
  size_t nseries = this->cook_ != nullptr ? std::min(HIST_SERIES, this->cook_->probes().size() + 2) : 2;
  for (size_t s = 0; s < nseries; s++) {
    out += s ? ",[" : "[";
    bool any = false;
    std::string pts;
    // oldest first: the newest sample is just before hist_head_
    for (size_t k = want; k >= step; k -= step) {
      size_t idx = (this->hist_head_ + HIST_LEN - k) % HIST_LEN;
      int16_t raw = this->hist_[s * HIST_LEN + idx];
      if (!pts.empty()) pts += ",";
      if (raw == INT16_MIN) pts += "null";
      else { char b[12]; std::snprintf(b, sizeof(b), "%.1f", raw / 10.0); pts += b; any = true; }
      if (k < step * 2) break;
    }
    out += any ? pts : "";
    out += "]";
  }
  out += "]}";
  return out;
}

// ---------------------------------------------------------------- journal

void Standalone::add_cook(const std::string &summary) {
  JsonDocument d = json::parse_json(summary);
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  size_t slot = 0;
  uint32_t oldest = UINT32_MAX, top = 0;
  for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
    const JEntry &e = this->journal_[i];
    if (e.id == 0) { slot = i; oldest = 0; continue; }
    top = std::max(top, e.seq);
    if (oldest != 0 && e.seq < oldest) { oldest = e.seq; slot = i; }
  }
  JEntry e{};
  do { e.id = random_uint32(); } while (e.id == 0);
  e.seq = top + 1;
  e.ended = epoch_now();
  std::strncpy(e.profile, d["profile"] | "Auto", sizeof(e.profile) - 1);
  e.weight_kg = d["weight_kg"] | NAN;
  e.pit_c = d["pit_c"] | NAN;
  e.target_c = d["target_c"] | NAN;
  e.stall_h = d["stall_h"] | NAN;
  e.total_h = d["total_h"] | NAN;
  e.ambient_c = d["ambient_c"] | NAN;
  e.wrapped = d["wrapped"].is<bool>() ? (d["wrapped"].as<bool>() ? 1 : 0) : 2;
  this->journal_[slot] = e;
  this->journal_dirty_ |= 1u << slot;
  ESP_LOGI(TAG, "Journal: %s, %.1f h", e.profile, e.total_h);
}

static std::string tag_names(uint16_t bits) {
  std::string s;
  for (size_t i = 0; i < N_TAGS; i++)
    if (bits & (1u << i)) { if (!s.empty()) s += ","; s += std::string("\"") + TAGS[i] + "\""; }
  return s;
}

static double band(float v, double step, double lo, double hi, bool floor_ = false) {
  double q = floor_ ? std::floor(v / step) * step : std::round(v / step) * step;
  q = std::min(hi, std::max(lo, q));
  return std::round(q * 10) / 10;
}

std::string Standalone::record_json_(const JEntry &e, const char *id) {
  // The only thing that ever leaves for Open Pitmaster: rounded, banded, no time, place, notes or names.
  auto c2f = [](float c) { return c * 9.0f / 5.0f + 32.0f; };
  if (std::isnan(e.total_h) || e.total_h < 0.5f) return "";
  double total = band(e.total_h, 0.1, 0.5, 36);
  std::string cut = "Auto";
  for (auto *c : CUTS) if (std::strcmp(c, e.profile) == 0) cut = c;
  int month = 0;
  if (e.ended) { time_t t = e.ended; struct tm tmv; gmtime_r(&t, &tmv); month = tmv.tm_mon; }
  static const char *const NORTH[] = {"winter", "winter", "spring", "spring", "spring", "summer",
                                      "summer", "summer", "autumn", "autumn", "autumn", "winter"};
  std::string season = NORTH[month];
  if (!std::isnan(this->s_.lat) && this->s_.lat < 0)
    season = season == "winter" ? "summer" : season == "summer" ? "winter" : season == "spring" ? "autumn" : "spring";
  return json::build_json([&](JsonObject o) {
    o["v"] = 1;
    o["id"] = id;
    o["grill"] = "gravity980";
    o["release"] = ESPHOME_PROJECT_VERSION;
    o["season"] = season;
    o["cut"] = cut;
    if (!std::isnan(e.weight_kg) && e.weight_kg > 0) o["weight_lb"] = band(e.weight_kg * 2.20462f, 0.5, 0.5, 25); else o["weight_lb"] = nullptr;
    if (e.wrapped < 2) o["wrapped"] = e.wrapped == 1; else o["wrapped"] = nullptr;
    if (!std::isnan(e.pit_c) && c2f(e.pit_c) >= 200) o["pit_f"] = band(c2f(e.pit_c), 5, 200, 700); else o["pit_f"] = nullptr;
    if (!std::isnan(e.target_c)) o["target_f"] = band(c2f(e.target_c), 1, 100, 250); else o["target_f"] = nullptr;
    if (!std::isnan(e.stall_h)) o["stall_h"] = std::min(total, band(e.stall_h, 0.1, 0, 24)); else o["stall_h"] = nullptr;
    o["total_h"] = total;
    if (!std::isnan(e.ambient_c)) o["outside_f"] = band(c2f(e.ambient_c), 5, -10, 110, true); else o["outside_f"] = nullptr;
    if (e.rating >= 1 && e.rating <= 5) o["rating"] = e.rating; else o["rating"] = nullptr;
    JsonArray t = o["tags"].to<JsonArray>();
    for (size_t i = 0; i < N_TAGS; i++) if (e.tags & (1u << i)) t.add(TAGS[i]);
  }).c_str();
}

bool Standalone::share_entry_(JEntry &e, std::string &why) {
  if (e.share == 1 || e.share == 3) return true;
  uint8_t rnd[16], key[24];
  random_bytes(rnd, sizeof(rnd));
  random_bytes(key, sizeof(key));
  std::string id = pinauth::to_hex(rnd, sizeof(rnd)), k = pinauth::to_hex(key, sizeof(key));
  if (this->record_json_(e, id.c_str()).empty()) { why = "This cook can't be shared (no total time)"; return false; }
  std::strncpy(e.share_id, id.c_str(), sizeof(e.share_id) - 1);
  std::strncpy(e.share_key, k.c_str(), sizeof(e.share_key) - 1);
  e.share = 3;  // sending: share_pump_ sends it (one upload a minute at most)
  this->share_wait_ |= 1u << size_t(&e - this->journal_);
  return true;
}

// Open Pitmaster takes one stored upload a minute per client (and has a daily cap): uploads and withdrawals go out
// one at a time, at least SHARE_GAP_MS apart, longer after a 429/503 (share_hold_ms_). From the main loop.
void Standalone::share_pump_(uint32_t now) {
  if (this->share_sent_at_ != 0 && now - this->share_sent_at_ < std::max(SHARE_GAP_MS, this->share_hold_ms_)) return;
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  if (this->share_sent_at_ != 0) {  // the pause is over: cleared, so millis() wrapping can't bring it back
    this->share_sent_at_ = 0;
    this->share_hold_ms_ = 0;
  }
  if ((this->share_wait_ | this->unshare_wait_) == 0 || !this->network_ready_()) return;
  for (int pass = 0; pass < 2; pass++) {  // withdrawals first
    uint32_t &wait = pass == 0 ? this->unshare_wait_ : this->share_wait_;
    for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
      if (!(wait & (1u << i))) continue;
      wait &= ~(1u << i);
      JEntry &e = this->journal_[i];
      if (pass == 0 && e.id && e.share == 1 && e.share_id[0]) {
        this->queue_({"unshare:" + hex32(e.id), "DELETE", std::string(SHARE_URL) + "/v1/cooks/" + e.share_id, "", "",
                      {{"X-Delete-Key", e.share_key}}});
      } else if (pass == 1 && e.id && e.share == 3 && e.share_id[0] && e.share_key[0]) {
        std::string rec = this->record_json_(e, e.share_id);
        if (rec.empty()) { e.share = 0; continue; }
        auto h = pinauth::sha256(reinterpret_cast<const uint8_t *>(e.share_key), std::strlen(e.share_key));
        std::string body = "{\"record\":" + rec + ",\"key_hash\":\"" + pinauth::to_hex(h.data(), h.size()) + "\"}";
        this->queue_({"share:" + hex32(e.id), "POST", std::string(SHARE_URL) + "/v1/cooks", body, "application/json", {}});
      } else {
        continue;  // changed meanwhile (deleted, declined): nothing to send
      }
      this->share_sent_at_ = now ? now : 1;
      return;
    }
  }
}

std::string Standalone::journal_json_(bool authed) {
  std::vector<const JEntry *> list;
  for (auto &e : this->journal_) if (e.id) list.push_back(&e);
  std::sort(list.begin(), list.end(), [](const JEntry *a, const JEntry *b) { return a->seq > b->seq; });
  const uint32_t t = epoch_now();
  std::string out = "{\"share\":{\"enabled\":" + std::string(this->s2_.share_enabled ? "true" : "false") +
                    ",\"auto\":" + (this->s2_.share_auto ? "true" : "false") + "},\"entries\":[";
  bool first = true;
  for (const JEntry *e : list) {
    std::string ent = json::build_json([&](JsonObject o) {
      o["id"] = hex32(e->id);
      o["ended"] = e->ended;
      o["profile"] = e->profile;
      auto num = [&](const char *k, float v) { if (!std::isnan(v)) o[k] = std::round(v * 100) / 100; };
      num("weight_kg", e->weight_kg); num("pit_c", e->pit_c); num("target_c", e->target_c);
      num("stall_h", e->stall_h); num("total_h", e->total_h); num("ambient_c", e->ambient_c);
      if (e->wrapped < 2) o["wrapped"] = e->wrapped == 1;
      if (e->rating) o["rating"] = e->rating;
      if (authed || !this->req_pin_) o["notes"] = e->notes;  // private: only for an unlocked page
      static const char *const ST[] = {"pending", "shared", "declined", "sending"};
      bool ready = e->rating || e->tags || (e->ended && t && t - e->ended >= READY_AFTER_S);
      o["share"] = e->share == 0 && !ready ? "waiting" : ST[e->share & 3];
    }).c_str();
    // tags and the exact record that would be (or was) shared, never the deletion key
    ent.pop_back();
    ent += ",\"tags\":[" + tag_names(e->tags) + "]";
    std::string rec = this->record_json_(*e, e->share_id[0] ? e->share_id : "0123456789abcdef0123456789abcdef");
    if (!rec.empty()) ent += ",\"record\":" + rec;
    ent += "}";
    out += (first ? "" : ",") + ent;
    first = false;
  }
  out += "],\"results\":[";
  for (size_t i = 0; i < this->share_results_.size(); i++)
    out += (i ? ",{\"id\":\"" : "{\"id\":\"") + hex32(this->share_results_[i].first) + "\",\"result\":\"" +
           this->share_results_[i].second + "\"}";
  out += "]}";
  return out;
}

std::string Standalone::community_json_() {
  return json::build_json([&](JsonObject o) {
    o["cooks"] = this->community_cooks_;
    o["updated"] = this->community_updated_;
    JsonArray g = o["groups"].to<JsonArray>();
    for (auto &x : this->community_) {
      JsonObject r = g.add<JsonObject>();
      r["cut"] = x.cut;
      r["line"] = x.line;
    }
  }).c_str();
}

// ---------------------------------------------------------------- plan

int Standalone::light_by_(uint32_t now_epoch, float *est_min) {
  if (this->s2_.serve_by == 0 || this->cook_ == nullptr) return 0;
  float est = NAN;  // the longest estimate among the food slots that have a weight (pre-cook or live)
  for (auto *p : this->cook_->probes()) {
    if (p->estimated_total && p->estimated_total->has_state() && !std::isnan(p->estimated_total->state) &&
        p->weight && p->weight->has_state() && p->weight->state > 0)
      est = std::isnan(est) ? p->estimated_total->state : std::max(est, p->estimated_total->state);
  }
  if (est_min) *est_min = est;
  if (std::isnan(est)) return 0;
  return int(this->s2_.serve_by) - int((est + this->s2_.rest_min) * 60.0f);
}

// ---------------------------------------------------------------- API: /local/history, journal, plan, share, community

std::string Standalone::api_cook_(const std::string &path, JsonDocument &in, bool authed, int &status) {
  auto err = [&](int code, const char *m) {
    status = code;
    return json::build_json([&](JsonObject o) { o["error"] = m; if (code == 401) o["pin"] = true; }).c_str();
  };
  if (path == "plan") {
    if (in["serve_by"].is<uint32_t>() || in["serve_by"].is<int>()) {
      uint32_t sb = in["serve_by"].as<uint32_t>();
      uint32_t t = epoch_now();
      if (sb != 0 && t != 0 && (sb < t - 3600 || sb > t + 7 * 86400)) return std::string(err(400, "Pick a time in the next week"));
      this->s2_.serve_by = sb;
    }
    if (in["rest_min"].is<int>()) {
      int r = in["rest_min"];
      if (r < 0 || r > 360) return std::string(err(400, "Rest between 0 and 360 minutes"));
      this->s2_.rest_min = uint16_t(r);
    }
    this->save_pending_ = true;
    return "{}";
  }
  if (path == "fuel") {
    static const char *const MODES[] = {"start", "check", "refill", "add", "end"};
    std::string m = in["mode"] | "";
    float pct = in["percent"] | NAN;
    int8_t mi = -1;
    for (int8_t i = 0; i < 5; i++) if (m == MODES[i]) mi = i;
    if (mi < 0 || std::isnan(pct) || pct < 0 || pct > 100) return std::string(err(400, "Unexpected charcoal entry"));
    this->fuel_mode_ = mi;
    this->fuel_pct_ = pct;
    return "{}";
  }
  if (path == "share/settings") {
    if (in["enabled"].is<bool>()) this->s2_.share_enabled = in["enabled"].as<bool>();
    if (in["auto"].is<bool>()) {
      bool a = in["auto"].as<bool>();
      if (a && !this->s2_.share_auto) this->s2_.auto_since = epoch_now();
      this->s2_.share_auto = a;
    }
    this->save_pending_ = true;
    return this->journal_json_(authed);
  }
  if (path == "share/withdraw") {
    int n = 0;
    for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
      JEntry &e = this->journal_[i];
      if (e.id && e.share == 1 && e.share_id[0]) {
        this->unshare_wait_ |= 1u << i;  // share_pump_ sends them, one at a time
        n++;
      }
    }
    return json::build_json([&](JsonObject o) { o["removing"] = n; }).c_str();
  }
  // journal/<id>[/delete], share/<id>[/decline]
  const bool is_j = path.rfind("journal/", 0) == 0, is_s = path.rfind("share/", 0) == 0;
  if (is_j || is_s) {
    std::string rest = path.substr(is_j ? 8 : 6);
    std::string idhex = rest.substr(0, rest.find('/')), sub = rest.find('/') == std::string::npos ? "" : rest.substr(rest.find('/') + 1);
    uint32_t id = strtoul(idhex.c_str(), nullptr, 16);
    for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
      JEntry &e = this->journal_[i];
      if (e.id == 0 || e.id != id) continue;
      if (is_j && sub == "delete") {
        e = JEntry{};
      } else if (is_j) {
        if (in["rating"].is<int>()) { int r = in["rating"]; e.rating = r >= 1 && r <= 5 ? uint8_t(r) : 0; }
        if (in["tags"].is<JsonArray>()) {
          uint16_t bits = 0;
          for (JsonVariant v : in["tags"].as<JsonArray>()) {
            bool known = false;
            for (size_t k = 0; k < N_TAGS; k++) if (v == TAGS[k]) { bits |= 1u << k; known = true; }
            if (!known) return std::string(err(400, "unknown tag"));
          }
          e.tags = bits;
        }
        if (in["notes"].is<const char *>()) {
          std::memset(e.notes, 0, sizeof(e.notes));
          std::string n = in["notes"].as<const char *>();
          size_t cut = std::min(n.size(), sizeof(e.notes) - 1);
          while (cut > 0 && cut < n.size() && (uint8_t(n[cut]) & 0xC0) == 0x80) cut--;  // not mid-character (UTF-8)
          std::memcpy(e.notes, n.data(), cut);
        }
      } else if (sub == "decline") {
        if (e.share == 0) e.share = 2;
      } else {
        if (!this->s2_.share_enabled) return std::string(err(409, "Turn on sharing first (Setup > Open Pitmaster)"));
        std::string why;
        if (!this->share_entry_(e, why)) return std::string(err(400, why.c_str()));
      }
      this->journal_dirty_ |= 1u << i;
      return this->journal_json_(authed);
    }
    return std::string(err(404, "no such cook"));
  }
  return std::string(err(404, "not found"));
}

}  // namespace standalone
}  // namespace esphome
