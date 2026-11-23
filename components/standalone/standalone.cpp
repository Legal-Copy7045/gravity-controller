#include "standalone.h"

#include <arpa/inet.h>
#include <cctype>

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
#ifdef USE_CAPTIVE_PORTAL
#include "esphome/components/captive_portal/captive_portal.h"
#endif
#include "esphome/components/network/util.h"
#ifdef USE_TIME_TIMEZONE
#include "esphome/components/time/posix_tz.h"
#endif
#include "../cook_assistant/cook_assistant.h"

#ifdef USE_ESP32
#include <esp_crt_bundle.h>
#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_http_client.h>
#include <esp_http_server.h>
#include <lwip/sockets.h>
#include <esp_random.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
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
    if (url.size() >= 7 && std::strncmp(url.c_str(), "/local/", 7) == 0)
      return this->take_();
    // DNS rebinding (a website posing as the controller) is refused for everything, reading included: such a page
    // could otherwise read the live states. Not while the setup hotspot's portal is up (phones ask it for any name).
    if (bad_host_(req) && !portal_active_())
      return this->take_();  // refused in handleRequest
    // Any change through the device page needs the PIN once one is set. ESPHome's web server also carries out
    // actions sent as GET (/button/<name>/press, /number/<name>/set?value=...), so those count as changes too: an
    // <img> on any website could otherwise press a button. Reading (the page, states, the live event stream) stays
    // open on the local network.
    if (req->method() == HTTP_OPTIONS)
      return false;
    const bool action = is_action_(url);
    if ((req->method() == HTTP_GET || req->method() == HTTP_HEAD) && !action)
      return false;
    if (action && clears_pin_(url))
      return this->take_();  // never from the web page, PIN or not: it would reopen the first PIN's window
    if (cross_site_(req))
      return this->take_();  // refused in handleRequest: another website can't post a form here, PIN or not
    if (!this->p_->pin_set())
      return false;
    return !this->p_->write_allowed(token_(req)) && this->take_();
  }

  void handleBody(AsyncWebServerRequest *req, uint8_t *data, size_t len, size_t index, size_t total) override {
    if (index == 0) {
      this->body_.clear();
      this->too_big_ = false;
      // JSON settings are small; a label photo (base64, shrunk by the page) is the one large body, and only an
      // unlocked browser may send one (no one else gets the controller to buffer 400 KB).
      char ubuf[AsyncWebServerRequest::URL_BUF_SIZE];
      this->cap_ = std::strcmp(req->url_to(ubuf).c_str(), "/local/ai/label") == 0 && this->p_->pin_set() &&
                           this->p_->write_allowed(token_(req))
                       ? 400000u : 4096u;
      if (total > 0 && total <= this->cap_) this->body_.reserve(total);  // one allocation, not doubling up to 512 KB
    }
    if (this->too_big_ || this->body_.size() + len > this->cap_) {
      this->too_big_ = true;  // stop here: a body with a gap in it would be garbage
      this->body_.clear();
      return;
    }
    this->body_.append(reinterpret_cast<const char *>(data), len);
  }

  void handleRequest(AsyncWebServerRequest *req) override {
    // This request's body, and nothing left over for the next one (whatever way this one ends).
    std::string body;
    body.swap(this->body_);
    const bool too_big = this->too_big_;
    this->too_big_ = false;
    char buf[AsyncWebServerRequest::URL_BUF_SIZE];
    StringRef url = req->url_to(buf);
    const bool local = url.size() >= 7 && std::strncmp(url.c_str(), "/local/", 7) == 0;
    if (bad_host_(req) && (local || !portal_active_())) {
      std::string me = App.get_name();
      req->send(403, "text/plain",
                ("Open the controller at its IP address or http://" + me + ".local/ (other names are refused)").c_str());
      return;
    }
    if ((req->method() != HTTP_GET || !local) && cross_site_(req)) {
      req->send(403, "application/json", "{\"error\":\"Changes come from the controller's own page only\"}");
      return;
    }
    if (!local && clears_pin_(url)) {
      req->send(403, "application/json",
                "{\"error\":\"Clear the PIN from Home Assistant, or hold the controller's BOOT button for 10 s\"}");
      return;
    }
    if (!local) {
      req->send(401, "application/json", "{\"error\":\"Enter the PIN to make changes\",\"pin\":true}");
      return;
    }
    if (too_big) {
      req->send(413, "application/json", "{\"error\":\"Too big (a photo needs the PIN; keep it under 300 KB)\"}");
      return;
    }
    const char *m = req->method() == HTTP_GET ? "GET" : req->method() == HTTP_POST ? "POST" : "OTHER";
    int status = 200;
    std::string path(url.c_str() + 7);
    if (req->hasArg("hours"))
      path += "?hours=" + req->arg("hours");
    // Run on the controller's API task: the web server's own task has a 4.5 KB stack, too small for this work.
    std::string out = this->p_->api_call(m, path, body, token_(req), peer_(req), status);
    auto *res = req->beginResponse(status, "application/json", out);
    res->addHeader("Cache-Control", "no-store");
    req->send(res);
  }

 protected:
  // A request sent by another website (a form post, a fetch): the browser marks it. Missing headers (curl, old
  // browsers, Home Assistant) are allowed: the PIN still applies.
  static bool cross_site_(AsyncWebServerRequest *req) {
    auto site = req->get_header("Sec-Fetch-Site");
    if (site.has_value() && (site.value() == "cross-site" || site.value() == "same-site"))
      return true;
    auto origin = req->get_header("Origin"), host = req->get_header("Host");
    if (origin.has_value() && host.has_value() && !origin.value().empty() && origin.value() != "null") {
      const std::string &o = origin.value();
      size_t p = o.find("://");
      std::string oh = p == std::string::npos ? o : o.substr(p + 3);
      return oh != host.value();
    }
    return false;
  }
  // /<domain>/<name>/<action>: ESPHome's REST actions (press, turn_on, set, install...), whatever the method.
  static bool is_action_(const StringRef &url) {
    const char *u = url.c_str();
    size_t n = url.size(), slashes = 0;
    for (size_t i = 0; i < n; i++) slashes += u[i] == '/';
    return slashes >= 3 && !(n >= 7 && std::strncmp(u, "/events", 7) == 0);
  }
  // The Host the browser asked for must be this controller (its IP address or <name>.local, any port): a page on
  // another site that rebinds its own name to the controller's address is refused.
  static bool bad_host_(AsyncWebServerRequest *req) {
    auto h = req->get_header("Host");
    if (!h.has_value() || h.value().empty()) return false;  // not a browser
    std::string host = h.value();
    if (!host.empty() && host[0] == '[') return false;  // IPv6 literal
    size_t colon = host.find(':');
    if (colon != std::string::npos) host.resize(colon);
    for (auto &c : host) c = std::tolower(static_cast<unsigned char>(c));
    struct in_addr a;
    if (inet_pton(AF_INET, host.c_str(), &a) == 1 || host == "localhost") return false;
    std::string me = App.get_name();
    for (auto &c : me) c = std::tolower(static_cast<unsigned char>(c));
    if (host.size() && host.back() == '.') host.pop_back();
    if (host == me) return false;
    // <name>.local, or a name the home router gives it under a suffix no website can own.
    for (const char *sfx : {".local", ".lan", ".home", ".internal", ".home.arpa", ".localdomain"})
      if (host == me + sfx) return false;
    return true;
  }
  static std::string token_(AsyncWebServerRequest *req) {
    auto h = req->get_header(TOKEN_HEADER);
    return h.has_value() ? h.value() : std::string();
  }
  // Who's asking (for the PIN's lockout): the IP address, or for IPv6 its /64 (one machine can have many in it).
  static std::string peer_(AsyncWebServerRequest *req) {
#ifdef USE_ESP32
    int fd = httpd_req_to_sockfd(*req);
    struct sockaddr_storage a {};
    socklen_t n = sizeof(a);
    if (fd < 0 || getpeername(fd, reinterpret_cast<struct sockaddr *>(&a), &n) != 0)
      return std::string();
    char b[48] = "";
    if (a.ss_family == AF_INET) {
      inet_ntop(AF_INET, &reinterpret_cast<struct sockaddr_in *>(&a)->sin_addr, b, sizeof(b));
    }
#if LWIP_IPV6
    else if (a.ss_family == AF_INET6) {
      struct in6_addr ip = reinterpret_cast<struct sockaddr_in6 *>(&a)->sin6_addr;
      const uint8_t *p = reinterpret_cast<const uint8_t *>(&ip);
      static const uint8_t V4[12] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xff, 0xff};
      if (std::memcmp(p, V4, 12) == 0)  // an IPv4 client on a dual-stack socket
        return inet_ntop(AF_INET, p + 12, b, sizeof(b)) ? std::string(b) : std::string();
      std::memset(reinterpret_cast<uint8_t *>(&ip) + 8, 0, 8);
      inet_ntop(AF_INET6, &ip, b, sizeof(b));
    }
