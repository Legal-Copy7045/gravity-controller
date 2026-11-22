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

#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

namespace esphome {
namespace gravity980 {

static const char *const TAG = "gravity980";

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

void Gravity980Component::setup() { this->publish_unknown_(); }

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
  if (this->ble_connected_ && int32_t(now - this->ble_last_frame_) > int32_t(this->stale_timeout_) &&
      int32_t(now - this->ble_warned_) > 60000) {
    ESP_LOGW(TAG, "BLE connected but no status notifications");
    this->ble_warned_ = now;
  }
  this->check_pending_();
  this->update_active_();
}

// ---------------------------------------------------------------- TCP

void Gravity980Component::tcp_start_connect_() {
  this->tcp_last_attempt_ = millis() | 1;
  struct sockaddr_in addr {};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(this->port_);
  const std::string &host = this->host_for_tcp_();
  if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
    // Hostname: resolving blocks the main loop, so do it rarely (an IP address / DHCP reservation is better).
    if (this->resolved_host_ == host && this->resolved_addr_ != 0 &&
        int32_t(millis() - this->resolved_at_) < 600000) {
      addr.sin_addr.s_addr = this->resolved_addr_;
      goto have_addr;
    }
    if (this->resolved_host_ == host && int32_t(millis() - this->resolved_at_) < 60000)
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
  if (this->tcp_state_ == TcpState::CONNECTED)
    ESP_LOGW(TAG, "TCP disconnected: %s", reason);
  else if (this->tcp_state_ == TcpState::CONNECTING)
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

void Gravity980Component::on_ble_disconnected() {
  this->ble_connected_ = false;
  this->ble_got_frame_ = false;
  ESP_LOGI(TAG, "BLE disconnected");
  this->update_active_();
}

// ---------------------------------------------------------------- common

void Gravity980Component::update_active_() {
  const uint32_t now = millis();
  Transport t = Transport::NONE;
  // Prefer TCP when it is delivering data; fall back to BLE.
  if (this->tcp_state_ == TcpState::CONNECTED && this->tcp_got_frame_ &&
      int32_t(now - this->tcp_last_frame_) < int32_t(this->stale_timeout_))
    t = Transport::TCP;
  else if (this->ble_connected_ && this->ble_got_frame_ &&
           int32_t(now - this->ble_last_frame_) < int32_t(this->stale_timeout_))
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
  for (int p = 0; p < PROBE_COUNT; p++) {
    const auto &r = s.probe[p];
#ifdef USE_SENSOR
    auto pub = [](sensor::Sensor *sn, float v) {
      if (sn == nullptr)
        return;
      float old = sn->get_raw_state();
      if (!sn->has_state() || (std::isnan(v) != std::isnan(old)) || (!std::isnan(v) && v != old))
        sn->publish_state(v);
    };
    pub(this->temp_sensors_[p], r.present ? this->to_unit_(r.temp_f) : NAN);
    pub(this->target_sensors_[p], r.has_target ? this->to_unit_(r.target_f) : NAN);
#endif
    if (this->pending_f_[p] != 0 && r.has_target && r.target_f == this->pending_f_[p]) {
      ESP_LOGI(TAG, "Grill accepted %s target %u°F", PROBE_NAME[p], r.target_f);
      this->pending_f_[p] = 0;
    }
#ifdef USE_NUMBER
    auto *n = this->target_numbers_[p];
    if (n != nullptr && r.has_target && this->pending_f_[p] == 0) {
      float v = this->to_unit_(r.target_f);
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
  return this->to_unit_(this->status_.probe[probe].target_f);
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
  if (this->fixed_address_ == 0 && this->get_address() == 0) {
    auto name = device.get_name();
    if (name.size() >= this->name_prefix_.size() &&
        strncmp(name.c_str(), this->name_prefix_.c_str(), this->name_prefix_.size()) == 0) {
      uint64_t a = device.address_uint64();
      ESP_LOGI(TAG, "Found grill '%s' at %02X:%02X:%02X:%02X:%02X:%02X (RSSI %d)", name.c_str(),
               unsigned((a >> 40) & 0xFF), unsigned((a >> 32) & 0xFF), unsigned((a >> 24) & 0xFF),
               unsigned((a >> 16) & 0xFF), unsigned((a >> 8) & 0xFF), unsigned(a & 0xFF), device.get_rssi());
      this->set_address(device.address_uint64());
    }
  }
  return BLEClientBase::parse_device(device);
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
    case ESP_GATTC_CLOSE_EVT:
      this->notify_handle_ = this->write_handle_ = 0;
      this->parent_->on_ble_disconnected();
      break;
    case ESP_GATTC_SEARCH_CMPL_EVT: {
      auto *rx = this->get_characteristic(SVC_UUID, NOTIFY_UUID);
      auto *tx = this->get_characteristic(SVC_UUID, WRITE_UUID);
      if (rx == nullptr) {
        ESP_LOGW(TAG, "BLE: grill service 0xAAAA/0xBBB1 not found. Dump services with log level VERBOSE.");
        break;
      }
      this->notify_handle_ = rx->handle;
      this->write_handle_ = tx != nullptr ? tx->handle : 0;
      auto err = this->register_for_notify(rx->handle);
      if (err != ESP_OK)
        ESP_LOGW(TAG, "BLE register_for_notify failed: %d", err);
      else
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
