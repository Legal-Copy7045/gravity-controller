#include "standalone.h"

#include <cmath>
#include <cstring>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#include "esphome/components/json/json_util.h"
#include "esphome/components/web_server_base/web_server_base.h"

#ifdef USE_API
#include "esphome/components/api/api_server.h"
#endif
#include "esphome/components/network/util.h"
#ifdef USE_TIME_TIMEZONE
#include "esphome/components/time/posix_tz.h"
#endif
#include "../cook_assistant/cook_assistant.h"

#ifdef USE_ESP32
#include <esp_crt_bundle.h>
#include <esp_http_client.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#endif

namespace esphome {
namespace standalone {

static const char *const TAG = "standalone";
static const char *const TOKEN_HEADER = "X-Smoker-Token";

// ---------------------------------------------------------------- the web handler (runs in the httpd task)

class Handler : public AsyncWebHandler {
 public:
  explicit Handler(Standalone *p) : p_(p) {}

  bool canHandle(AsyncWebServerRequest *req) const override {
    char buf[AsyncWebServerRequest::URL_BUF_SIZE];
    StringRef url = req->url_to(buf);
    if (url.size() >= 7 && std::strncmp(url.c_str(), "/local/", 7) == 0) {
      this->body_.clear();
      return true;
    }
    // Any change through the device page (ESPHome's REST POSTs, the settings pages) needs the PIN once one is set.
    // Reading (GET: the page, states, the live event stream) stays open on the local network.
    if (req->method() == HTTP_GET || req->method() == HTTP_HEAD || req->method() == HTTP_OPTIONS)
      return false;
    if (!this->p_->pin_set())
      return false;
    return !this->p_->write_allowed(token_(req));
  }

  void handleBody(AsyncWebServerRequest *req, uint8_t *data, size_t len, size_t index, size_t total) override {
    if (index == 0)
      this->body_.clear();
    if (this->body_.size() + len <= 4096)
      this->body_.append(reinterpret_cast<const char *>(data), len);
  }

  void handleRequest(AsyncWebServerRequest *req) override {
    char buf[AsyncWebServerRequest::URL_BUF_SIZE];
    StringRef url = req->url_to(buf);
    if (!(url.size() >= 7 && std::strncmp(url.c_str(), "/local/", 7) == 0)) {
      req->send(401, "application/json", "{\"error\":\"Enter the PIN to make changes\",\"pin\":true}");
      return;
    }
    const char *m = req->method() == HTTP_GET ? "GET" : req->method() == HTTP_POST ? "POST" : "OTHER";
    int status = 200;
    std::string path(url.c_str() + 7);
    if (req->hasArg("hours"))
      path += "?hours=" + req->arg("hours");
    std::string out = this->p_->api(m, path, this->body_, token_(req), status);
    this->body_.clear();
    auto *res = req->beginResponse(status, "application/json", out);
    res->addHeader("Cache-Control", "no-store");
    req->send(res);
  }