#endif
    return b;
#else
    return std::string();
#endif
  }
  // "Clear the device page PIN" (base.yaml): Home Assistant's button, not one for the web page.
  static bool clears_pin_(const StringRef &url) {
    std::string u(url.c_str(), url.size());
    for (auto &c : u) c = std::tolower(static_cast<unsigned char>(c));
    return u.rfind("/button/", 0) == 0 && u.find("clear the device page pin") != std::string::npos;
  }
  static bool portal_active_() {
#ifdef USE_CAPTIVE_PORTAL
    return captive_portal::global_captive_portal != nullptr && captive_portal::global_captive_portal->is_active();
#else
    return false;
#endif
  }
  // This handler takes the request: start it with an empty body.
  bool take_() const {
    this->body_.clear();
    this->too_big_ = false;
    return true;
  }
  Standalone *p_;
  mutable std::string body_;
  size_t cap_{4096};
  mutable bool too_big_{false};
};

// ---------------------------------------------------------------- the API task
// The web server runs handlers on a task with a 4.5 KB stack (ESPHome's web_server_idf, fixed). The PIN's PBKDF2, the
// JSON and the journal need more: from 0.2.31 the page's requests overflowed it and the controller restarted
// (exception/panic) whenever the page was open. Requests now run one at a time on a task of their own.
#ifdef USE_ESP32
struct ApiCall {
  const char *method;
  const std::string *path, *body, *token, *client;
  std::string out;
  int status;
};
void Standalone::api_task_(void *arg) {
  auto *s = static_cast<Standalone *>(arg);
  for (;;) {
    ApiCall *c = nullptr;
    if (xQueueReceive(static_cast<QueueHandle_t>(s->api_q_), &c, portMAX_DELAY) != pdTRUE || c == nullptr) continue;
    c->out = s->api(c->method, *c->path, *c->body, *c->token, *c->client, c->status);
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(s->api_done_));
  }
}
#endif

