// The device page's cook replay (and the picture of a cook to share): each journal entry keeps its cook's curves and
// events, so it can be replayed later.
//  - events (lid opened and for how long, wrapped / unwrapped, stall began / ended, program steps, charcoal top-ups,
//    off the grill) are noted as they happen, in RAM (the last 64), from the controller's own entities ("Lid",
//    "Charcoal level", "Program status", each food slot's wrapped / stall / pulled);
//  - when a finished cook goes into the journal (add_cook), its pit and food curves (from the chart's 24 h history, at
//    most CURVE_LEN points) and its events are kept in flash beside the entry: one JCurve record per journal slot. A
//    cook from before this has none (the page then uses the chart's last 24 hours, if the cook is still in them);
//  - GET /local/journal/<id>/curve answers with them.
#include "standalone.h"

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <ctime>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "../cook_assistant/cook_assistant.h"

#ifdef USE_ESP32
#include <esp_heap_caps.h>
#endif

namespace esphome {
namespace standalone {

static const char *const TAG = "standalone";
static const char *const EVENT_KINDS[] = {"", "lid", "wrap", "unwrap", "stall_start", "stall_end", "step", "fuel", "pulled"};
static constexpr float FUEL_JUMP = 8.0f;  // the charcoal level this many points above the last: a top-up

static uint32_t epoch_now_() {
  time_t t = ::time(nullptr);
  return t > 1700000000 ? uint32_t(t) : 0;
}

void Standalone::note_event_(uint32_t t, uint8_t k, uint8_t slot, uint16_t v) {
  CookEvent &e = this->events_[this->ev_head_];
  e.t = t;
  e.k = k;
  e.slot = slot;
  e.v = v;
  this->ev_head_ = (this->ev_head_ + 1) % EVENT_RING;
  if (this->ev_count_ < EVENT_RING) this->ev_count_++;
}

// From the main loop, once a second: what changed since last time.
void Standalone::watch_events_(uint32_t now) {
  if (this->ev_polled_ != 0 && now - this->ev_polled_ < 1000) return;
  this->ev_polled_ = now ? now : 1;
  if (!this->ev_looked_) {  // the entities, by name (once: the yaml decides which there are)
    this->ev_looked_ = true;
#ifdef USE_BINARY_SENSOR
    for (auto *b : App.get_binary_sensors())
      if (b->name_equals(StringRef("Lid"))) { this->ev_lid_bs_ = b; break; }
#endif
#ifdef USE_SENSOR
    for (auto *s : App.get_sensors())
      if (s->name_equals(StringRef("Charcoal level"))) { this->ev_fuel_s_ = s; break; }
#endif
#ifdef USE_TEXT_SENSOR
    for (auto *s : App.get_text_sensors())
      if (s->name_equals(StringRef("Program status"))) { this->ev_prog_ts_ = s; break; }
#endif
  }
  const uint32_t t = epoch_now_();
  if (t == 0) return;  // no clock yet: nothing to place in time
  const bool primed = this->ev_primed_;
  this->ev_primed_ = true;  // the first look only learns how things are
  // The lid: when it opened, and (once shut) for how long.
#ifdef USE_BINARY_SENSOR
  if (this->ev_lid_bs_ != nullptr && this->ev_lid_bs_->has_state()) {
    const int8_t open = this->ev_lid_bs_->state ? 1 : 0;
    if (primed && this->ev_lid_ == 0 && open) {
      this->ev_lid_at_ = this->ev_head_;
      this->note_event_(t, 1, 0, 0);
    } else if (this->ev_lid_ == 1 && !open && this->ev_lid_at_ < EVENT_RING) {
      CookEvent &e = this->events_[this->ev_lid_at_];
      if (e.k == 1 && t >= e.t) e.v = uint16_t(std::min<uint32_t>(t - e.t, 65535));
      this->ev_lid_at_ = SIZE_MAX;
    }
    this->ev_lid_ = open;
  }
#endif
  // Each food: wrapped, stall, off the grill.
  if (this->cook_ != nullptr) {
    uint8_t wrap = 0, stall = 0, pulled = 0;
    const auto &ps = this->cook_->probes();
    for (size_t i = 0; i < ps.size() && i < 8; i++) {
      const auto *p = ps[i];
      if (p->wrapped != nullptr && p->wrapped->state) wrap |= 1u << i;
      if (p->stall != nullptr && p->stall->has_state() && p->stall->state) stall |= 1u << i;
      if (p->pulled != nullptr && p->pulled->state) pulled |= 1u << i;
    }
    if (primed) {
      for (size_t i = 0; i < ps.size() && i < 8; i++) {
        const uint8_t bit = 1u << i, slot = uint8_t(i + 1);
        if ((wrap ^ this->ev_wrap_) & bit) this->note_event_(t, (wrap & bit) ? 2 : 3, slot, 0);
        if ((stall ^ this->ev_stall_) & bit) this->note_event_(t, (stall & bit) ? 4 : 5, slot, 0);
        if ((pulled & bit) && !(this->ev_pulled_ & bit)) this->note_event_(t, 8, slot, 0);
      }
    }
    this->ev_wrap_ = wrap;
    this->ev_stall_ = stall;
    this->ev_pulled_ = pulled;
  }
  // The program's step ("Step 2/3, ..." in Program status).
#ifdef USE_TEXT_SENSOR
  if (this->ev_prog_ts_ != nullptr && this->ev_prog_ts_->has_state()) {
    const std::string &st = this->ev_prog_ts_->state;
    const int step = st.rfind("Step ", 0) == 0 ? std::atoi(st.c_str() + 5) : -1;
    if (primed && step > 0 && step != this->ev_step_) this->note_event_(t, 6, 0, uint16_t(step));
    this->ev_step_ = step;
  }
#endif
  // Charcoal: the level jumping up is a top-up (from this page, Home Assistant or the grill's own log).
#ifdef USE_SENSOR
  if (this->ev_fuel_s_ != nullptr && this->ev_fuel_s_->has_state() && std::isfinite(this->ev_fuel_s_->state)) {
    const float lvl = this->ev_fuel_s_->state;
    if (primed && std::isfinite(this->ev_fuel_) && lvl - this->ev_fuel_ >= FUEL_JUMP)
      this->note_event_(t, 7, 0, uint16_t(std::lround(std::max(0.0f, std::min(100.0f, lvl)))));
    this->ev_fuel_ = lvl;
  }
#endif
}

// At setup, after the journal: the kept curves, from flash into RAM (PSRAM; only those that still belong to their
// entry). Read here, in the main loop, never from the web page's task.
void Standalone::setup_replay_() {
  for (size_t i = 0; i < JOURNAL_SLOTS; i++)
    this->cpref_[i] = global_preferences->make_preference<JCurve>(fnv1_hash("standalone_curve_v1_") + i, true);
#ifdef USE_ESP32
  this->curves_ = static_cast<JCurve *>(heap_caps_calloc(JOURNAL_SLOTS, sizeof(JCurve), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
#endif
  if (this->curves_ == nullptr)
    this->curves_ = static_cast<JCurve *>(calloc(JOURNAL_SLOTS, sizeof(JCurve)));  // NOLINT
  if (this->curves_ == nullptr) {
    ESP_LOGW(TAG, "No memory for cook replays");
    return;
  }
  for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
    JCurve c{};
    this->curves_[i] = this->journal_[i].id != 0 && this->cpref_[i].load(&c) && c.id == this->journal_[i].id ? c : JCurve{};
  }
}

// A finished cook just went into journal slot `slot` (add_cook, under lock_): keep its curves and events there.
void Standalone::keep_curve_(size_t slot, const JEntry &e, const std::string &probe_key) {
  if (this->curves_ == nullptr) return;
  JCurve &c = this->curves_[slot];
  c = JCurve{};
  this->curve_dirty_ |= 1u << slot;  // saved (or cleared) from the main loop
  if (e.ended == 0 || std::isnan(e.total_h) || e.total_h <= 0 || this->hist_ == nullptr) return;
  c.id = e.id;
  c.unit_f = this->fahrenheit_ ? 1 : 0;
  int series = -1;
  if (this->cook_ != nullptr) {
    const auto &ps = this->cook_->probes();
    for (size_t i = 0; i < ps.size(); i++)
      if (ps[i]->key == probe_key) {
        if (i + 2 < HIST_SERIES) series = int(i + 2);
        if (i < 9) c.slot = uint8_t(i + 1);
      }
  }
  const uint32_t start = e.ended - uint32_t(std::lround(std::min(e.total_h, 24.0f) * 3600.0f));
  {
    std::lock_guard<std::mutex> g(this->hist_lock_);
    // One sample a minute; the newest is just before hist_head_, taken (millis() - hist_last_) ago.
    const uint32_t newest = e.ended - std::min<uint32_t>((millis() - this->hist_last_) / 1000, e.ended);
    if (this->hist_count_ > 0 && newest > start) {
      const size_t want = std::min<size_t>(this->hist_count_, (newest - start) / 60 + 1);
      const size_t step = std::max<size_t>(1, (want + CURVE_LEN - 1) / CURVE_LEN);
      const size_t n = std::min<size_t>(CURVE_LEN, (want + step - 1) / step);
      c.start = newest - uint32_t((want - 1) * 60);
      c.step_s = uint16_t(step * 60);
      c.n = uint8_t(n);
      for (size_t j = 0; j < n; j++) {
        const size_t ago = (want - 1) - j * step;  // samples before the newest
        const size_t idx = (this->hist_head_ + HIST_LEN - 1 - ago % HIST_LEN) % HIST_LEN;
        c.pit[j] = this->hist_[idx];
        c.food[j] = series >= 0 ? this->hist_[size_t(series) * HIST_LEN + idx] : INT16_MIN;
      }
    }
  }
  // Its events (only this food's wrap, stall and pull), oldest first.
  for (size_t k = 0; k < this->ev_count_ && c.ne < CURVE_EVENTS; k++) {
    const CookEvent &ev = this->events_[(this->ev_head_ + EVENT_RING - this->ev_count_ + k) % EVENT_RING];
    if (ev.t < start || ev.t > e.ended + 60) continue;
    if (ev.slot != 0 && c.slot != 0 && ev.slot != c.slot) continue;
    c.ev[c.ne++] = ev;
  }
  ESP_LOGI(TAG, "Journal: kept the cook's curves (%u points) and %u events", unsigned(c.n), unsigned(c.ne));
}

// GET /local/journal/<id>/curve (API task, under lock_).
std::string Standalone::curve_json_(const std::string &id_hex, int &status) {
  const uint32_t id = strtoul(id_hex.c_str(), nullptr, 16);
  for (size_t i = 0; i < JOURNAL_SLOTS; i++) {
    if (id == 0 || this->journal_[i].id != id) continue;
    char b[48];
    std::snprintf(b, sizeof(b), "{\"id\":\"%08x\"", unsigned(id));
    std::string out = b;
    const JCurve *c = this->curves_ != nullptr && this->curves_[i].id == id ? &this->curves_[i] : nullptr;
    if (c == nullptr || c->n == 0) return out + ",\"pit\":[],\"food\":[],\"events\":[]}";
    std::snprintf(b, sizeof(b), ",\"start\":%u,\"step_s\":%u,\"slot\":%u", unsigned(c->start), unsigned(c->step_s), unsigned(c->slot));
    out += b;
    out += c->unit_f ? ",\"unit\":\"°F\"" : ",\"unit\":\"°C\"";
    for (int s = 0; s < 2; s++) {
      out += s ? "],\"food\":[" : ",\"pit\":[";
      const int16_t *v = s ? c->food : c->pit;
      for (size_t j = 0; j < c->n && j < CURVE_LEN; j++) {
        if (j) out += ",";
        if (v[j] == INT16_MIN) out += "null";
        else { std::snprintf(b, sizeof(b), "%.1f", v[j] / 10.0); out += b; }
      }
    }
    out += "],\"events\":[";
    for (size_t k = 0; k < c->ne && k < CURVE_EVENTS; k++) {
      const CookEvent &ev = c->ev[k];
      if (ev.k == 0 || ev.k >= sizeof(EVENT_KINDS) / sizeof(EVENT_KINDS[0])) continue;
      std::snprintf(b, sizeof(b), "%s{\"t\":%u,\"k\":\"%s\"", out.back() == '[' ? "" : ",", unsigned(ev.t), EVENT_KINDS[ev.k]);
      out += b;
      if (ev.slot) { std::snprintf(b, sizeof(b), ",\"slot\":%u", unsigned(ev.slot)); out += b; }
      if (ev.v) { std::snprintf(b, sizeof(b), ev.k == 1 ? ",\"d\":%u" : ",\"v\":%u", unsigned(ev.v)); out += b; }
      out += "}";
    }
    return out + "]}";
  }
  status = 404;
  return "{\"error\":\"no such cook\"}";
}

}  // namespace standalone
}  // namespace esphome