 protected:
  static std::string token_(AsyncWebServerRequest *req) {
    auto h = req->get_header(TOKEN_HEADER);
    return h.has_value() ? h.value() : std::string();
  }
  Standalone *p_;
  mutable std::string body_;
};

// ---------------------------------------------------------------- setup / loop

float Standalone::get_setup_priority() const { return setup_priority::WIFI + 1.0f; }

static void fill_random(uint8_t *b, size_t n) {
#ifdef USE_ESP32
  esp_fill_random(b, n);  // hardware RNG (true random with the radio on)
#else
  for (size_t i = 0; i < n; i++) b[i] = uint8_t(random_uint32());
#endif
}

void Standalone::setup() {
  this->pref_ = global_preferences->make_preference<Settings>(fnv1_hash("standalone_settings_v1"), true);
  this->pin_pref_ = global_preferences->make_preference<pinauth::Stored>(fnv1_hash("standalone_pin_v1"), true);
  Settings loaded{};
  if (this->pref_.load(&loaded) && loaded.version == 1)
    this->s_ = loaded;
  this->guard_ = new pinauth::Guard(fill_random, []() { return millis(); });  // NOLINT
  pinauth::Stored pin{};
  if (this->pin_pref_.load(&pin) && pin.set == 1)
    this->guard_->load(pin);
  this->apply_tz_();
  this->setup_cook_();
  auto *base = web_server_base::global_web_server_base;
  if (base != nullptr) {
    base->add_handler(new Handler(this));  // NOLINT
  } else {
    ESP_LOGW(TAG, "No web server: the device page's PIN and settings are unavailable");
  }
#ifdef USE_ESP32
  this->jobs_sem_ = xSemaphoreCreateCounting(16, 0);
  xTaskCreate(Standalone::worker_task_, "standalone_http", 8192, this, 2, nullptr);
#endif
}

void Standalone::dump_config() {
  ESP_LOGCONFIG(TAG,
                "Standalone:\n"
                "  Device page PIN: %s\n"
                "  Notifications: %s (ntfy %s, Pushover %s, Telegram %s)\n"
                "  On-device weather: %s\n"
                "  Time zone from the device page: %s",
                YESNO(this->guard_ && this->guard_->pin_set()), this->s_.route, YESNO(this->s_.ntfy_topic[0]),
                YESNO(this->s_.pushover_user[0] && this->s_.pushover_token[0]),
                YESNO(this->s_.telegram_token[0] && this->s_.telegram_chat[0]), YESNO(this->weather_here()),
                YESNO(this->s_.tz_set));
}

void Standalone::loop() {
  const uint32_t now = millis();
  this->loop_cook_(now);
  if (this->save_pending_.exchange(false))
    this->save_();
  // Weather: every 30 min while a location is set (and straight away after it changes).
  if (this->weather_here() && (this->wx_fetched_ == 0 || now - this->wx_fetched_ > 30 * 60 * 1000)) {
    this->wx_fetched_ = now | 1;
    this->fetch_weather_();
  }
  bool ready;
  float t, h, w;
  std::vector<float> mins, temps;
  {
    std::lock_guard<std::mutex> g(this->results_lock_);
    ready = this->wx_ready_;
    this->wx_ready_ = false;
    t = this->wx_t_; h = this->wx_h_; w = this->wx_w_;
    if (ready) { mins.swap(this->fc_min_); temps.swap(this->fc_t_); }
  }
  if (ready && this->weather_here()) {
#ifdef USE_SENSOR
    if (this->wx_temp_ && !std::isnan(t)) this->wx_temp_->publish_state(t);
    if (this->wx_hum_ && !std::isnan(h)) this->wx_hum_->publish_state(h);
    if (this->wx_wind_ && !std::isnan(w)) this->wx_wind_->publish_state(w);
#endif
    if (this->cook_ != nullptr && mins.size() >= 2)
      this->cook_->set_forecast(mins, temps);
    this->wx_at_ = now;
    ESP_LOGD(TAG, "Weather: %.1f, %.0f %%, wind %.1f; %u forecast hours", t, h, w, unsigned(mins.size()));
  }
}

void Standalone::save_() {
  Settings copy;
  Settings2 copy2;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    copy = this->s_;
    copy2 = this->s2_;
    this->pin_pref_.save(&this->guard_->stored());
  }
  this->pref_.save(&copy);
  this->pref2_.save(&copy2);
  global_preferences->sync();
}

void Standalone::apply_tz_() {
#ifdef USE_TIME_TIMEZONE
  if (!this->s_.tz_set)
    return;
  time::ParsedTimezone tz{};
  static_assert(sizeof(tz) <= sizeof(Settings::tz_raw), "time zone doesn't fit");
  std::memcpy(&tz, this->s_.tz_raw, sizeof(tz));
  time::set_global_tz(tz);
#endif
}

bool Standalone::pin_set() {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  return this->guard_ != nullptr && this->guard_->pin_set();
}

bool Standalone::write_allowed(const std::string &token) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  return this->guard_ == nullptr || !this->guard_->pin_set() || this->guard_->check(token);
}