std::string Standalone::api_call(const char *method, const std::string &path, const std::string &body,
                                 const std::string &token, const std::string &client, int &status) {
#ifdef USE_ESP32
  if (this->api_q_ != nullptr) {
    ApiCall c{method, &path, &body, &token, &client, std::string(), 200};
    ApiCall *pc = &c;
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(this->api_mutex_), portMAX_DELAY);  // one request at a time
    xQueueSend(static_cast<QueueHandle_t>(this->api_q_), &pc, portMAX_DELAY);
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(this->api_done_), portMAX_DELAY);  // c lives until it's answered
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(this->api_mutex_));
    status = c.status;
    return std::move(c.out);
  }
#endif
  return this->api(method, path, body, token, client, status);
}

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
  this->sess_pref_ = global_preferences->make_preference<SavedSessions>(fnv1_hash("standalone_sessions_v1"), true);
  SavedSessions ss{};
  if (this->guard_->pin_set() && this->sess_pref_.load(&ss) && ss.n <= 4) {
    std::vector<std::string> toks;
    for (uint8_t i = 0; i < ss.n; i++) { ss.tok[i][64] = 0; toks.emplace_back(ss.tok[i]); }
    this->guard_->restore(toks);
  }
  this->sess_gen_ = this->guard_->generation();
#ifdef USE_ESP32
  // The first PIN's window opens on power-up (or a reset by hand), not on a software restart: with no PIN set,
  // anyone on the Wi-Fi can press Restart, and that mustn't let them claim the page.
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: case ESP_RST_EXT: case ESP_RST_BROWNOUT: case ESP_RST_PWR_GLITCH: case ESP_RST_USB:
    case ESP_RST_JTAG:
      break;
    default:
      this->guard_->close_first_pin();
  }
