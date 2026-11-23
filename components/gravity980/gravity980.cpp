#include "gravity980.h"

#include <algorithm>
#include <cstring>

#include <cerrno>
#include <cmath>
#include <cstring>

#include <fcntl.h>
#include <netdb.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

#ifdef USE_ESP32
#include <mutex>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#endif
#ifdef USE_GRAVITY980_BLE
#include "esphome/components/esp32_ble/ble.h"
#endif

namespace esphome {
namespace gravity980 {

static const char *const TAG = "gravity980";

// Looking a hostname up (getaddrinfo) can take several seconds when DNS is slow or the name doesn't answer (mDNS
// retries for ~7 s): long enough for the main loop's 5 s watchdog to restart the controller. On the controller it
// runs on a small task of its own; the main loop asks and picks the answer up on a later connection attempt.
#ifdef USE_ESP32
namespace {
struct DnsLookup {
  std::mutex m;
  std::string want, got;
  uint32_t addr{0};
  bool busy{false}, done{false};
  TaskHandle_t task{nullptr};
};
DnsLookup dns_;
void dns_task(void *) {
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    std::string h;
    {
      std::lock_guard<std::mutex> g(dns_.m);
      h = dns_.want;
    }
    struct addrinfo hints {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo *res = nullptr;
    uint32_t a = 0;
    if (getaddrinfo(h.c_str(), nullptr, &hints, &res) == 0 && res != nullptr) {
      a = reinterpret_cast<struct sockaddr_in *>(res->ai_addr)->sin_addr.s_addr;
      freeaddrinfo(res);
    }
    std::lock_guard<std::mutex> g(dns_.m);
    dns_.got = h;
    dns_.addr = a;
    dns_.busy = false;
    dns_.done = true;
  }
}
}  // namespace
#endif

std::string hex_dump(const uint8_t *data, size_t len) {
  static const char *const HEX = "0123456789ABCDEF";
  std::string s;
  s.reserve(len * 3);
  for (size_t i = 0; i < len; i++) {
    if (i)
      s += ' ';
    s += HEX[data[i] >> 4];
    s += HEX[data[i] & 0xF];
  }
  return s;
}
static const char *const PROBE_NAME[PROBE_COUNT] = {"pit", "food1", "food2"};
static const uint32_t CONNECT_TIMEOUT_MS = 5000;
// The grill silently ignores writes while idle; unacknowledged writes revert.
static const uint32_t VERIFY_TIMEOUT_MS = 6000;

float Gravity980Component::to_unit_(uint16_t f) const {
  if (this->fahrenheit_)
    return float(f);
  return roundf(f_to_c(float(f)) * 10.0f) / 10.0f;
}

uint16_t Gravity980Component::from_unit_(float v) const {
  float f = this->fahrenheit_ ? v : c_to_f(v);
  if (!(f > 0.0f) || f > 2000.0f)
    return 0;  // out of any valid range; build_target_command rejects 0
  return uint16_t(lroundf(f));
}

void Gravity980Component::set_host(const std::string &host) {
  if (host == this->host_)
    return;
  this->host_ = host;
  this->tcp_close_("host changed");
  this->tcp_last_attempt_ = 0;
}

void Gravity980Component::setup() {
  this->publish_unknown_();
  this->recover_pref_ = global_preferences->make_preference<uint32_t>(fnv1_hash("gravity980_recover_boots"));
  if (!this->recover_pref_.load(&this->recover_boots_))
    this->recover_boots_ = 0;
  if (this->recover_boots_ != 0)
    ESP_LOGW(TAG, "Restarted by the link recovery (%u in a row)", unsigned(this->recover_boots_));
  // The grill found last time: tried first after a restart (another Gravity 980 nearby isn't picked up instead).
  this->grill_pref_ = global_preferences->make_preference<uint64_t>(fnv1_hash("gravity980_grill_addr_v1"), true);
  if (!this->grill_pref_.load(&this->remembered_grill_))
    this->remembered_grill_ = 0;
  // A boost interrupted by a restart: put the target back as soon as the grill reports the boosted one.
  this->boost_pref_ = global_preferences->make_preference<uint32_t>(fnv1_hash("gravity980_boost_v1"));
  uint32_t b = 0;
  if (this->boost_pref_.load(&b) && b != 0) {
    this->boost_base_f_ = b >> 16;
    this->boost_f_ = b & 0xFFFF;
    this->boost_start_ = 1;
    this->boost_ms_ = 0;  // over: restore
    ESP_LOGW(TAG, "Boost was running at the restart: restoring the pit target to %u°F", this->boost_base_f_);
  }
#ifdef USE_GRAVITY980_BLE
  if (this->ble_ != nullptr && !this->ble_->has_fixed_address() && this->remembered_grill_ != 0 &&
      this->ble_->get_address() == 0) {
    this->ble_->set_address(this->remembered_grill_);
    ESP_LOGI(TAG, "BLE: trying the remembered grill first");
  }
#endif
}

void Gravity980Component::remember_grill(uint64_t a) {
  if (a == 0 || a == this->remembered_grill_)
    return;
  this->remembered_grill_ = a;
  this->grill_pref_.save(&a);
}

void Gravity980Component::forget_grill() {
  this->remembered_grill_ = 0;
  uint64_t z = 0;
  this->grill_pref_.save(&z);
#ifdef USE_GRAVITY980_BLE
  if (this->ble_ != nullptr && !this->ble_->has_fixed_address()) {
    this->ble_->reconnect("forgot the grill");
    this->ble_->set_address(0);
  }
#endif
  ESP_LOGI(TAG, "Forgot the grill: the next Gravity 980 heard is used");
}

void Gravity980Component::dump_config() {
  ESP_LOGCONFIG(TAG,
                "Gravity 980 bridge:\n"
                "  TCP host: %s:%u\n"
                "  BLE: %s (writes %s)\n"
                "  Unit: %s\n"
                "  Read only: %s",
                this->host_.empty() ? "(not set)" : this->host_.c_str(), this->port_,
#ifdef USE_GRAVITY980_BLE
                this->ble_ != nullptr ? "enabled" : "disabled",
#else
                "not compiled in",
#endif
                YESNO(this->ble_writes_), this->fahrenheit_ ? "°F" : "°C", YESNO(this->read_only_));
}

void Gravity980Component::set_enabled(bool enabled) {
  if (enabled == this->enabled_)
    return;
  this->enabled_ = enabled;
  if (!enabled)
    this->tcp_close_("bridge disabled");
  this->tcp_last_attempt_ = 0;
#ifdef USE_GRAVITY980_BLE
  if (this->ble_ != nullptr)
    this->ble_->set_enabled(enabled);
#endif
  ESP_LOGI(TAG, "Bridge %s", enabled ? "enabled" : "disabled (official app can connect)");
  this->update_active_();
}

void Gravity980Component::wifi_status_(const std::string &msg) {
  ESP_LOGI(TAG, "Grill Wi-Fi: %s", msg.c_str());
  if (this->wifi_ts_ != nullptr)
    this->wifi_ts_->publish_state(msg);
}

bool Gravity980Component::ble_raw_(const std::vector<uint8_t> &data, const char *what) {
#ifdef USE_GRAVITY980_BLE
  if (this->ble_ != nullptr && this->ble_->ready() && this->ble_->write(data))
    return true;
#endif
  this->wifi_status_(std::string("Can't ") + what + ": the grill isn't connected over Bluetooth");
  return false;
}

bool Gravity980Component::wifi_rejoin() {
  if (!this->ble_raw_({0x06, 0x00, 0x00, 0x00}, "ask the grill to join Wi-Fi"))
    return false;
  this->wifi_status_("Asked the grill to join its saved Wi-Fi…");
  return true;
}

bool Gravity980Component::wifi_scan() {
  if (!this->ble_raw_({0x00, 0x00, 0x02, 0x00, 0x01, 0x02}, "scan for Wi-Fi"))
    return false;
  this->wifi_nets_.clear();
  this->wifi_scan_at_ = millis();
  if (this->wifi_networks_ts_ != nullptr)
    this->wifi_networks_ts_->publish_state("Scanning…");
  return true;
}

void Gravity980Component::wifi_scan_done_() {
  this->wifi_scan_at_ = 0;
  // Strongest first, one entry per network name.
  std::sort(this->wifi_nets_.begin(), this->wifi_nets_.end(),
            [](const WifiNet &a, const WifiNet &b) { return a.signal > b.signal; });
  std::string list;
  std::vector<std::string> seen;
  for (const auto &w : this->wifi_nets_) {
    if (std::find(seen.begin(), seen.end(), w.ssid) != seen.end())
      continue;
    seen.push_back(w.ssid);
    if (!list.empty())
      list += ", ";
    list += w.ssid;
    if (list.size() > 200) {
      list += ", …";
      break;
    }
  }
  if (this->wifi_networks_ts_ != nullptr)
    this->wifi_networks_ts_->publish_state(list.empty() ? "No networks found (2.4 GHz only)" : list);
  if (!this->wifi_join_ssid_.empty()) {
    std::string ssid = this->wifi_join_ssid_, pass = this->wifi_join_pass_;
    this->wifi_join_ssid_.clear();
    this->wifi_join_pass_.clear();
    for (const auto &w : this->wifi_nets_)
      if (w.ssid == ssid) {
        this->wifi_send_credentials_(w, pass);
        return;
      }
    this->wifi_status_("The grill can't see '" + ssid + "' (it only joins 2.4 GHz networks; is it in range?)");
  }
}

bool Gravity980Component::wifi_send_credentials_(const WifiNet &net, const std::string &password) {
  std::vector<uint8_t> m;
  if (!build_wifi_credentials(net.bssid, password, m)) {
    this->wifi_status_("Password too long (max 63 characters)");
    return false;
  }
  bool ok = this->ble_raw_(m, "send the Wi-Fi details");
  std::fill(m.begin(), m.end(), 0);  // don't leave the password lying around
  if (!ok)
    return false;
  this->wifi_cred_at_ = millis();
  this->wifi_status_("Sent the Wi-Fi details for '" + net.ssid + "' to the grill…");
  return true;
}

bool Gravity980Component::wifi_join(const std::string &ssid, const std::string &password) {
  if (ssid.empty()) {
    this->wifi_status_("Enter the network name first");
    return false;
  }
  for (const auto &w : this->wifi_nets_)
    if (w.ssid == ssid)
      return this->wifi_send_credentials_(w, password);
  // The grill needs the access point's address, which comes from a scan: scan first, then send.
  this->wifi_join_ssid_ = ssid;
  this->wifi_join_pass_ = password;
  if (!this->wifi_scan()) {
    this->wifi_join_ssid_.clear();
    this->wifi_join_pass_.clear();
    return false;
  }
  this->wifi_status_("Looking for '" + ssid + "'…");
  return true;
}

void Gravity980Component::loop() {
  // Wi-Fi setup timers: scan results arrive over ~5 s; after sending credentials, join even without an ack.
  if (this->wifi_scan_at_ != 0 && millis() - this->wifi_scan_at_ > 7000)
    this->wifi_scan_done_();
  if (this->wifi_cred_at_ != 0 && millis() - this->wifi_cred_at_ > 4000) {
    this->wifi_cred_at_ = 0;
    this->wifi_rejoin();
  }
  const uint32_t now = millis();
  if (this->enabled_ && !this->host_for_tcp_().empty()) {
    switch (this->tcp_state_) {
      case TcpState::IDLE:
        if (this->tcp_last_attempt_ == 0 || now - this->tcp_last_attempt_ >= this->reconnect_interval_)
          this->tcp_start_connect_();
        break;
      case TcpState::CONNECTING:
        this->tcp_check_connect_();
        break;
      case TcpState::CONNECTED:
        this->tcp_flush_();
        this->tcp_read_();
        if (this->tcp_state_ == TcpState::CONNECTED &&
            int32_t(millis() - this->tcp_last_frame_) > int32_t(this->stale_timeout_))
          this->tcp_close_(this->tcp_got_frame_ ? "no status frames (stale)" : "connected but no data");
        break;
    }
  }
  if (now - this->supervised_at_ >= 1000) {
    this->supervised_at_ = now;
    this->supervise_(now);
  }
  this->check_pending_();
  this->update_active_();
}

// ---------------------------------------------------------------- TCP

void Gravity980Component::tcp_start_connect_() {
  { const uint32_t t = millis(); this->tcp_last_attempt_ = t ? t : 1; }  // not "| 1": ahead of now, it wraps
  struct sockaddr_in addr {};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(this->port_);
  const std::string &host = this->host_for_tcp_();
  if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
    // Hostname: resolving blocks the main loop, so do it rarely (an IP address / DHCP reservation is better).
    if (this->resolved_host_ == host && this->resolved_addr_ != 0 &&
        (millis() - this->resolved_at_) < 600000u) {
      addr.sin_addr.s_addr = this->resolved_addr_;
      goto have_addr;
    }
#ifdef USE_ESP32
    {
      std::lock_guard<std::mutex> g(dns_.m);
      if (dns_.done && dns_.got == host) {  // an answer from the lookup task
        dns_.done = false;
        this->resolved_host_ = host;
        this->resolved_at_ = millis();
        this->resolved_addr_ = dns_.addr;
        if (dns_.addr == 0) {
          ESP_LOGW(TAG, "Cannot resolve %s (use an IP address / DHCP reservation)", host.c_str());
          return;
        }
        addr.sin_addr.s_addr = dns_.addr;
        goto have_addr;
      }
      if (dns_.busy)
        return;  // still looking it up
      if (this->resolved_host_ == host && this->resolved_addr_ == 0 && (millis() - this->resolved_at_) < 60000u)
        return;  // failed recently: back off
      if (dns_.task == nullptr &&
          xTaskCreatePinnedToCore(dns_task, "g980_dns", 4096, nullptr, 1, &dns_.task, 0) != pdPASS) {
        dns_.task = nullptr;
        return;
      }
      dns_.want = host;
      dns_.busy = true;
      dns_.done = false;
      this->resolved_host_ = host;
      this->resolved_at_ = millis();
      this->resolved_addr_ = 0;
    }
    xTaskNotifyGive(dns_.task);
    return;  // connect on a later attempt, once it has answered
#else
    if (this->resolved_host_ == host && (millis() - this->resolved_at_) < 60000u)
      return;  // failed recently: back off
    this->resolved_host_ = host;
    this->resolved_at_ = millis();
    this->resolved_addr_ = 0;
    struct addrinfo hints {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo *res = nullptr;
    if (getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || res == nullptr) {
      ESP_LOGW(TAG, "Cannot resolve %s (use an IP address / DHCP reservation)", host.c_str());
      return;
    }
    addr.sin_addr = reinterpret_cast<struct sockaddr_in *>(res->ai_addr)->sin_addr;
    this->resolved_addr_ = addr.sin_addr.s_addr;
    freeaddrinfo(res);
#endif
  }
have_addr:
  int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (fd < 0) {
    ESP_LOGW(TAG, "socket() failed: %d", errno);
    return;
  }
  fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
  int one = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
  int rc = connect(fd, reinterpret_cast<struct sockaddr *>(&addr), sizeof(addr));
  if (rc != 0 && errno != EINPROGRESS) {
    ESP_LOGD(TAG, "connect() failed: %d", errno);
    close(fd);
    return;
  }
  this->fd_ = fd;
  this->tcp_state_ = TcpState::CONNECTING;
  this->tcp_since_ = millis();
}

void Gravity980Component::tcp_check_connect_() {
  fd_set wfds;
  FD_ZERO(&wfds);
  FD_SET(this->fd_, &wfds);
  struct timeval tv {0, 0};
  int rc = ::select(this->fd_ + 1, nullptr, &wfds, nullptr, &tv);
  if (rc < 0) {
    this->tcp_close_("select() failed");
    return;
  }
  if (rc == 0) {
    if (millis() - this->tcp_since_ > CONNECT_TIMEOUT_MS)
      this->tcp_close_("connect timeout");
    return;
  }
  int err = 0;
  socklen_t len = sizeof(err);
  if (getsockopt(this->fd_, SOL_SOCKET, SO_ERROR, &err, &len) != 0)
    err = errno ? errno : -1;
  if (err != 0) {
    this->tcp_close_("connect refused/unreachable");
    return;
  }
  ESP_LOGI(TAG, "TCP connected to %s:%u", this->host_for_tcp_().c_str(), this->port_);
  this->tcp_state_ = TcpState::CONNECTED;
  this->tcp_since_ = this->tcp_last_frame_ = millis();  // starts the "no data" timer; not "alive" until a frame
  this->tcp_got_frame_ = false;
  this->assembler_.reset();
}

void Gravity980Component::tcp_read_() {
  uint8_t buf[128];
  while (true) {
    ssize_t n = recv(this->fd_, buf, sizeof(buf), 0);
    if (n > 0) {
      if (this->log_raw_)
        ESP_LOGD(TAG, "TCP rx: %s", hex_dump(buf, n).c_str());
      this->assembler_.feed(buf, size_t(n), [this](const uint8_t *f, size_t len) {
        Status s;
        if (parse_status(f, len, s)) {
          this->tcp_last_frame_ = millis();
          this->tcp_got_frame_ = true;
          this->handle_status_(s, Transport::TCP);
        }
      });
      continue;
    }
    if (n == 0) {
      this->tcp_close_("closed by grill");
      return;
    }
    if (errno == EAGAIN || errno == EWOULDBLOCK)
      break;
    this->tcp_close_("recv() error");
    return;
  }
  // First frame after connect: show data before the stride is known.
  Status lone;
  if (this->tcp_state_ == TcpState::CONNECTED && this->assembler_.frame_size() == 0 &&
      int32_t(millis() - this->tcp_since_) > 2500 && this->assembler_.take_lone_frame(lone)) {
    this->tcp_got_frame_ = true;  // shows data early; doesn't refresh the stale timer
    this->handle_status_(lone, Transport::TCP);
  }
}

void Gravity980Component::tcp_flush_() {
  if (this->tx_.empty() || this->fd_ < 0)
    return;
  ssize_t n = send(this->fd_, this->tx_.data(), this->tx_.size(), 0);
  if (n > 0)
    this->tx_.erase(this->tx_.begin(), this->tx_.begin() + n);
  else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK)
    this->tcp_close_("send() error");
}

void Gravity980Component::tcp_close_(const char *reason) {
  if (this->fd_ >= 0) {
    close(this->fd_);
    this->fd_ = -1;
  }
  if (this->tcp_state_ == TcpState::CONNECTED) {
    ESP_LOGW(TAG, "TCP disconnected: %s", reason);
    this->last_drop_ = std::string("Wi-Fi: ") + reason;
  } else if (this->tcp_state_ == TcpState::CONNECTING)
    ESP_LOGD(TAG, "TCP connect failed: %s", reason);
  this->tcp_state_ = TcpState::IDLE;
  this->tx_.clear();
  this->assembler_.reset();
}

// ---------------------------------------------------------------- BLE glue

void Gravity980Component::on_ble_data(const uint8_t *data, size_t len) {
  if (this->log_raw_)
    ESP_LOGD(TAG, "BLE notify (%u): %s", (unsigned) len, hex_dump(data, len).c_str());
  const uint8_t *payload;
  size_t plen;
  if (ble_status_payload(data, len, &payload, &plen)) {
    Status s;
    if (parse_status(payload, plen, s)) {
      this->ble_connected_ = true;
      this->ble_got_frame_ = true;
      this->ble_retries_ = 0;
      this->ble_last_frame_ = millis();
      this->handle_status_(s, Transport::BLE);
    }
    return;
  }
  if (len >= 1 && data[0] == 0x07) {
    // Wi-Fi info: [07][status][signal][..][..][ssid_len][ssid][bssid6][ip4]...
    if (len >= 6 && len >= size_t(6 + data[5] + 6 + 4)) {
      const uint8_t *ip = data + 6 + data[5] + 6;
      std::string ssid;
      for (size_t i = 0; i < data[5]; i++) {
        char ch = char(data[6 + i]);
        ssid += (ch >= 0x20 && ch < 0x7F) ? ch : '?';
      }
      char ipb[16];
      std::snprintf(ipb, sizeof(ipb), "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
      bool has_ip = ip[0] != 0 && ip[0] != 255;
      ESP_LOGI(TAG, "Grill reports Wi-Fi status 0x%02X, signal %d, network '%s', IP %s", data[1], int8_t(data[2]),
               ssid.c_str(), ipb);
#ifdef USE_SENSOR
      // The signal byte: Char-Griller's app shows it as a magnitude (44 = -44 dBm); a signed byte is already dBm.
      if (this->grill_wifi_signal_ != nullptr) {
        int v = int8_t(data[2]);
        float dbm = !has_ip || v == 0 ? NAN : v > 0 ? -float(v) : float(v);
        this->grill_wifi_signal_->publish_state(dbm);
      }
#endif
      if (this->wifi_ts_ != nullptr) {
        char b[96];
        if (ssid.empty())
          std::snprintf(b, sizeof(b), "No network set up (status 0x%02X)", data[1]);
        else if (has_ip)
          std::snprintf(b, sizeof(b), "On %s, IP %s, signal %d (status 0x%02X)", ssid.c_str(), ipb, int8_t(data[2]),
                        data[1]);
        else
          std::snprintf(b, sizeof(b), "Trying %s, no IP yet (status 0x%02X)", ssid.c_str(), data[1]);
        if (!this->wifi_ts_->has_state() || this->wifi_ts_->state != b)
          this->wifi_ts_->publish_state(b);
      }
      // Grill IP address left empty: use the address the grill reports for the Wi-Fi link.
      if (has_ip && this->auto_host_ != ipb) {
        this->auto_host_ = ipb;
        if (this->host_.empty())
          ESP_LOGI(TAG, "Using the grill's reported IP %s for Wi-Fi (Grill IP address is empty)", ipb);
      }
    }
    return;
  }
  if (len >= 5 && data[0] == 0x00 && data[1] == 0x10) {
    WifiScanResult r;
    if (parse_wifi_scan_result(data, len, r)) {
      ESP_LOGI(TAG, "Grill sees Wi-Fi '%s' (signal %u, security %u)", r.ssid.c_str(), r.signal, r.security);
      WifiNet w;
      w.ssid = r.ssid;
      std::memcpy(w.bssid, r.bssid, 6);
      w.signal = r.signal;
      w.security = r.security;
      this->wifi_nets_.push_back(w);
    }
    return;
  }
  if (len >= 1 && data[0] == 0x02) {
    ESP_LOGI(TAG, "Grill stored the Wi-Fi details; asking it to join");
    if (this->wifi_cred_at_ != 0) {
      this->wifi_cred_at_ = 0;
      this->wifi_rejoin();
    }
    return;
  }
  ESP_LOGD(TAG, "Unrecognised BLE notification: %s", hex_dump(data, len).c_str());
}

void Gravity980Component::on_ble_connected() {
  this->ble_connected_ = true;
  this->ble_got_frame_ = false;  // active only once status notifications arrive
  this->ble_last_frame_ = this->ble_warned_ = millis();
  ESP_LOGI(TAG, "BLE connected");
}

void Gravity980Component::on_ble_disconnected(int reason) {
  if (this->ble_connected_ && reason >= 0) {
    // 0x08 supervision timeout (out of range / grill off), 0x13 grill ended it, 0x16 we ended it, 0x3E never set up.
    const char *why = reason == 0x08   ? "signal lost (grill off or out of range)"
                      : reason == 0x13 ? "the grill closed the connection"
                      : reason == 0x16 ? nullptr
                      : reason == 0x3E ? "connection failed to set up"
                                       : "dropped";
    if (why != nullptr)
      this->last_drop_ = why;
  }
  this->ble_connected_ = false;
  this->ble_got_frame_ = false;
  ESP_LOGI(TAG, "BLE disconnected (reason 0x%02X)", unsigned(reason & 0xFF));
  this->update_active_();
}

// ---------------------------------------------------------------- recovery
//
// The bridge must never sit silently on a dead link. Every second:
//  - the "Grill link status" text says, in plain words, what the bridge is doing about the grill right now;
//  - a Bluetooth link that connected but carries no status (a grill switched on after the bridge, or one whose
//    notifications stopped) is dropped and made again;
//  - a connection attempt stuck for 45 s is cancelled; if it can't be, Bluetooth is restarted;
//  - the grill advertising but no link for 3 min: restart Bluetooth; still none 5 min later: reboot the bridge
//    (at most 3 times in a row, counted across reboots; a program comes back paused, the grill keeps its own pit
//    target meanwhile);
//  - no Bluetooth advertisements from anything for 5 min (scanner stuck): restart Bluetooth.
// Turning the bridge off ("Bridge enabled") stops all of this: that's how the grill's own app gets the connection.

void Gravity980Component::set_link_status_(const std::string &s) {
  if (s == this->link_status_)
    return;
  this->link_status_ = s;
  ESP_LOGI(TAG, "Link status: %s", s.c_str());
#ifdef USE_TEXT_SENSOR
  if (this->link_status_ts_ != nullptr)
    this->link_status_ts_->publish_state(s);
#endif
}

#ifdef USE_GRAVITY980_BLE
void Gravity980Component::restart_bluetooth_(const char *why) {
  ESP_LOGW(TAG, "Restarting Bluetooth: %s", why);
  this->last_drop_ = std::string("restarted Bluetooth (") + why + ")";
  this->ble_connected_ = this->ble_got_frame_ = false;
  esp32_ble::global_ble->disable();
  this->set_timeout("g980_ble_on", 3000, []() { esp32_ble::global_ble->enable(); });
}
#endif

void Gravity980Component::publish_signals_(uint32_t now) {
#ifdef USE_SENSOR
  float ble = NAN;
#ifdef USE_GRAVITY980_BLE
  if (this->ble_ != nullptr) {
    if (this->ble_connected_) {
      this->ble_->request_rssi();  // answered asynchronously; published on the next round
      if (this->ble_->link_rssi_at() != 0 && now - this->ble_->link_rssi_at() < 90000)
        ble = this->ble_->link_rssi();
    } else if (this->ble_->grill_seen_at() != 0 && now - this->ble_->grill_seen_at() < 60000) {
      ble = this->ble_->adv_rssi();  // not connected: how strong its advertisements are
    }
  }
#endif
  if (this->ble_signal_ != nullptr && !(std::isnan(ble) && std::isnan(this->ble_signal_->state)) &&
      ble != this->ble_signal_->state)
    this->ble_signal_->publish_state(ble);
  // The grill's own Wi-Fi signal is reported only when asked ("Grill Wi-Fi: join saved network" or a join): the
  // last report stays, and the pages show how old it is.
#endif
}

void Gravity980Component::supervise_(uint32_t now) {
  if (now - this->signals_at_ >= 30000 || this->signals_at_ == 0) {
    this->signals_at_ = now;
    this->publish_signals_(now);
  }
  if (!this->enabled_) {
    this->down_since_ = 0;
    this->recover_stage_ = 0;
    this->set_link_status_("Bridge turned off (the grill's own app can connect)");
    return;
  }
  const bool tcp_wanted = !this->host_for_tcp_().empty();
  if (this->active_ != Transport::NONE) {
    if (this->down_since_ != 0 && !this->last_drop_.empty())
      ESP_LOGI(TAG, "Link back after %u s", unsigned((now - this->down_since_) / 1000));
    this->down_since_ = 0;
    this->recover_stage_ = 0;
    this->ble_retries_ = 0;
    if (this->recover_boots_ != 0) {
      this->recover_boots_ = 0;
      this->recover_pref_.save(&this->recover_boots_);
    }
    this->set_link_status_(this->tcp_up_ && this->ble_up_ ? "Connected over Wi-Fi and Bluetooth (reading Wi-Fi)"
                           : this->active_ == Transport::TCP ? "Connected over Wi-Fi" : "Connected over Bluetooth");
    return;
  }
  if (this->down_since_ == 0)
    this->down_since_ = now;
  const uint32_t down = now - this->down_since_;
  std::string why = this->last_drop_.empty() ? "" : " · last drop: " + this->last_drop_;
#ifdef USE_GRAVITY980_BLE
  if (this->ble_ != nullptr && esp32_ble::global_ble != nullptr) {
    if (!esp32_ble::global_ble->is_active()) {
      this->set_link_status_("Restarting Bluetooth…" + why);
      return;
    }
    using esp32_ble_tracker::ClientState;
    const ClientState st = this->ble_->state();
    if (uint8_t(st) != this->ble_state_) {
      this->ble_state_ = uint8_t(st);
      this->ble_state_since_ = now;
    }
    const uint32_t in_state = now - this->ble_state_since_;
    const bool seen = this->ble_->grill_seen_at() != 0 && now - this->ble_->grill_seen_at() < 60000;
    const bool setup_busy = this->wifi_scan_at_ != 0 || this->wifi_cred_at_ != 0;

    // 1. Connected over Bluetooth but no status: a grill still starting up, or notifications that stopped.
    if (this->ble_connected_ && !setup_busy) {
      const uint32_t limit = this->ble_got_frame_ ? std::max<uint32_t>(this->stale_timeout_ * 2, 30000) : 20000;
      if (int32_t(now - this->ble_last_frame_) > int32_t(limit)) {
        this->last_drop_ = this->ble_got_frame_ ? "status from the grill stopped" : "no status after connecting";
        ESP_LOGW(TAG, "BLE connected but %s for %u s: reconnecting", this->last_drop_.c_str(), unsigned(limit / 1000));
        if (this->ble_retries_ < 255)
          this->ble_retries_++;
        if (!this->ble_->reconnect(this->last_drop_.c_str()))
          this->restart_bluetooth_("couldn't drop a silent link");
        this->ble_connected_ = this->ble_got_frame_ = false;
        return;
      }
    }
    // 2. A connection attempt that never finishes.
    const bool mid_connect = st == ClientState::DISCOVERED || st == ClientState::CONNECTING ||
                             ((st == ClientState::CONNECTED || st == ClientState::ESTABLISHED) && !this->ble_connected_);
    if (mid_connect && in_state > 45000) {
      this->last_drop_ = "connecting took too long";
      if (in_state > 60000 || !this->ble_->reconnect("connecting took too long"))
        this->restart_bluetooth_("a connection attempt was stuck");
      this->ble_state_since_ = now;
      return;
    }
    // 3. Scanner gone quiet: no advertisements from anything for 5 min.
    const uint32_t adv = this->ble_->any_adv_at();
    if (adv != 0 && now - adv < 60000)
      this->scan_restarted_ = false;
    if (!this->scan_restarted_ && now > 300000 && (adv == 0 || now - adv > 300000)) {
      this->scan_restarted_ = true;
      this->restart_bluetooth_("no Bluetooth advertisements for 5 min");
      return;
    }
    // 4. The grill is there (advertising) but no link comes up.
    if (seen && st == ClientState::IDLE && this->recover_stage_ == 0 && down > 180000) {
      this->recover_stage_ = 1;
      this->recover_at_ = now;
      this->restart_bluetooth_("the grill is advertising but no link for 3 min");
      return;
    }
    if (seen && this->recover_stage_ == 1 && now - this->recover_at_ > 300000) {
      if (this->recover_boots_ < 3) {
        this->recover_boots_++;
        this->recover_pref_.save(&this->recover_boots_);
        global_preferences->sync();
        this->set_link_status_("No link to the grill for 8 min: restarting the bridge");
        ESP_LOGE(TAG, "No link to the grill for 8 min although it's advertising: rebooting (%u of 3)",
                 unsigned(this->recover_boots_));
        this->set_timeout("g980_reboot", 2000, []() { App.safe_reboot(); });
        this->recover_stage_ = 2;
        return;
      }
      this->recover_stage_ = 2;
    }
    if (this->recover_stage_ == 2 && this->recover_boots_ >= 3) {
      this->set_link_status_("Can't connect to the grill over Bluetooth although it's in range. Is the grill's own app "
                             "connected to it? Turn the grill off and on" + why);
      return;
    }
    if (setup_busy) {
      this->set_link_status_("Setting up the grill's Wi-Fi over Bluetooth…");
    } else if (this->ble_connected_) {
      this->set_link_status_("Connected over Bluetooth, waiting for the grill's status…");
    } else if (mid_connect) {
      this->set_link_status_("Grill found: connecting over Bluetooth…" + why);
    } else if (seen) {
      this->set_link_status_("Grill in range: reconnecting over Bluetooth" + why);
    } else {
      std::string s = "Looking for the grill over Bluetooth (not seen: off, or out of range)";
      if (tcp_wanted)
        s += " and over Wi-Fi at " + this->host_for_tcp_();
      this->set_link_status_(s + why);
    }
    return;
  }
#endif
  if (tcp_wanted)
    this->set_link_status_("Trying the grill over Wi-Fi at " + this->host_for_tcp_() + why);
  else
    this->set_link_status_("Not connected: no Bluetooth and no grill IP address set");
}

// ---------------------------------------------------------------- common

void Gravity980Component::update_active_() {
  const uint32_t now = millis();
  Transport t = Transport::NONE;
  const bool tcp_up = this->tcp_state_ == TcpState::CONNECTED && this->tcp_got_frame_ &&
                      int32_t(now - this->tcp_last_frame_) < int32_t(this->stale_timeout_);
  const bool ble_up = this->ble_connected_ && this->ble_got_frame_ &&
                      int32_t(now - this->ble_last_frame_) < int32_t(this->stale_timeout_);
  if (!this->links_known_ || tcp_up != this->tcp_up_ || ble_up != this->ble_up_) {
    this->links_known_ = true;
    this->tcp_up_ = tcp_up;
    this->ble_up_ = ble_up;
#ifdef USE_BINARY_SENSOR
    if (this->wifi_link_bs_ != nullptr)
      this->wifi_link_bs_->publish_state(tcp_up);
    if (this->ble_link_bs_ != nullptr)
      this->ble_link_bs_->publish_state(ble_up);
#endif
  }
  // Prefer TCP when it is delivering data; fall back to BLE.
  if (tcp_up)
    t = Transport::TCP;
  else if (ble_up)
    t = Transport::BLE;
  if (t == this->active_)
    return;
  this->active_ = t;
  static const char *const NAMES[] = {"none", "wifi", "bluetooth"};
  ESP_LOGI(TAG, "Active link: %s", NAMES[int(t)]);
#ifdef USE_BINARY_SENSOR
  if (this->connected_bs_ != nullptr)
    this->connected_bs_->publish_state(t != Transport::NONE);
#endif
#ifdef USE_TEXT_SENSOR
  if (this->transport_ts_ != nullptr)
    this->transport_ts_->publish_state(NAMES[int(t)]);
#endif
  if (t == Transport::NONE) {
    this->publish_unknown_();
  } else if (t == Transport::BLE && this->ble_writes_ == false) {
    ESP_LOGI(TAG, "Bluetooth link is read-only: target changes need Wi-Fi, or turn on \"Control over Bluetooth\"");
  }
}

void Gravity980Component::handle_status_(const Status &s, Transport via) {
  // When both links deliver, only the preferred one updates entities.
  this->update_active_();
  if (via != this->active_ && this->active_ != Transport::NONE)
    return;
  this->status_ = s;
  this->have_status_ = true;

#ifdef USE_TEXT_SENSOR
  if (this->raw_ts_ != nullptr) {
    std::string hex = hex_dump(s.raw, s.raw_len);
    if (hex != this->last_raw_) {
      this->last_raw_ = hex;
      this->raw_ts_->publish_state(hex);
    }
  }
#endif
  this->boost_step_(s);
  for (int p = 0; p < PROBE_COUNT; p++) {
    const auto &r = s.probe[p];
    const uint16_t shown = this->shown_target_f_(p, r);
#ifdef USE_SENSOR
    auto pub = [](sensor::Sensor *sn, float v) {
      if (sn == nullptr)
        return;
      float old = sn->get_raw_state();
      if (!sn->has_state() || (std::isnan(v) != std::isnan(old)) || (!std::isnan(v) && v != old))
        sn->publish_state(v);
    };
    pub(this->temp_sensors_[p], r.present ? this->to_unit_(r.temp_f) : NAN);
    pub(this->target_sensors_[p], r.has_target ? this->to_unit_(shown) : NAN);
#endif
    if (this->pending_f_[p] != 0 && r.has_target && r.target_f == this->pending_f_[p]) {
      ESP_LOGI(TAG, "Grill accepted %s target %u°F", PROBE_NAME[p], r.target_f);
      this->pending_f_[p] = 0;
    }
#ifdef USE_NUMBER
    auto *n = this->target_numbers_[p];
    if (n != nullptr && r.has_target && this->pending_f_[p] == 0) {
      float v = this->to_unit_(shown);
      if (!n->has_state() || n->state != v)
        n->publish_state(v);
    }
#endif
  }
#ifdef USE_BINARY_SENSOR
  if (this->alarm_bs_ != nullptr)
    this->alarm_bs_->publish_state(s.alarm_firing);
  if (this->fan_bs_ != nullptr)
    this->fan_bs_->publish_state(s.fan_on);
  if (this->fan_turbo_bs_ != nullptr)
    this->fan_turbo_bs_->publish_state(s.fan_turbo);
  if (this->door_bs_ != nullptr)
    this->door_bs_->publish_state(s.door_open);
#endif
  for (auto &cb : this->status_cbs_)
    cb(s);
}

void Gravity980Component::publish_unknown_() {
#ifdef USE_SENSOR
  for (auto *s : this->temp_sensors_)
    if (s != nullptr && (!s->has_state() || !std::isnan(s->get_raw_state())))
      s->publish_state(NAN);
  for (auto *s : this->target_sensors_)
    if (s != nullptr && (!s->has_state() || !std::isnan(s->get_raw_state())))
      s->publish_state(NAN);
#endif
#ifdef USE_BINARY_SENSOR
  for (auto *b : {this->door_bs_, this->fan_bs_, this->fan_turbo_bs_, this->alarm_bs_})
    if (b != nullptr)
      b->invalidate_state();
  if (this->connected_bs_ != nullptr)
    this->connected_bs_->publish_state(false);
#endif
#ifdef USE_TEXT_SENSOR
  if (this->raw_ts_ != nullptr && !this->last_raw_.empty()) {
    this->last_raw_.clear();
    this->raw_ts_->publish_state("");
  }
#endif
#ifdef USE_NUMBER
  for (auto *n : this->target_numbers_)
    if (n != nullptr && n->has_state() && !std::isnan(n->state))
      n->publish_state(NAN);
#endif
  this->have_status_ = false;
}

float Gravity980Component::reported_target(Probe probe) const {
  if (!this->have_status_ || probe >= PROBE_COUNT || !this->status_.probe[probe].has_target)
    return NAN;
  return this->to_unit_(this->shown_target_f_(probe, this->status_.probe[probe]));
}

bool Gravity980Component::request_target(Probe probe, float value) {
  if (probe >= PROBE_COUNT)
    return false;
  if (this->read_only_) {
    ESP_LOGW(TAG, "Read-only: not changing %s target", PROBE_NAME[probe]);
    return false;
  }
  if (std::isnan(value) || probe >= PROBE_COUNT)
    return false;
  uint16_t f = this->from_unit_(value);
  if (probe == PROBE_PIT && this->boosting())
    this->boost_end_("the pit target was changed");
  return this->write_target_(probe, f);
}

bool Gravity980Component::write_target_(Probe probe, uint16_t f) {
  std::vector<uint8_t> cmd;
  // Write over the link that is actually delivering data.
  bool use_tcp = this->active_ == Transport::TCP;
  bool use_ble = false;
#ifdef USE_GRAVITY980_BLE
  use_ble = !use_tcp && this->active_ == Transport::BLE && this->ble_writes_ && this->ble_ != nullptr && this->ble_->ready();
#endif
  if (!use_tcp && !use_ble) {
    ESP_LOGW(TAG, "No writable link to the grill (TCP down%s)",
             this->ble_writes_ ? ", BLE not ready" : "; turn on \"Control over Bluetooth\" to use Bluetooth");
    return false;
  }
  if (!build_target_command(probe, f, use_ble, cmd)) {
    ESP_LOGW(TAG, "%s target %u°F out of range %u-%u°F", PROBE_NAME[probe], f, TARGET_MIN_F[probe],
             TARGET_MAX_F[probe]);
    return false;
  }
  ESP_LOGI(TAG, "Set %s target %u°F via %s: %s", PROBE_NAME[probe], f, use_tcp ? "TCP" : "BLE",
           hex_dump(cmd).c_str());
  if (use_tcp) {
    this->tx_.insert(this->tx_.end(), cmd.begin(), cmd.end());
    this->tcp_flush_();
  }
#ifdef USE_GRAVITY980_BLE
  else if (!this->ble_->write(cmd)) {
    return false;
  }
#endif
  this->pending_f_[probe] = f;
  this->pending_since_[probe] = millis();
  return true;
}

std::string Gravity980Component::send_test_command(int id, int value) {
  if (!this->test_mode())
    return "command tests are off (turn on \"Command tests\")";
  if (id < 0 || id > 0xFF || value < 0 || value > 0xFFFF)
    return "id must be 0-255 and value 0-65535";
  if (id == 0x01 || id == 0x04 || id == 0x05)
    return "ids 0x01, 0x04 and 0x05 are never sent (they crash the grill's Wi-Fi side)";
  if (this->read_only_)
    return "the bridge is read-only";
  const uint32_t now = millis();
  if (this->test_last_ != 0 && now - this->test_last_ < 15000)
    return "wait 15 s between test commands";
  bool use_tcp = this->active_ == Transport::TCP, use_ble = false;
#ifdef USE_GRAVITY980_BLE
  use_ble = !use_tcp && this->active_ == Transport::BLE && this->ble_writes_ && this->ble_ != nullptr && this->ble_->ready();
#endif
  if (!use_tcp && !use_ble)
    return this->ble_writes_ ? "no writable link to the grill" : "no writable link (turn on \"Control over Bluetooth\")";
  std::vector<uint8_t> cmd;
  if (use_ble)
    cmd.insert(cmd.end(), {0x00, 0x19, 0x04, 0x00});
  cmd.insert(cmd.end(), {0xFF, uint8_t(id), uint8_t(value >> 8), uint8_t(value & 0xFF)});
  ESP_LOGW(TAG, "TEST command via %s: %s (last status: %s)", use_tcp ? "TCP" : "BLE", hex_dump(cmd).c_str(),
           this->have_status_ ? hex_dump(this->status_.raw, this->status_.raw_len).c_str() : "none");
  this->test_last_ = now ? now : 1;
  if (use_tcp) {
    this->tx_.insert(this->tx_.end(), cmd.begin(), cmd.end());
    this->tcp_flush_();
  }
#ifdef USE_GRAVITY980_BLE
  else if (!this->ble_->write(cmd)) {
    return "the Bluetooth write failed";
  }
#endif
  return "";
}

std::string Gravity980Component::start_boost(uint32_t minutes) {
  auto refuse = [this](const char *why) {
    this->boost_msg_ = std::string("Boost didn't start: ") + why;
    ESP_LOGW(TAG, "%s", this->boost_msg_.c_str());
    return std::string(why);
  };
  if (this->boosting())
    return "";
  if (this->read_only_)
    return refuse("the bridge is read-only");
  if (!this->have_status_ || !this->status_.probe[PROBE_PIT].has_target || !this->status_.probe[PROBE_PIT].present)
    return refuse("no pit reading or target from the grill");
  const uint16_t base = this->pending_f_[PROBE_PIT] ? this->pending_f_[PROBE_PIT] : this->status_.probe[PROBE_PIT].target_f;
  const uint16_t pit = this->status_.probe[PROBE_PIT].temp_f;
  if (pit + 10 >= base)
    return refuse("the pit is already at its target");
  const uint16_t to = std::min<uint16_t>(TARGET_MAX_F[PROBE_PIT], base + 100);
  if (to <= base)
    return refuse("the target is already the grill's maximum");
  if (!this->write_target_(PROBE_PIT, to))
    return refuse("no writable link to the grill (over Bluetooth, turn on \"Control over Bluetooth\")");
  const uint32_t now = millis();
  this->boost_base_f_ = base;
  this->boost_f_ = to;
  this->boost_start_ = now ? now : 1;
  this->boost_ms_ = std::max<uint32_t>(1, std::min<uint32_t>(minutes, 30)) * 60000u;
  this->boost_restore_at_ = 0;
  uint32_t b = (uint32_t(base) << 16) | to;
  this->boost_pref_.save(&b);
  global_preferences->sync();
  ESP_LOGI(TAG, "Boost: pit target %u°F -> %u°F for up to %u min", base, to, unsigned(this->boost_ms_ / 60000));
  return "";
}

void Gravity980Component::stop_boost() {
  if (!this->boosting())
    return;
  this->boost_ms_ = 0;  // restored on the next status (or below, now)
  if (this->have_status_)
    this->boost_step_(this->status_);
}

uint32_t Gravity980Component::boost_minutes_left() const {
  if (!this->boosting() || this->boost_ms_ == 0)
    return 0;
  uint32_t el = millis() - this->boost_start_;
  return el >= this->boost_ms_ ? 0 : (this->boost_ms_ - el + 59999) / 60000;
}

void Gravity980Component::boost_end_(const char *why) {
  ESP_LOGI(TAG, "Boost ended: %s", why);
  this->boost_base_f_ = this->boost_f_ = 0;
  this->boost_msg_.clear();
  uint32_t zero = 0;
  this->boost_pref_.save(&zero);
  global_preferences->sync();
}

void Gravity980Component::boost_step_(const Status &s) {
  if (!this->boosting())
    return;
  const auto &r = s.probe[PROBE_PIT];
  const uint32_t now = millis();
  if (this->pending_f_[PROBE_PIT] == this->boost_f_)
    return;  // the boost target isn't confirmed yet
  if (this->boost_restore_at_ != 0) {
    // Restoring: done when the grill reports the base target again.
    if (r.has_target && r.target_f == this->boost_base_f_)
      return this->boost_end_("the pit target is back");
    if (now - this->boost_restore_at_ < 10000)
      return;
  } else if (r.has_target && r.target_f == this->boost_base_f_ && now - this->boost_start_ < 30000) {
    // The grill never took the boosted target (it only accepts targets while cooking).
    this->boost_end_("the grill didn't take the boosted target");
    this->boost_msg_ = "Boost didn't start: the grill didn't take the higher target (start a cook on its panel)";
    return;
  } else if (!r.has_target || r.target_f != this->boost_f_) {
    // Someone set another target (the panel, the app): theirs stands.
    return this->boost_end_("the target was changed on the grill");
  }
  const bool reached = r.present && r.temp_f + 5 >= this->boost_base_f_;
  const bool over = this->boost_ms_ == 0 || now - this->boost_start_ >= this->boost_ms_;
  if (!reached && !over) {
    char b[96];
    snprintf(b, sizeof b, "Boosting to %u°F until the pit reaches %u°F (%u min left)", this->boost_f_, this->boost_base_f_,
             unsigned(this->boost_minutes_left()));
    this->boost_msg_ = b;
    return;
  }
  ESP_LOGI(TAG, "Boost: %s, putting the pit target back to %u°F", reached ? "pit reached its target" : "time's up",
           this->boost_base_f_);
  this->boost_msg_ = "Putting the pit target back";
  this->boost_ms_ = 0;
  if (this->write_target_(PROBE_PIT, this->boost_base_f_))
    this->boost_restore_at_ = now ? now : 1;  // confirmed by a later status, or retried after 10 s
}

void Gravity980Component::check_pending_() {
  const uint32_t now = millis();
  for (int p = 0; p < PROBE_COUNT; p++) {
    if (this->pending_f_[p] == 0 || now - this->pending_since_[p] < VERIFY_TIMEOUT_MS)
      continue;
    ESP_LOGW(TAG, "Grill ignored %s target %u°F (it ignores writes while idle: start a cook on the panel first)",
             PROBE_NAME[p], this->pending_f_[p]);
    this->pending_f_[p] = 0;
#ifdef USE_NUMBER
    if (this->target_numbers_[p] != nullptr)
      this->target_numbers_[p]->publish_state(this->reported_target(Probe(p)));
#endif
  }
}

// ---------------------------------------------------------------- entities

#ifdef USE_NUMBER
void Gravity980TargetNumber::control(float value) {
  if (this->parent_->request_target(this->probe_, value))
    this->publish_state(value);
  else
    this->publish_state(this->parent_->reported_target(this->probe_));
}
#endif

#ifdef USE_SWITCH
void Gravity980EnableSwitch::setup() {
  auto initial = this->get_initial_state_with_restore_mode();
  bool on = initial.has_value() ? *initial : true;
  this->parent_->set_enabled(on);
  this->publish_state(on);
}
void Gravity980EnableSwitch::write_state(bool state) {
  this->parent_->set_enabled(state);
  this->publish_state(state);
}
#endif

#ifdef USE_GRAVITY980_BLE
static const uint16_t SVC_UUID = 0xAAAA;
static const uint16_t WRITE_UUID = 0xBBB0;
static const uint16_t NOTIFY_UUID = 0xBBB1;

bool Gravity980BLE::parse_device(const esp32_ble_tracker::ESPBTDevice &device) {
  if (!this->enabled_)
    return false;
  const uint32_t now = millis();
  uint64_t a = device.address_uint64();
  this->any_adv_at_ = now;
  if (a != 0 && a == this->get_address())
    this->seen_at_ = now;
  if (a != 0 && (a == this->fixed_address_ || (this->fixed_address_ == 0 && a == this->get_address())))
    this->grill_seen_at_ = now;
  // Found by name (no fixed address): learn the address and remember it. A grill that is power-cycled can come back
  // on a different address, so while idle a match from a new address takes over once the one we know has been quiet
  // for a minute (another Gravity 980 or a look-alike nearby doesn't snatch the link while ours is around).
  if (this->fixed_address_ == 0 && a != this->get_address() &&
      (this->get_address() == 0 ||
       (this->state() == esp32_ble_tracker::ClientState::IDLE && (now - this->seen_at_) > 60000u))) {
    if (this->is_grill_(device)) {
      this->seen_at_ = this->grill_seen_at_ = now;
      auto name = device.get_name();
      ESP_LOGI(TAG, "Found grill '%s' at %02X:%02X:%02X:%02X:%02X:%02X (RSSI %d)", name.c_str(),
               unsigned((a >> 40) & 0xFF), unsigned((a >> 32) & 0xFF), unsigned((a >> 24) & 0xFF),
               unsigned((a >> 16) & 0xFF), unsigned((a >> 8) & 0xFF), unsigned(a & 0xFF), device.get_rssi());
      this->set_address(device.address_uint64());
      if (this->parent_ != nullptr)
        this->parent_->remember_grill(device.address_uint64());
    }
  }
  if (a != 0 && a == this->get_address())
    this->adv_rssi_ = device.get_rssi();
  return BLEClientBase::parse_device(device);
}

// The grill advertises as "Gravity980-…", but while it starts up (and in some firmware states) as "BLEWIFI APP", and
// always with its service 0xAAAA. Matching only the name missed a grill switched on after the bridge.
bool Gravity980BLE::is_grill_(const esp32_ble_tracker::ESPBTDevice &device) const {
  const std::string &name = device.get_name();
  if (!this->name_prefix_.empty() && name.compare(0, this->name_prefix_.size(), this->name_prefix_) == 0)
    return true;
  if (name == "BLEWIFI APP")
    return true;
  static const auto SVC = esp32_ble_tracker::ESPBTUUID::from_uint16(0xAAAA);
  for (const auto &u : device.get_service_uuids())
    if (u == SVC)
      return true;
  return false;
}

void Gravity980BLE::request_rssi() {
  if (this->state() != esp32_ble_tracker::ClientState::ESTABLISHED)
    return;
  esp_err_t err = esp_ble_gap_read_rssi(this->get_remote_bda());
  if (err != ESP_OK)
    ESP_LOGD(TAG, "BLE: read RSSI failed: %d", err);
}

void Gravity980BLE::gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
  BLEClientBase::gap_event_handler(event, param);
  if (event == ESP_GAP_BLE_READ_RSSI_COMPLETE_EVT && this->check_addr(param->read_rssi_cmpl.remote_addr) &&
      param->read_rssi_cmpl.status == ESP_BT_STATUS_SUCCESS) {
    this->link_rssi_ = param->read_rssi_cmpl.rssi;
    this->link_rssi_at_ = millis();
  }
}

bool Gravity980BLE::reconnect(const char *why) {
  auto st = this->state();
  if (st == esp32_ble_tracker::ClientState::IDLE || st == esp32_ble_tracker::ClientState::INIT)
    return true;
  if (st == esp32_ble_tracker::ClientState::DISCONNECTING)
    return true;  // ESPHome forces it idle if the stack never confirms
  ESP_LOGI(TAG, "BLE: reconnecting to the grill (%s)", why);
  this->disconnect();
  // Cancelling before the connection exists clears the address: keep a configured one.
  if (this->fixed_address_ != 0 && this->get_address() == 0)
    this->set_address(this->fixed_address_);
  // Before the stack gave us a connection id there's nothing to close: the caller restarts Bluetooth.
  return this->state() != st || st == esp32_ble_tracker::ClientState::DISCOVERED;
}

void Gravity980BLE::set_enabled(bool enabled) {
  this->enabled_ = enabled;
  this->set_auto_connect(enabled);
  if (!enabled && this->state() != esp32_ble_tracker::ClientState::IDLE)
    this->disconnect();
}

bool Gravity980BLE::gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                                        esp_ble_gattc_cb_param_t *param) {
  if (!BLEClientBase::gattc_event_handler(event, gattc_if, param))
    return false;
  switch (event) {
    case ESP_GATTC_OPEN_EVT:
      if ((param->open.status == ESP_GATT_OK || param->open.status == ESP_GATT_ALREADY_OPEN) &&
          this->state() != esp32_ble_tracker::ClientState::IDLE)
        this->parent_->on_ble_connected();
      break;
    case ESP_GATTC_DISCONNECT_EVT:
      this->notify_handle_ = this->write_handle_ = 0;
      this->parent_->on_ble_disconnected(param->disconnect.reason);
      break;
    case ESP_GATTC_CLOSE_EVT:
      this->notify_handle_ = this->write_handle_ = 0;
      this->parent_->on_ble_disconnected();
      break;
    case ESP_GATTC_SEARCH_CMPL_EVT: {
      auto *rx = this->get_characteristic(SVC_UUID, NOTIFY_UUID);
      auto *tx = this->get_characteristic(SVC_UUID, WRITE_UUID);
      if (rx == nullptr) {
        // Usually a grill that has only just been switched on: its services aren't up yet. Try again.
        ESP_LOGW(TAG, "BLE: grill service 0xAAAA/0xBBB1 not found (still starting up?); reconnecting");
        this->disconnect();
        break;
      }
      this->notify_handle_ = rx->handle;
      this->write_handle_ = tx != nullptr ? tx->handle : 0;
      auto err = this->register_for_notify(rx->handle);
      if (err != ESP_OK) {
        ESP_LOGW(TAG, "BLE register_for_notify failed: %d; reconnecting", err);
        this->disconnect();
      } else
        ESP_LOGI(TAG, "BLE subscribed to status notifications");
      break;
    }
    case ESP_GATTC_NOTIFY_EVT:
      if (param->notify.handle == this->notify_handle_ && param->notify.value_len > 0)
        this->parent_->on_ble_data(param->notify.value, param->notify.value_len);
      break;
    default:
      break;
  }
  return true;
}

bool Gravity980BLE::write(const std::vector<uint8_t> &data) {
  if (this->write_handle_ == 0)
    return false;
  // Short commands go without response (as the grill's own app does). Anything longer than one packet (the Wi-Fi
  // credentials) is written with response, which the stack splits into a long write when needed.
  bool long_write = data.size() + 3 > this->mtu_;
  if (long_write)
    ESP_LOGD(TAG, "BLE write of %u bytes (MTU %u): with response", (unsigned) data.size(), this->mtu_);
  auto err = esp_ble_gattc_write_char(this->get_gattc_if(), this->get_conn_id(), this->write_handle_, data.size(),
                                      const_cast<uint8_t *>(data.data()),
                                      long_write ? ESP_GATT_WRITE_TYPE_RSP : ESP_GATT_WRITE_TYPE_NO_RSP,
                                      ESP_GATT_AUTH_REQ_NONE);
  if (err != ESP_OK) {
    ESP_LOGW(TAG, "BLE write failed: %d", err);
    return false;
  }
  return true;
}
#endif

}  // namespace gravity980
}  // namespace esphome