void Standalone::clear_pin() {
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    this->guard_->clear();
  }
  ESP_LOGW(TAG, "Device page PIN cleared: set a new one on the device page");
  this->save_();
}

bool Standalone::migrate_ntfy_topic(const std::string &topic) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  if (topic.empty() || topic.size() >= sizeof(this->s_.ntfy_topic))
    return false;
  if (this->s_.ntfy_topic[0])
    return true;  // already moved: just empty the old field
  std::strncpy(this->s_.ntfy_topic, topic.c_str(), sizeof(this->s_.ntfy_topic) - 1);
  this->save_pending_ = true;
  ESP_LOGI(TAG, "Moved the ntfy topic into the controller's secret store");
  return true;
}

// ---------------------------------------------------------------- notifications

static bool ha_connected() {
#ifdef USE_API
  return api::global_api_server != nullptr && api::global_api_server->is_connected();
#else
  return false;
#endif
}

bool Standalone::direct_configured_() const {
  return this->s_.ntfy_topic[0] || (this->s_.pushover_user[0] && this->s_.pushover_token[0]) ||
         (this->s_.telegram_token[0] && this->s_.telegram_chat[0]);
}

bool Standalone::send_via_ha() const {
  const std::string r = this->s_.route;
  return r == "ha" || r == "both" || (r == "auto" && ha_connected());
}

static std::string url_encode(const std::string &s) {
  static const char *H = "0123456789ABCDEF";
  std::string o;
  for (unsigned char c : s) {
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') o += char(c);
    else { o += '%'; o += H[c >> 4]; o += H[c & 15]; }
  }
  return o;
}

void Standalone::notify(const std::string &title, const std::string &message, int priority, const std::string &tag) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  const std::string r = this->s_.route;
  // Straight to the phone when the route says so, when Home Assistant isn't there (auto), and always for critical
  // alarms (they must arrive even if Home Assistant is down).
  bool direct = r == "direct" || r == "both" || (r == "auto" && !ha_connected()) || priority >= 2;
  if (!direct || !this->direct_configured_())
    return;
  if (this->s_.ntfy_topic[0]) {
    std::string body = json::build_json([&](JsonObject root) {
      root["topic"] = this->s_.ntfy_topic;
      root["title"] = title;
      root["message"] = message;
      root["priority"] = priority >= 2 ? 5 : priority == 1 ? 4 : 3;
      if (!tag.empty()) root["tags"].to<JsonArray>().add(tag);
    }).c_str();
    this->queue_({"ntfy", "POST", std::string(this->s_.ntfy_server), body, "application/json", {}});
  }
  if (this->s_.pushover_user[0] && this->s_.pushover_token[0]) {
    std::string body = "token=" + url_encode(this->s_.pushover_token) + "&user=" + url_encode(this->s_.pushover_user) +
                       "&title=" + url_encode(title) + "&message=" + url_encode(message) +
                       "&priority=" + (priority >= 1 ? "1" : "0");
    this->queue_({"pushover", "POST", "https://api.pushover.net/1/messages.json", body,
                  "application/x-www-form-urlencoded", {}});
  }
  if (this->s_.telegram_token[0] && this->s_.telegram_chat[0]) {
    std::string body = json::build_json([&](JsonObject root) {
      root["chat_id"] = this->s_.telegram_chat;
      root["text"] = title + "\n" + message;
      root["disable_notification"] = priority == 0;
    }).c_str();
    this->queue_({"telegram", "POST", std::string("https://api.telegram.org/bot") + this->s_.telegram_token + "/sendMessage",
                  body, "application/json", {}});
  }
}

void Standalone::test_notify() {
  std::string r;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    r = this->s_.route;
    std::strcpy(this->s_.route, "direct");  // a test always goes straight to the phone
  }
  this->notify("Smoker test", "Notifications from your smoker controller work.", 0, "test");
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  std::strncpy(this->s_.route, r.c_str(), sizeof(this->s_.route) - 1);
}

