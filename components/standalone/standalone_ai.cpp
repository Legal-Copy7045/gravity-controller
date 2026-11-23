// Stage 3 of running without Home Assistant: the AI on the controller, with the owner's own key (docs/standalone.md).
//  - providers: Google Gemini, Anthropic Claude, OpenAI; the key is write-only (Settings::ai_key);
//  - the AI pitmaster: a second opinion on the live cook (on request, and every 30 min during a cook if turned on);
//  - Plan with AI: describe the cook; it suggests timings and a cook program the controller can load;
//  - What's cooking: a photo of the package label; it reads the cut and weight, and sets them on a Food slot.
// Calls run in their own worker lane (standalone.cpp), so a slow answer never holds up a notification.
#include "standalone.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <ctime>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "../cook_assistant/cook_assistant.h"
#ifdef USE_API
#include "esphome/components/api/api_server.h"
#endif
#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif

namespace esphome {
namespace standalone {

static const char *const TAG = "standalone.ai";
// Defaults per provider; the device page can change the model. Claude: the current Opus (the default model).
static const char *default_model(const std::string &p) {
  return p == "claude" ? "claude-opus-5-5" : p == "openai" ? "gpt-4.1-mini" : "gemini-flash-lite-latest";
}
static const char *const CUTS_LIST = "Pork shoulder, Brisket, Ribs, Beef roast, Poultry, Sausage, Fish, Auto";
static const char *const PROGRAM_HELP =
    "Cook programs are text: an optional first line 'name: <name>', then steps separated by ';'. A step is 'pit <temp>' "
    "(set the pit target) or 'hold <temp>' (set it and stay: use for the last step), optionally with 'notify \"text\"', "
    "optionally followed by 'until' and conditions joined by 'or': 'food<N> >= <temp>' or 'food<N> >= <temp> for <M>m' "
    "(N = food slot 1-6), 'food<N> done' (reached its own target), 'after <N>h' or 'after <N>m' (time in this step), "
    "'at HH:MM'. Write temperatures with the unit, e.g. 250F or 120C. Example: name: Pork shoulder; pit 250F until "
    "food1 >= 165F for 30m; pit 275F until food1 >= 203F; hold 200F notify \"Pork is done - rest it\"";

static std::string now_local() {
  time_t t = ::time(nullptr);
  if (t < 1700000000) return "unknown (clock not set)";
  struct tm lt;
  localtime_r(&t, &lt);
  char b[40];
  strftime(b, sizeof(b), "%a %d %b %H:%M", &lt);
  return b;
}

void Standalone::setup_ai_() {
  this->aipref_ = global_preferences->make_preference<AiSettings>(fnv1_hash("standalone_ai_v1"), true);
  AiSettings a{};
  if (this->aipref_.load(&a) && a.version == 1)
    this->ai_ = a;
}

std::string Standalone::ai_model_() const {
  return this->s_.ai_model[0] ? std::string(this->s_.ai_model) : std::string(default_model(this->s_.ai_provider));
}

bool Standalone::ai_ready_() const { return this->s_.ai_provider[0] && this->s_.ai_key[0]; }

// The cook as the AI sees it: live state, this grill's past cooks, the journal, shared averages, the plan.
std::string Standalone::ai_context_() {
  std::string c = "Now: " + now_local() + ". Temperatures in " + (this->fahrenheit_ ? "F" : "C") + ".\n";
#ifdef USE_SENSOR
  if (this->wx_temp_ && this->wx_temp_->has_state())
  {
    char b[64];
    std::snprintf(b, sizeof(b), "Outside: %.0f", this->wx_temp_->state);
    c += b;
    if (this->wx_wind_ && this->wx_wind_->has_state()) {
      std::snprintf(b, sizeof(b), ", wind %.0f %s", this->wx_wind_->state, this->wind_unit_);
      c += b;
    }
    c += ".\n";
  }
#endif
  if (this->cook_ != nullptr) {
    c += "Live state: " + this->cook_->state_json() + "\n";
    std::string h = this->cook_->history_json();
    if (h.size() > 4000) h = h.substr(0, 4000) + "...";
    c += "This grill's past cooks (learned): " + h + "\n";
  }
  std::string j;
  int n = 0;
  std::vector<const JEntry *> list;
  for (auto &e : this->journal_) if (e.id) list.push_back(&e);
  std::sort(list.begin(), list.end(), [](const JEntry *a, const JEntry *b) { return a->seq > b->seq; });
  for (const JEntry *e : list) {
    if (n++ >= 6) break;
    char b[200];
    std::snprintf(b, sizeof(b), "%s %.1f kg, %.1f h total, stall %.1f h, %d stars, notes: ", e->profile,
                  std::isnan(e->weight_kg) ? 0.0f : e->weight_kg, e->total_h, std::isnan(e->stall_h) ? 0.0f : e->stall_h,
                  e->rating);
    j += std::string("- ") + b + e->notes + "\n";
  }
  if (!j.empty()) c += "The cook's journal (recent cooks; low stars with 'dry' means cook lower or wrap earlier):\n" + j;
  std::string like;
  for (auto &g : this->community_) {
    if (like.size() > 1200) break;
    for (auto *p : this->cook_ ? this->cook_->probes() : std::vector<cook_assistant::FoodProbe *>{})
      if (p->profile && p->profile->has_state() && p->profile->current_option() == g.cut) { like += "- " + g.line + "\n"; break; }
  }
  if (!like.empty()) c += "Shared cooks from other Gravity 980 owners (Open Pitmaster averages; weigh by number of cooks):\n" + like;
  if (this->s2_.serve_by) {
    time_t sb = this->s2_.serve_by;
    struct tm lt;
    localtime_r(&sb, &lt);
    char b[32];
    strftime(b, sizeof(b), "%a %H:%M", &lt);
    c += std::string("Planned: serve at ") + b + " after a " + std::to_string(this->s2_.rest_min) + " min rest.\n";
  }
  return c;
}

bool Standalone::ai_ask_(const std::string &kind, const std::string &system, const std::string &user,
                         const std::string &image_b64, std::string &why) {
  if (!this->ai_ready_()) { why = "Set up the AI first (Setup > AI: provider and key)"; return false; }
  if (this->ai_busy_ & (1u << this->ai_kind_(kind))) { why = "Already asking: give it a moment"; return false; }
  // A cap on the owner's credits, whatever else goes wrong: 40 questions a day.
  const uint32_t day = ::time(nullptr) > 1700000000 ? uint32_t(::time(nullptr) / 86400) : millis() / 86400000u;
  if (day != this->ai_day_) { this->ai_day_ = day; this->ai_calls_today_ = 0; }
  if (this->ai_calls_today_ >= 40) { why = "That's 40 AI questions today, the daily limit: it resets tomorrow"; return false; }
  this->ai_calls_today_++;
  const std::string p = this->s_.ai_provider, model = this->ai_model_();
  Job j;
  j.what = "ai:" + kind;
  j.method = "POST";
  j.content_type = "application/json";
  j.lane = 1;
  if (p == "claude") {
    j.url = "https://api.anthropic.com/v1/messages";
    j.headers = {{"x-api-key", this->s_.ai_key}, {"anthropic-version", "2026-10-21"}};
    const bool fb = model == "claude-opus-5-5" || model == "claude-sonnet-5-5" || model == "claude-fable-5-2";
    if (fb) j.headers.push_back({"anthropic-beta", "server-side-fallback-2026-07-01"});
    j.body = json::build_json([&](JsonObject o) {
      o["model"] = model;
      o["max_tokens"] = 8000;
      o["system"] = system;
      o["output_config"]["effort"] = kind == "label" || kind == "test" ? "low" : "medium";
      if (fb) o["fallbacks"] = "default";  // a safety decline is retried on a fallback model, in the same call
      JsonArray content = o["messages"].to<JsonArray>().add<JsonObject>()["content"].to<JsonArray>();
      o["messages"][0]["role"] = "user";
      if (!image_b64.empty()) {
        JsonObject img = content.add<JsonObject>();
        img["type"] = "image";
        img["source"]["type"] = "base64";
        img["source"]["media_type"] = "image/jpeg";
        img["source"]["data"] = image_b64;
      }
      JsonObject t = content.add<JsonObject>();
      t["type"] = "text";
      t["text"] = user;
    }).c_str();
  } else if (p == "openai") {
    j.url = "https://api.openai.com/v1/chat/completions";
    j.headers = {{"Authorization", std::string("Bearer ") + this->s_.ai_key}};
    j.body = json::build_json([&](JsonObject o) {
      o["model"] = model;
      o["response_format"]["type"] = "json_object";
      JsonArray m = o["messages"].to<JsonArray>();
      JsonObject sys = m.add<JsonObject>();
      sys["role"] = "system";
      sys["content"] = system;
      JsonObject u = m.add<JsonObject>();
      u["role"] = "user";
      JsonArray content = u["content"].to<JsonArray>();
      JsonObject t = content.add<JsonObject>();
      t["type"] = "text";
      t["text"] = user;
      if (!image_b64.empty()) {
        JsonObject img = content.add<JsonObject>();
        img["type"] = "image_url";
        img["image_url"]["url"] = "data:image/jpeg;base64," + image_b64;
      }
    }).c_str();
  } else {  // gemini
    j.url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent";
    j.headers = {{"x-goog-api-key", this->s_.ai_key}};
    j.body = json::build_json([&](JsonObject o) {
      o["systemInstruction"]["parts"].to<JsonArray>().add<JsonObject>()["text"] = system;
      o["generationConfig"]["responseMimeType"] = "application/json";
      JsonObject c = o["contents"].to<JsonArray>().add<JsonObject>();
      c["role"] = "user";
      JsonArray parts = c["parts"].to<JsonArray>();
      if (!image_b64.empty()) {
        JsonObject img = parts.add<JsonObject>();
        img["inline_data"]["mime_type"] = "image/jpeg";
        img["inline_data"]["data"] = image_b64;
      }
      parts.add<JsonObject>()["text"] = user;
    }).c_str();
  }
  this->ai_busy_ |= 1u << this->ai_kind_(kind);
  this->ai_error_.clear();
  this->queue_(std::move(j));
  ESP_LOGI(TAG, "Asking %s (%s): %s", p.c_str(), model.c_str(), kind.c_str());
  return true;
}

int Standalone::ai_kind_(const std::string &k) const {
  return k == "advise" ? 0 : k == "plan" ? 1 : k == "label" ? 2 : 3;
}

// The provider's answer -> the JSON object the prompt asked for (or an error the page can show).
void Standalone::ai_done_(const std::string &what, int code, const std::string &body) {
  const std::string kind = what.substr(3);
  this->ai_busy_ &= ~(1u << this->ai_kind_(kind));
  const std::string p = this->s_.ai_provider;
  JsonDocument d = json::parse_json(body);
  std::string text, err;
  if (code < 200 || code >= 300) {
    const char *m = d["error"]["message"] | (const char *) nullptr;
    err = code == 0 ? "Couldn't reach the AI (no internet?)"
                    : std::string("The AI said ") + std::to_string(code) + (m ? std::string(": ") + m : "");
  } else if (p == "claude") {
    if (std::string(d["stop_reason"] | "") == "refusal") err = "The AI declined to answer this one";
    for (JsonObject b : d["content"].as<JsonArray>())
      if (std::string(b["type"] | "") == "text") text += b["text"] | "";
  } else if (p == "openai") {
    text = d["choices"][0]["message"]["content"] | "";
  } else {
    for (JsonObject part : d["candidates"][0]["content"]["parts"].as<JsonArray>()) text += part["text"] | "";
  }
  std::string out;
  if (err.empty()) {
    size_t a = text.find('{'), b = text.rfind('}');
    if (a == std::string::npos || b == std::string::npos || b < a) err = "The AI's answer wasn't readable; try again";
    else {
      JsonDocument r = json::parse_json(text.substr(a, b - a + 1));
      if (!r.is<JsonObject>()) err = "The AI's answer wasn't readable; try again";
      else {
        r["at"] = ::time(nullptr) > 1700000000 ? uint32_t(::time(nullptr)) : 0;
        serializeJson(r, out);
      }
    }
  }
  if (!err.empty()) {
    this->ai_error_ = err;
    ESP_LOGW(TAG, "%s: %s", kind.c_str(), err.c_str());
    if (kind == "test") this->ai_test_ = err;
    return;
  }
  if (kind == "advise") this->ai_advice_ = out;
  else if (kind == "plan") this->ai_plan_ = out;
  else if (kind == "label") this->ai_labels_ = out;
  else this->ai_test_ = "Working (" + p + ", " + this->ai_model_() + ")";
  ESP_LOGI(TAG, "%s: answered", kind.c_str());
}

// The AI only works on a cook: one underway, or one planned (serve-by within the next two days).
bool Standalone::ai_cook_on_() {
  if (this->cook_ != nullptr && this->cook_->cook_active()) return true;
  const time_t t = ::time(nullptr);
  return this->s2_.serve_by && t > 1700000000 && this->s2_.serve_by > uint32_t(t) && this->s2_.serve_by - uint32_t(t) < 48 * 3600;
}

std::string Standalone::ai_advise_() {
  std::string why;
  if (!this->ai_cook_on_()) return "Nothing's cooking or planned: start a cook, or set Serve by under Plan a cook";
  this->ai_ask_("advise",
                "You are an experienced pitmaster giving a second opinion on a live cook on a Char-Griller Gravity 980 "
                "charcoal smoker, using the controller's data. Be specific and practical; don't repeat the numbers back. "
                "Reply ONLY with a JSON object: {\"summary\": one or two sentences on how the cook is going, "
                "\"suggestion\": the single most useful thing to do next (or empty), \"finish_estimate_min\": minutes "
                "until the food is done or null, \"recommendations\": up to 4 of {\"when\": \"now\" or a temperature or "
                "a clock time, \"title\": short, \"detail\": one sentence}}.",
                this->ai_context_(), "", why);
  return why;
}

void Standalone::loop_ai_(uint32_t now) {
  // A food slot set from a package label, and a program from Plan with AI: applied here, in the main loop.
  int probe = 0;
  std::string cut, prog;
  float lb = NAN;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    probe = this->ai_assign_probe_;
    cut = this->ai_assign_cut_;
    lb = this->ai_assign_lb_;
    this->ai_assign_probe_ = 0;
    prog.swap(this->ai_program_);
  }
  if (probe >= 1 && this->cook_ != nullptr) {
    const auto &ps = this->cook_->probes();
    if (size_t(probe) <= ps.size()) {
      auto *p = ps[probe - 1];
      if (p->profile && !cut.empty()) p->profile->make_call().set_option(cut).perform();
      if (p->weight && !std::isnan(lb)) {
        float w = this->fahrenheit_ ? lb : lb * 0.4536f;  // the weight number is in lb with °F, kg with °C
        p->weight->make_call().set_value(std::round(w * 10) / 10).perform();
      }
    }
  }
  if (!prog.empty() && this->cook_ != nullptr && !this->cook_->load_program(prog)) {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    this->ai_error_ = "The controller couldn't read the AI's program; nothing was loaded";
  }
  // The AI pitmaster every N minutes during a cook (when turned on).
  if (this->ai_.auto_advise && this->ai_ready_() && this->cook_ != nullptr && this->cook_->cook_active() &&
      (this->ai_last_auto_ == 0 || now - this->ai_last_auto_ > uint32_t(this->ai_.interval_min) * 60000)) {
    this->ai_last_auto_ = now ? now : 1;  // not "now | 1": 1 ms ahead, now - it wraps
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    this->ai_advise_();
  }
}

std::string Standalone::ai_json_() {
  std::string out = json::build_json([&](JsonObject o) {
    o["provider"] = this->s_.ai_provider;
    o["model"] = this->s_.ai_provider[0] ? this->ai_model_() : "";
    o["default_model"] = default_model(this->s_.ai_provider);
    o["key"] = this->s_.ai_key[0] != 0;
    o["auto"] = this->ai_.auto_advise != 0;
    o["interval"] = this->ai_.interval_min;
    JsonObject b = o["busy"].to<JsonObject>();
    b["advise"] = (this->ai_busy_ & 1) != 0;
    b["plan"] = (this->ai_busy_ & 2) != 0;
    b["label"] = (this->ai_busy_ & 4) != 0;
    b["test"] = (this->ai_busy_ & 8) != 0;
    o["cook_on"] = this->ai_cook_on_();
    o["calls_today"] = this->ai_calls_today_;
    o["daily_limit"] = 40;
    o["error"] = this->ai_error_;
    o["test"] = this->ai_test_;
  }).c_str();
  out.pop_back();
  auto add = [&](const char *k, const std::string &v) { if (!v.empty()) out += std::string(",\"") + k + "\":" + v; };
  add("advice", this->ai_advice_);
  add("plan", this->ai_plan_);
  add("labels", this->ai_labels_);
  return out + "}";
}

std::string Standalone::api_ai_(const std::string &path, JsonDocument &in, int &status) {
  auto err = [&](int code, const std::string &m) {
    status = code;
    return std::string(json::build_json([&](JsonObject o) { o["error"] = m; }).c_str());
  };
  std::string why;
  if (path == "ai/settings") {
    if (in["provider"].is<const char *>()) {
      std::string p = in["provider"].as<const char *>();
      if (!p.empty() && p != "gemini" && p != "claude" && p != "openai") return err(400, "Unknown AI provider");
      if (p != this->s_.ai_provider) { std::memset(this->s_.ai_model, 0, sizeof(this->s_.ai_model)); this->ai_test_.clear(); }
      std::memset(this->s_.ai_provider, 0, sizeof(this->s_.ai_provider));
      std::strncpy(this->s_.ai_provider, p.c_str(), sizeof(this->s_.ai_provider) - 1);
    }
    if (in["model"].is<const char *>()) {
      std::string m = in["model"].as<const char *>();
      for (char ch : m) if (!(isalnum(ch) || ch == '-' || ch == '.' || ch == '_')) return err(400, "Unexpected character in the model name");
      std::memset(this->s_.ai_model, 0, sizeof(this->s_.ai_model));
      std::strncpy(this->s_.ai_model, m.c_str(), sizeof(this->s_.ai_model) - 1);
    }
    if (in["auto"].is<bool>()) this->ai_.auto_advise = in["auto"].as<bool>();
    this->save_pending_ = true;
    this->ai_save_ = true;
    return this->ai_json_();
  }
  if (path == "ai/test") {
    if (!this->ai_ask_("test", "Reply ONLY with the JSON object {\"ok\": true}.", "Are you there?", "", why)) return err(400, why);
    return this->ai_json_();
  }
  if (path == "ai/advise") {
    why = this->ai_advise_();
    if (!why.empty()) return err(400, why);
    return this->ai_json_();
  }
  if (path == "ai/plan") {
    std::string req = in["request"] | "";
    if (req.empty() || req.size() > 600) return err(400, "Describe the cook (up to 600 characters)");
    if (!this->ai_ask_("plan",
                       std::string("You are an experienced pitmaster planning a cook on a Char-Griller Gravity 980 charcoal "
                                   "smoker. Use this grill's past cooks and the journal when they're relevant. ") +
                           PROGRAM_HELP +
                           " Reply ONLY with a JSON object: {\"summary\": two or three sentences, \"light_at\": the "
                           "clock time to light the grill or null, \"steps\": up to 6 of {\"when\", \"title\", \"detail\"}, "
                           "\"program\": a cook program for this cook in the syntax above, or null}.",
                       "The cook: " + req + "\n" + this->ai_context_(), "", why))
      return err(400, why);
    return this->ai_json_();
  }
  if (path == "ai/label") {
    std::string img = in["image"] | "";
    if (img.size() < 100 || img.size() > 380000) return err(400, "Send one photo (the page shrinks it first)");
    for (size_t i = 0; i < img.size(); i += 97)  // a cheap check that it's base64
      if (!(isalnum(img[i]) || img[i] == '+' || img[i] == '/' || img[i] == '=')) return err(400, "Not a photo");
    if (!this->ai_ask_("label",
                       std::string("You read meat and fish package labels for a smoker cook. Identify every distinct "
                                   "item. Reply ONLY with a JSON object: {\"items\": [{\"name\": short description, "
                                   "\"profile\": one of ") + CUTS_LIST + ", \"weight_lb\": number or null}]}.",
                       "What is in this photo?", img, why))
      return err(400, why);
    return this->ai_json_();
  }
  if (path == "ai/assign") {
    int idx = in["index"] | -1, probe = in["probe"] | 0;
    JsonDocument l = json::parse_json(this->ai_labels_);
    JsonObject it = l["items"][idx];
    if (it.isNull() || probe < 1 || probe > 6) return err(400, "Pick an item and a food slot");
    this->ai_assign_cut_ = it["profile"] | "";
    this->ai_assign_lb_ = it["weight_lb"].is<float>() ? it["weight_lb"].as<float>() : NAN;
    this->ai_assign_probe_ = probe;
    return this->ai_json_();
  }
  if (path == "ai/load-program") {
    JsonDocument pl = json::parse_json(this->ai_plan_);
    std::string prog = pl["program"] | "";
    if (prog.empty()) return err(400, "This plan has no program");
    this->ai_program_ = prog;
    return this->ai_json_();
  }
  return err(404, "not found");
}

// ---------------------------------------------------------------- Home Assistant dropped the controller
// Home Assistant normally reconnects by itself. If it has used this controller and hasn't been back for 10 minutes,
// reconnect Wi-Fi (Home Assistant notices the controller announcing itself again); every 30 minutes after that, again.
// After an hour, restart the controller once, never during a cook, and not again until Home Assistant has been back.
// A controller that has never seen Home Assistant (standalone) is left alone.
void Standalone::loop_ha_watch_(uint32_t now) {
#ifdef USE_API
  if (api::global_api_server == nullptr) return;
  if (!this->ha_loaded_) {
    this->ha_loaded_ = true;
    this->ha_pref_ = global_preferences->make_preference<uint8_t>(fnv1_hash("standalone_ha_watch_v1"));
    if (!this->ha_pref_.load(&this->ha_state_)) this->ha_state_ = 0;
  }
  if (api::global_api_server->is_connected()) {
    if (this->ha_state_ != 1) { this->ha_state_ = 1; this->ha_pref_.save(&this->ha_state_); }
    this->ha_lost_at_ = this->ha_bounced_at_ = 0;
    return;
  }
  if (!(this->ha_state_ & 1) || now < 120000) return;  // never used with Home Assistant, or just started
  if (this->ha_lost_at_ == 0) { this->ha_lost_at_ = now ? now : 1; return; }
  const uint32_t lost = now - this->ha_lost_at_;
#ifdef USE_WIFI
  if (lost > 10 * 60000 && (this->ha_bounced_at_ == 0 || now - this->ha_bounced_at_ > 30 * 60000) &&
      wifi::global_wifi_component != nullptr && wifi::global_wifi_component->is_connected()) {
    this->ha_bounced_at_ = now ? now : 1;  // not "now | 1": 1 ms ahead, now - it wraps
    ESP_LOGW(TAG, "Home Assistant hasn't reconnected for %u min: reconnecting Wi-Fi", unsigned(lost / 60000));
    wifi::global_wifi_component->disable();
    this->set_timeout("ha_wifi_back", 3000, []() { wifi::global_wifi_component->enable(); });
  }
#endif
  if (lost > 60 * 60000 && !(this->ha_state_ & 2) && !(this->cook_ != nullptr && this->cook_->cook_active())) {
    this->ha_state_ |= 2;
    this->ha_pref_.save(&this->ha_state_);
    global_preferences->sync();
    ESP_LOGW(TAG, "Home Assistant hasn't reconnected for an hour: restarting once");
    this->set_timeout("ha_reboot", 1000, []() { App.safe_reboot(); });
  }
#endif
}

}  // namespace standalone
}  // namespace esphome