#endif
  this->apply_tz_();
  this->setup_cook_();
  auto *base = web_server_base::global_web_server_base;
  if (base != nullptr) {
    base->add_handler(new Handler(this));  // NOLINT
  } else {
    ESP_LOGW(TAG, "No web server: the device page's PIN and settings are unavailable");
  }
#ifdef USE_ESP32
  // Allocations of 16 KB and more (a label photo, an AI request or answer, the chart's history) go to the 8 MB PSRAM,
  // not the ~100 KB of internal RAM that Wi-Fi and Bluetooth need: ESP-IDF's own default for PSRAM-backed malloc.
  // (ESPHome's psram component only makes PSRAM available to explicit requests.)
  heap_caps_malloc_extmem_enable(16384);
  // The PIN's hashing sleeps a tick every 1,000 rounds, so it never starves the other tasks on its core.
  pinauth::pbkdf2_yield = []() { vTaskDelay(1); };
  // Never let ESP-IDF's HTTP client log URLs or headers: they carry keys (Telegram's token is in its URL).
  esp_log_level_set("HTTP_CLIENT", ESP_LOG_WARN);
  esp_log_level_set("esp-tls", ESP_LOG_WARN);
  this->api_q_ = xQueueCreate(1, sizeof(void *));
  this->api_done_ = xSemaphoreCreateBinary();
  this->api_mutex_ = xSemaphoreCreateMutex();
  if (this->api_q_ == nullptr || this->api_done_ == nullptr || this->api_mutex_ == nullptr ||
      // Core 0, at the main loop's priority: ESPHome runs the main loop on core 1, so the PIN's hashing (a second or
      // two) runs beside it rather than taking turns with it.
      xTaskCreatePinnedToCore(Standalone::api_task_, "standalone_api", 12288, this, 1, nullptr, 0) != pdPASS) {
    this->api_q_ = nullptr;  // fall back to the web server's own task (as before 0.2.34)
    ESP_LOGE(TAG, "Couldn't start the API task");
  }
  this->jobs_sem_[0] = xSemaphoreCreateCounting(16, 0);
  this->jobs_sem_[1] = xSemaphoreCreateCounting(8, 0);
  xTaskCreate(Standalone::worker_task_, "standalone_http", 8192, this, 2, nullptr);
  // The AI lane's task starts with the first AI question (Standalone::queue_), not at boot: internal memory is
  // tight next to Bluetooth and Wi-Fi, and a controller without an AI key never needs it.
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
  this->loop_ha_watch_(now);
  if (this->clear_pin_pending_) this->clear_pin();
  {  // keep the unlocked browsers across a restart (saved only when the list changes: login, logout, expiry)
    std::unique_lock<std::mutex> g(this->guard_lock_, std::try_to_lock);  // never wait here: the PIN may be hashing
    if (g.owns_lock() && this->guard_ != nullptr)
      this->guard_->tick();  // the first PIN's window and the lockouts end on time
    if (g.owns_lock() && this->guard_ != nullptr && this->guard_->generation() != this->sess_gen_) {
      this->sess_gen_ = this->guard_->generation();
      SavedSessions ss{};
      for (auto &t : this->guard_->tokens()) {
        if (ss.n >= 4) break;
        std::strncpy(ss.tok[ss.n++], t.c_str(), 64);
      }
      this->sess_pref_.save(&ss);
    }
  }
  if (this->save_pending_.exchange(false))
    this->save_();
  // Weather: every 30 min while a location is set (and straight away after it changes).
  if (this->weather_here() && (this->wx_fetched_ == 0 || now - this->wx_fetched_ > 30 * 60 * 1000)) {
    this->wx_fetched_ = now ? now : 1;  // not "now | 1": 1 ms ahead, now - it wraps
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
  }
  {
    std::unique_lock<std::mutex> gl(this->guard_lock_, std::try_to_lock);  // never wait on the PIN's hashing
    if (!gl.owns_lock()) { this->save_pending_ = true; return; }  // the next loop tries again
    pinauth::Stored st = this->guard_->stored();
    gl.unlock();
    this->pin_pref_.save(&st);
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
  // Stored as ESPHome's own struct: if a future ESPHome changes it, don't apply garbage (fall back to UTC/HA).
  if (tz.std_offset_seconds < -15 * 3600 || tz.std_offset_seconds > 15 * 3600 || tz.dst_offset_seconds < -15 * 3600 ||
      tz.dst_offset_seconds > 15 * 3600) {
    ESP_LOGW(TAG, "The saved time zone doesn't look right: set it again on the device page");
    return;
  }
  time::set_global_tz(tz);
#endif
}