// ---------------------------------------------------------------- weather (Open-Meteo, no account)

void Standalone::fetch_weather_() {
  char url[320];
  std::snprintf(url, sizeof(url),
                "https://api.open-meteo.com/v1/forecast?latitude=%.2f&longitude=%.2f"
                "&current=temperature_2m,relative_humidity_2m,wind_speed_10m&hourly=temperature_2m&forecast_hours=24"
                "&timeformat=unixtime&temperature_unit=%s&wind_speed_unit=%s",
                this->s_.lat, this->s_.lon, this->fahrenheit_ ? "fahrenheit" : "celsius", this->wind_unit_);
  this->queue_({"weather", "GET", url, "", "", {}});
}

// ---------------------------------------------------------------- the HTTP worker

void Standalone::queue_(Job j) {
#ifdef USE_ESP32
  {
    std::lock_guard<std::mutex> g(this->jobs_lock_);
    if (this->jobs_.size() >= 12) {
      ESP_LOGW(TAG, "Too many outgoing requests waiting; dropped %s", j.what.c_str());
      return;
    }
    this->jobs_.push_back(std::move(j));
  }
  xSemaphoreGive(static_cast<SemaphoreHandle_t>(this->jobs_sem_));
#else
  ESP_LOGD(TAG, "(host build) would send %s to %s", j.what.c_str(), j.url.c_str());
#endif
}

void Standalone::worker_task_(void *arg) { static_cast<Standalone *>(arg)->worker_(); }

#ifdef USE_ESP32
static esp_err_t collect_(esp_http_client_event_t *e) {
  if (e->event_id == HTTP_EVENT_ON_DATA && e->user_data != nullptr) {
    auto *s = static_cast<std::string *>(e->user_data);
    if (s->size() + e->data_len <= 32768)
      s->append(static_cast<const char *>(e->data), e->data_len);
  }
  return ESP_OK;
}
#endif

void Standalone::worker_() {
#ifdef USE_ESP32
  for (;;) {
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(this->jobs_sem_), portMAX_DELAY);
    Job j;
    {
      std::lock_guard<std::mutex> g(this->jobs_lock_);
      if (this->jobs_.empty())
        continue;
      j = std::move(this->jobs_.front());
      this->jobs_.pop_front();
    }
    std::string resp;
    esp_http_client_config_t cfg{};
    cfg.url = j.url.c_str();
    cfg.method = j.method == "POST" ? HTTP_METHOD_POST : j.method == "DELETE" ? HTTP_METHOD_DELETE : HTTP_METHOD_GET;
    cfg.timeout_ms = 15000;
    cfg.crt_bundle_attach = esp_crt_bundle_attach;  // real certificate checks
    cfg.event_handler = collect_;
    cfg.user_data = &resp;
    cfg.buffer_size_tx = 1024;
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (c == nullptr)
      continue;
    esp_http_client_set_header(c, "User-Agent", "smoker-controller");
    if (!j.content_type.empty())
      esp_http_client_set_header(c, "Content-Type", j.content_type.c_str());
    for (auto &h : j.headers)
      esp_http_client_set_header(c, h.first.c_str(), h.second.c_str());
    if (!j.body.empty())
      esp_http_client_set_post_field(c, j.body.c_str(), j.body.size());
    esp_err_t err = esp_http_client_perform(c);
    int code = err == ESP_OK ? esp_http_client_get_status_code(c) : 0;
    esp_http_client_cleanup(c);
    // Never log URLs or bodies: they carry the keys.
    char result[96];
    if (err != ESP_OK)
      std::snprintf(result, sizeof(result), "couldn't connect (%s)", esp_err_to_name(err));
    else
      std::snprintf(result, sizeof(result), code >= 200 && code < 300 ? "sent (HTTP %d)" : "refused (HTTP %d)", code);
    ESP_LOGI(TAG, "%s: %s", j.what.c_str(), result);
    std::lock_guard<std::mutex> g(this->results_lock_);
    if (j.what.rfind("share:", 0) == 0 || j.what.rfind("unshare:", 0) == 0 || j.what == "aggregates") {
      this->done_.push_back({j.what, code, j.what == "aggregates" && code == 200 ? std::move(resp) : std::string()});
      continue;
    }
    if (j.what == "ntfy") this->last_result_[0] = result;
    else if (j.what == "pushover") this->last_result_[1] = result;
    else if (j.what == "telegram") this->last_result_[2] = result;
    else if (j.what == "weather" && code == 200) {
      JsonDocument doc = json::parse_json(resp);
      JsonObject cur = doc["current"];
      JsonArray times = doc["hourly"]["time"], temps = doc["hourly"]["temperature_2m"];
      if (!cur.isNull()) {
        this->wx_t_ = cur["temperature_2m"] | NAN;
        this->wx_h_ = cur["relative_humidity_2m"] | NAN;
        this->wx_w_ = cur["wind_speed_10m"] | NAN;
        double t0 = cur["time"] | 0.0;
        this->fc_min_.clear();
        this->fc_t_.clear();
        for (size_t i = 0; i < times.size() && i < temps.size(); i++) {
          double m = ((times[i] | 0.0) - t0) / 60.0;
          if (m >= -59 && !temps[i].isNull()) {
            this->fc_min_.push_back(float(m < 0 ? 0 : m));
            this->fc_t_.push_back(temps[i] | NAN);
          }
        }
        this->wx_ready_ = true;
      }
    }
  }