bool Standalone::pin_set() {
  std::lock_guard<std::mutex> g(this->guard_lock_);
  return this->guard_ != nullptr && this->guard_->pin_set();
}

bool Standalone::write_allowed(const std::string &token) {
  std::lock_guard<std::mutex> g(this->guard_lock_);
  return this->guard_ == nullptr || !this->guard_->pin_set() || this->guard_->check(token);
}

void Standalone::clear_pin() {
  {
    // From the main loop (BOOT button, Home Assistant): never wait on a PIN being hashed; try again next loop.
    std::unique_lock<std::mutex> g(this->guard_lock_, std::try_to_lock);
    if (!g.owns_lock()) { this->clear_pin_pending_ = true; return; }
    this->clear_pin_pending_ = false;
    this->guard_->clear();
  }
  ESP_LOGW(TAG, "Device page PIN cleared: set a new one on the device page within 15 minutes");
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

// A self-hosted ntfy server: a public DNS name only (no IP address, localhost or home-network name), so the controller
// can't be pointed at something on the home network. host_part: everything after "https://".
static bool public_host(const std::string &host_part) {
  std::string h = host_part.substr(0, host_part.find_first_of("/?#"));
  if (h.find('@') != std::string::npos || h.empty() || h[0] == '[') return false;  // user info, IPv6 literal
  size_t colon = h.find(':');
  if (colon != std::string::npos) {
    std::string port = h.substr(colon + 1);
    h.resize(colon);
    if (port.empty() || port.size() > 5) return false;
    for (char c : port)
      if (!isdigit(static_cast<unsigned char>(c))) return false;
  }
  for (auto &c : h) {
    c = std::tolower(static_cast<unsigned char>(c));
    if (!(isalnum(static_cast<unsigned char>(c)) || c == '-' || c == '.')) return false;
  }
  if (!h.empty() && h.back() == '.') h.pop_back();
  size_t dot = h.rfind('.');
  if (dot == std::string::npos || dot == 0) return false;  // one label: localhost, a router name
  // The last label must be letters: rules out 10.0.0.1, 2130706433 and friends.
  std::string tld = h.substr(dot + 1);
  if (tld.size() < 2) return false;
  for (char c : tld)
    if (!isalpha(static_cast<unsigned char>(c))) return false;
  for (const char *sfx : {".local", ".lan", ".home", ".internal", ".localhost", ".localdomain", ".home.arpa", ".intranet",
                          ".corp", ".private"}) {
    size_t n = std::strlen(sfx);
    if (h.size() >= n && h.compare(h.size() - n, n, sfx) == 0) return false;
  }
  return true;
}
static bool public_server(const char *url) {
  return std::strncmp(url, "https://", 8) == 0 && public_host(std::string(url + 8));
}

void Standalone::notify(const std::string &title, const std::string &message, int priority, const std::string &tag) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  const std::string r = this->s_.route;
  // Straight to the phone when the route says so, when Home Assistant isn't there (auto), and always for critical
  // alarms (they must arrive even if Home Assistant is down).
  bool direct = r == "direct" || r == "both" || (r == "auto" && !ha_connected()) || priority >= 2;
  if (!direct || !this->direct_configured_())
    return;
  // Tapping the alert opens the controller's page at the right section (on the home Wi-Fi).
  std::string page;
  for (auto &ip : network::get_ip_addresses()) {
    if (ip.is_set() && ip.is_ip4()) {
      char b[network::IP_ADDRESS_BUFFER_SIZE];
      page = std::string("http://") + ip.str_to(b) + "/";
      break;
    }
  }
  if (!page.empty()) {
    const bool food = tag.rfind("done_", 0) == 0 || tag.rfind("pull_", 0) == 0 || tag.rfind("stall_", 0) == 0 ||
                      tag.rfind("probe", 0) == 0 || tag.rfind("rest", 0) == 0;
    page += food ? "#s-food" : (tag.rfind("fuel", 0) == 0 || tag.rfind("fire", 0) == 0) ? "#s-fuel"
                 : (tag.rfind("pit", 0) == 0 || tag == "program" || tag == "lid") ? "#s-pit" : "";
  }
  if (this->s_.ntfy_topic[0] && !public_server(this->s_.ntfy_server)) {
    std::lock_guard<std::mutex> r(this->results_lock_);  // saved by older firmware, and pointing into the home network
    this->last_result_[0] = "not sent: set a public ntfy server";
  } else if (this->s_.ntfy_topic[0]) {
    std::string body = json::build_json([&](JsonObject root) {
      root["topic"] = this->s_.ntfy_topic;
      root["title"] = title;
      root["message"] = message;
      root["priority"] = priority >= 2 ? 5 : priority == 1 ? 4 : 3;
      if (!tag.empty()) root["tags"].to<JsonArray>().add(tag);
      if (!page.empty()) {
        root["click"] = page;
        JsonObject a = root["actions"].to<JsonArray>().add<JsonObject>();
        a["action"] = "view";
        a["label"] = "Open the smoker page";
        a["url"] = page;
      }
    }).c_str();
    this->queue_({"ntfy", "POST", std::string(this->s_.ntfy_server), body, "application/json", {}});
  }
  if (this->s_.pushover_user[0] && this->s_.pushover_token[0]) {
    std::string body = "token=" + url_encode(this->s_.pushover_token) + "&user=" + url_encode(this->s_.pushover_user) +
                       "&title=" + url_encode(title) + "&message=" + url_encode(message) +
                       "&priority=" + (priority >= 1 ? "1" : "0") +
                       (page.empty() ? std::string() : "&url=" + url_encode(page) + "&url_title=" + url_encode("Open the smoker page"));
    this->queue_({"pushover", "POST", "https://api.pushover.net/1/messages.json", body,
                  "application/x-www-form-urlencoded", {}});
  }
  if (this->s_.telegram_token[0] && this->s_.telegram_chat[0]) {
    std::string body = json::build_json([&](JsonObject root) {
      root["chat_id"] = this->s_.telegram_chat;
      root["text"] = title + "\n" + message + (page.empty() ? std::string() : "\n" + page);
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
    const int lane = j.lane ? 1 : 0;
    std::lock_guard<std::mutex> g(this->jobs_lock_[lane]);
    if (this->jobs_[lane].size() >= 12) {
      ESP_LOGW(TAG, "Too many outgoing requests waiting; dropped %s", j.what.c_str());
      if (lane == 1 || j.what.rfind("share:", 0) == 0 || j.what.rfind("unshare:", 0) == 0) {
        std::lock_guard<std::mutex> r(this->results_lock_);
        this->done_.push_back({j.what, 0, std::string()});
      }
      return;
    }
    if (lane == 1 && !this->ai_task_) {
      this->ai_task_ = true;
      if (xTaskCreate(Standalone::worker_task_ai_, "standalone_ai", 8192, this, 1, nullptr) != pdPASS) {
        this->ai_task_ = false;
        ESP_LOGW(TAG, "Not enough memory to start the AI right now; dropped %s", j.what.c_str());
        std::lock_guard<std::mutex> r(this->results_lock_);
        this->done_.push_back({j.what, 0, std::string()});  // the page sees "couldn't reach the AI", not a stuck "asking"
        return;
      }
    }
    this->jobs_[lane].push_back(std::move(j));
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(this->jobs_sem_[lane]));
  }
#else
  ESP_LOGD(TAG, "(host build) would send %s to %s", j.what.c_str(), j.url.c_str());
#endif
}

void Standalone::worker_task_(void *arg) { static_cast<Standalone *>(arg)->worker_lane_(0); }
void Standalone::worker_task_ai_(void *arg) { static_cast<Standalone *>(arg)->worker_lane_(1); }
void Standalone::worker_() { this->worker_lane_(0); }

#ifdef USE_ESP32
static esp_err_t collect_(esp_http_client_event_t *e) {
  if (e->event_id == HTTP_EVENT_ON_DATA && e->user_data != nullptr) {
    auto *s = static_cast<std::string *>(e->user_data);
    if (s->size() + e->data_len <= 65536)  // an AI answer can be long (PSRAM)
      s->append(static_cast<const char *>(e->data), e->data_len);
  }
  return ESP_OK;
}
#endif

void Standalone::worker_lane_(int lane) {
#ifdef USE_ESP32
  for (;;) {
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(this->jobs_sem_[lane]), portMAX_DELAY);
    Job j;
    {
      std::lock_guard<std::mutex> g(this->jobs_lock_[lane]);
      if (this->jobs_[lane].empty())
        continue;
      j = std::move(this->jobs_[lane].front());
      this->jobs_[lane].pop_front();
    }
    std::string resp;
    esp_http_client_config_t cfg{};
    cfg.url = j.url.c_str();
    cfg.method = j.method == "POST" ? HTTP_METHOD_POST : j.method == "DELETE" ? HTTP_METHOD_DELETE : HTTP_METHOD_GET;
    cfg.timeout_ms = lane ? 180000 : 15000;  // an AI answer can take a couple of minutes
    cfg.crt_bundle_attach = esp_crt_bundle_attach;  // real certificate checks
    // Never follow a redirect: it could point into the home network, and headers (an AI key) would go along. A 3xx
    // counts as a failure.
    cfg.disable_auto_redirect = true;
    cfg.event_handler = collect_;
    cfg.user_data = &resp;
    cfg.buffer_size_tx = 1024;
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (c == nullptr) {  // out of memory: still report it, or the page waits forever ("asking", "sending")
      ESP_LOGW(TAG, "%s: couldn't start a request (memory)", j.what.c_str());
      if (j.what.rfind("ai:", 0) == 0 || j.what.rfind("share:", 0) == 0 || j.what.rfind("unshare:", 0) == 0) {
        std::lock_guard<std::mutex> g(this->results_lock_);
        this->done_.push_back({j.what, 0, std::string()});
      }
      continue;
    }
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
      std::snprintf(result, sizeof(result),
                    code >= 200 && code < 300   ? "sent (HTTP %d)"
                    : code >= 300 && code < 400 ? "redirected (HTTP %d), not followed"
                                                : "refused (HTTP %d)",
                    code);
    ESP_LOGI(TAG, "%s: %s", j.what.c_str(), result);
    std::lock_guard<std::mutex> g(this->results_lock_);
    if (j.what.rfind("share:", 0) == 0 || j.what.rfind("unshare:", 0) == 0 || j.what == "aggregates" ||
        j.what.rfind("ai:", 0) == 0) {
      bool keep = (j.what == "aggregates" && code == 200) || j.what.rfind("ai:", 0) == 0;
      this->done_.push_back({j.what, code, keep ? std::move(resp) : std::string()});
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
    o["pin"] = this->req_pin_;
    o["authed"] = authed;
    o["locked"] = this->req_locked_;
    if (!this->req_pin_) o["first_pin"] = this->req_first_pin_;  // seconds left for the first PIN (0 = power-cycle first)
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
      // When you're eating (and so when the house is busy) is for an unlocked page once a PIN is set.
      const bool show = authed || !this->req_pin_;
      plan["serve_by"] = show ? this->s2_.serve_by : 0;
      plan["rest_min"] = this->s2_.rest_min;
      plan["now"] = t;
      if (show && light > 0) plan["light_by"] = light;
      if (show && !std::isnan(est)) plan["est_min"] = std::round(est);
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

// login / pin / logout (called with guard_lock_ held, not lock_).
std::string Standalone::api_pin_(const std::string &path, const std::string &body, const std::string &token,
                                 const std::string &client, int &status) {
  JsonDocument in = json::parse_json(body);
  auto str = [&](const char *k) { return in[k].is<const char *>() ? std::string(in[k].as<const char *>()) : std::string(); };
  if (path == "login") {
    if (!this->guard_->pin_set()) { status = 409; return err_json("No PIN yet: set one first"); }
    const std::string pin = str("pin");
    if (!pinauth::well_formed(pin)) { status = 400; return err_json("Enter the PIN (6 to 32 characters)"); }  // not counted
    std::string t = this->guard_->login(pin, client);
    if (t.empty()) {
      const uint32_t locked = this->guard_->locked_for(client);
      status = locked ? 429 : 401;
      return json::build_json([&](JsonObject o) {
        o["error"] = locked ? "Too many wrong PINs: wait and try again" : "Wrong PIN";
        o["locked"] = locked;
      }).c_str();
    }
    return json::build_json([&](JsonObject o) { o["token"] = t; }).c_str();
  }
  if (path == "pin") {  // set (first use, within its window) or change (needs the current PIN)
    std::string why = this->guard_->set_pin(str("pin"), str("current"), client);
    if (why == pinauth::FIRST_PIN_CLOSED) { status = 403; return err_json(why); }
    if (!why.empty()) { status = 400; return err_json(why); }
    this->save_pending_ = true;
    std::string t = this->guard_->new_session();  // (not login(): that would hash the PIN a third time)
    return json::build_json([&](JsonObject o) { o["token"] = t; }).c_str();
  }
  if (path == "logout") {
    this->guard_->logout(token);
    return "{}";
  }
  status = 404;
  return err_json("not found");
}

std::string Standalone::api(const std::string &method, const std::string &path, const std::string &body,
                            const std::string &token, const std::string &client, int &status) {
  // The PIN (login, set or change, logout) first, under its own lock: hashing it takes a while on the controller,
  // and the main loop must never wait on that (it takes lock_ below).
  bool authed;
  {
    std::lock_guard<std::mutex> gl(this->guard_lock_);
    authed = this->guard_->pin_set() && this->guard_->check(token);
    this->req_pin_ = this->guard_->pin_set();  // for this request's answer (read below without guard_lock_)
    this->req_locked_ = this->guard_->locked_for(client);
    this->req_first_pin_ = this->guard_->first_pin_for();
    if (method == "POST" && (path == "login" || path == "pin" || path == "logout"))
      return this->api_pin_(path, body, token, client, status);
  }
  std::lock_guard<std::recursive_mutex> g(this->lock_);
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
  if (method == "GET" && path == "ai")
    return this->ai_json_(authed || !this->req_pin_);
  // Capture mode (what the Char-Griller app wrote to the controller posing as the grill): behind the PIN when one is
  // set, reading included, like the switch that turns it on.
  if (path == "capture" || path == "capture/clear") {
    if (this->req_pin_ && !authed) {
      status = 401;
      return json::build_json([&](JsonObject o) { o["error"] = "Enter the PIN"; o["pin"] = true; }).c_str();
    }
    if (!this->capture_json_) {
      if (method == "GET" && path == "capture")
        return "{\"available\":false,\"records\":[]}";
      status = 404;
      return err_json("not found");
    }
    if (method == "POST" && path == "capture/clear" && this->capture_clear_)
      this->capture_clear_();
    else if (!(method == "GET" && path == "capture")) {
      status = 404;
      return err_json("not found");
    }
    return this->capture_json_();
  }
  if (method != "POST") {
    status = 404;
    return err_json("not found");
  }
  // Everything below changes settings or keys: a PIN must be set (so keys are never stored on an open page) and
  // this request must carry a live session. Checked before the body is even parsed.
  if (!this->req_pin_) { status = 409; return err_json("Set a PIN for the device page first"); }
  if (!authed) { status = 401; return json::build_json([&](JsonObject o) { o["error"] = "Enter the PIN"; o["pin"] = true; }).c_str(); }
  JsonDocument in = json::parse_json(body);
  auto str = [&](const char *k) { return in[k].is<const char *>() ? std::string(in[k].as<const char *>()) : std::string(); };

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
      while (!u.empty() && u.back() == '/') u.pop_back();
      if (u.rfind("https://", 0) != 0 || u.size() >= sizeof(this->s_.ntfy_server)) {
        status = 400;
        return err_json("The ntfy server must be an https:// address");
      }
      if (!public_server(u.c_str())) {
        status = 400;
        return err_json("The ntfy server must be a public name (like ntfy.example.com), not an address on your network");
      }
      if (u != this->s_.ntfy_server) {
        // The topic was for the old server: never hand it to a new one (whoever changed the server would read it).
        std::memset(this->s_.ntfy_topic, 0, sizeof(this->s_.ntfy_topic));
        std::lock_guard<std::mutex> r(this->results_lock_);
        this->last_result_[0].clear();
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
    if (in["ai_model"].is<const char *>()) {
      for (char ch : str("ai_model"))  // it goes into the provider's URL (Gemini): letters, digits, - . _ only
        if (!(isalnum(static_cast<unsigned char>(ch)) || ch == '-' || ch == '.' || ch == '_')) {
          status = 400;
          return err_json("Unexpected character in the model name");
        }
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
  if (path.rfind("ai/", 0) == 0)
    return this->api_ai_(path, in, status);
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