#endif
}

// ---------------------------------------------------------------- the device page's API: /local/...

static void copy_field(char *dst, size_t n, const std::string &v) {
  std::memset(dst, 0, n);
  std::strncpy(dst, v.c_str(), n - 1);
}

std::string Standalone::status_json_(bool authed) {
  std::string r[3];
  {
    std::lock_guard<std::mutex> g(this->results_lock_);
    for (int i = 0; i < 3; i++) r[i] = this->last_result_[i];
  }
  return json::build_json([&](JsonObject o) {
    o["pin"] = this->guard_->pin_set();
    o["authed"] = authed;
    o["locked"] = this->guard_->locked_for();
    o["ha"] = ha_connected();
    o["route"] = this->s_.route;
    JsonObject set = o["set"].to<JsonObject>();  // secrets: only whether they're there, never their value
    set["ntfy"] = this->s_.ntfy_topic[0] != 0;
    set["pushover"] = this->s_.pushover_user[0] && this->s_.pushover_token[0];
    set["telegram"] = this->s_.telegram_token[0] && this->s_.telegram_chat[0];
    set["ai"] = this->s_.ai_key[0] != 0;
    o["ntfy_server"] = this->s_.ntfy_server;
    o["ai_provider"] = this->s_.ai_provider;
    o["ai_model"] = this->s_.ai_model;
    o["location"] = this->weather_here();
    if (authed && this->weather_here()) {
      o["lat"] = this->s_.lat;
      o["lon"] = this->s_.lon;
    }
    o["tz"] = this->s_.tz_set != 0;
    {
      float est = NAN;
      uint32_t t = ::time(nullptr) > 1700000000 ? uint32_t(::time(nullptr)) : 0;
      int light = this->light_by_(t, &est);
      JsonObject plan = o["plan"].to<JsonObject>();
      plan["serve_by"] = this->s2_.serve_by;
      plan["rest_min"] = this->s2_.rest_min;
      plan["now"] = t;
      if (light > 0) plan["light_by"] = light;
      if (!std::isnan(est)) plan["est_min"] = std::round(est);
    }
    o["weather_age_min"] = this->wx_at_ ? int((millis() - this->wx_at_) / 60000) : -1;
    JsonObject last = o["last"].to<JsonObject>();
    last["ntfy"] = r[0];
    last["pushover"] = r[1];
    last["telegram"] = r[2];
  }).c_str();
}

static std::string err_json(const std::string &msg) {
  return json::build_json([&](JsonObject o) { o["error"] = msg; }).c_str();
}

std::string Standalone::api(const std::string &method, const std::string &path, const std::string &body,
                            const std::string &token, int &status) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  const bool authed = this->guard_->pin_set() && this->guard_->check(token);
  if (method == "GET" && path == "status")
    return this->status_json_(authed);
  if (method == "GET" && path.rfind("history", 0) == 0) {
    int h = 6;
    size_t q = path.find("hours=");
    if (q != std::string::npos) h = atoi(path.c_str() + q + 6);
    return this->history_json_(h);
  }
  if (method == "GET" && path == "journal")
    return this->journal_json_(authed);
  if (method == "GET" && path == "community")
    return this->community_json_();
  if (method != "POST") {
    status = 404;
    return err_json("not found");
  }
  JsonDocument in = json::parse_json(body);
  auto str = [&](const char *k) { return in[k].is<const char *>() ? std::string(in[k].as<const char *>()) : std::string(); };

  if (path == "login") {
    if (!this->guard_->pin_set()) { status = 409; return err_json("No PIN yet: set one first"); }
    std::string t = this->guard_->login(str("pin"));
    if (t.empty()) {
      status = this->guard_->locked_for() ? 429 : 401;
      return json::build_json([&](JsonObject o) {
        o["error"] = this->guard_->locked_for() ? "Too many wrong PINs: wait and try again" : "Wrong PIN";
        o["locked"] = this->guard_->locked_for();
      }).c_str();
    }
    return json::build_json([&](JsonObject o) { o["token"] = t; }).c_str();
  }
  if (path == "pin") {  // set (first use) or change (needs the current PIN)
    std::string why = this->guard_->set_pin(str("pin"), str("current"));
    if (!why.empty()) { status = 400; return err_json(why); }
    this->save_pending_ = true;
    std::string t = this->guard_->login(str("pin"));
    return json::build_json([&](JsonObject o) { o["token"] = t; }).c_str();
  }
  if (path == "logout") {
    this->guard_->logout(token);
    return "{}";
  }
  // Everything below changes settings or keys: a PIN must be set (so keys are never stored on an open page) and
  // this request must carry a live session.
  if (!this->guard_->pin_set()) { status = 409; return err_json("Set a PIN for the device page first"); }
  if (!authed) { status = 401; return json::build_json([&](JsonObject o) { o["error"] = "Enter the PIN"; o["pin"] = true; }).c_str(); }

  if (path == "secret") {
    const std::string name = str("name"), value = str("value");
    struct F { const char *name; char *dst; size_t n; };
    F fields[] = {{"ntfy_topic", this->s_.ntfy_topic, sizeof(this->s_.ntfy_topic)},
                  {"pushover_user", this->s_.pushover_user, sizeof(this->s_.pushover_user)},
                  {"pushover_token", this->s_.pushover_token, sizeof(this->s_.pushover_token)},
                  {"telegram_token", this->s_.telegram_token, sizeof(this->s_.telegram_token)},
                  {"telegram_chat", this->s_.telegram_chat, sizeof(this->s_.telegram_chat)},
                  {"ai_key", this->s_.ai_key, sizeof(this->s_.ai_key)}};
    for (auto &f : fields) {
      if (name == f.name) {
        if (value.size() >= f.n) { status = 400; return err_json("Too long"); }
        for (char c : value)
          if (c < 0x20 || c > 0x7e) { status = 400; return err_json("Unexpected character"); }
        copy_field(f.dst, f.n, value);
        this->save_pending_ = true;
        return this->status_json_(true);
      }
    }
    status = 400;
    return err_json("Unknown setting");
  }
  if (path == "settings") {
    if (in["route"].is<const char *>()) {
      std::string r = str("route");
      if (r != "auto" && r != "ha" && r != "direct" && r != "both") { status = 400; return err_json("Unknown route"); }
      copy_field(this->s_.route, sizeof(this->s_.route), r);
    }
    if (in["ntfy_server"].is<const char *>()) {
      std::string u = str("ntfy_server");
      if (u.rfind("https://", 0) != 0 || u.size() >= sizeof(this->s_.ntfy_server)) {
        status = 400;
        return err_json("The ntfy server must be an https:// address");
      }
      copy_field(this->s_.ntfy_server, sizeof(this->s_.ntfy_server), u);
    }
    if (in["clear_location"] == true) {
      this->s_.lat = this->s_.lon = NAN;
    } else if (in["lat"].is<float>() && in["lon"].is<float>()) {
      float la = in["lat"], lo = in["lon"];
      if (!(la >= -90 && la <= 90 && lo >= -180 && lo <= 180)) { status = 400; return err_json("Not a place on Earth"); }
      this->s_.lat = std::round(la * 100) / 100;  // about 1 km: enough for the weather, no closer
      this->s_.lon = std::round(lo * 100) / 100;
      this->wx_fetched_ = 0;
    }
    if (in["ai_provider"].is<const char *>()) {
      std::string p = str("ai_provider");
      if (!p.empty() && p != "gemini" && p != "claude" && p != "openai") { status = 400; return err_json("Unknown AI provider"); }
      copy_field(this->s_.ai_provider, sizeof(this->s_.ai_provider), p);
    }
    if (in["ai_model"].is<const char *>())
      copy_field(this->s_.ai_model, sizeof(this->s_.ai_model), str("ai_model").substr(0, sizeof(this->s_.ai_model) - 1));
#ifdef USE_TIME_TIMEZONE
    if (in["tz"].is<JsonObject>()) {  // worked out by the browser: offsets (seconds west of UTC) and DST rules
      JsonObject z = in["tz"];
      time::ParsedTimezone tz{};
      tz.std_offset_seconds = z["std"] | 0;
      tz.dst_offset_seconds = z["dst"] | tz.std_offset_seconds;
      auto rule = [](JsonObject r, time::DSTRule &d) {
        if (r.isNull()) return true;
        int m = r["m"] | 0, w = r["w"] | 0, dow = r["d"] | -1, t = r["t"] | 7200;
        if (m < 1 || m > 12 || w < 1 || w > 5 || dow < 0 || dow > 6 || t < -86400 || t > 2 * 86400) return false;
        d.type = time::DSTRuleType::MONTH_WEEK_DAY;
        d.month = m; d.week = w; d.day_of_week = dow; d.time_seconds = t;
        return true;
      };
      if (std::abs(tz.std_offset_seconds) > 15 * 3600 || std::abs(tz.dst_offset_seconds) > 15 * 3600 ||
          !rule(z["start"], tz.dst_start) || !rule(z["end"], tz.dst_end) ||
          (tz.dst_start.type == time::DSTRuleType::NONE) != (tz.dst_end.type == time::DSTRuleType::NONE)) {
        status = 400;
        return err_json("Unexpected time zone");
      }
      std::memset(this->s_.tz_raw, 0, sizeof(this->s_.tz_raw));
      std::memcpy(this->s_.tz_raw, &tz, sizeof(tz));
      this->s_.tz_set = 1;
      this->apply_tz_();
    }
#endif
    this->save_pending_ = true;
    return this->status_json_(true);
  }
  if (path == "plan" || path == "fuel" || path.rfind("journal/", 0) == 0 || path.rfind("share/", 0) == 0)
    return this->api_cook_(path, in, authed, status);
  if (path == "test-notify") {
    if (!this->direct_configured_()) { status = 400; return err_json("Set up ntfy, Pushover or Telegram first"); }
    this->test_notify();
    return this->status_json_(true);
  }
  status = 404;
  return err_json("not found");
}

}  // namespace standalone
}  // namespace esphome
