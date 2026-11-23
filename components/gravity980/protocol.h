#pragma once
// Char-Griller Gravity 980 stock-controller protocol: pure C++, no ESPHome
// dependencies, so it can be unit tested on a PC (see tests/).
//
// Protocol credit: github.com/grzbiet/cg980app (MIT). Summary in docs/protocol.md.

#include <cstddef>
#include <algorithm>
#include <cstdint>
#include <string>
#include <vector>

namespace g980proto {

constexpr uint16_t TEMP_ABSENT = 1000;   // 0x03E8 current temp: probe not connected
constexpr uint16_t TARGET_NONE = 4096;   // 0x1000 set temp: no target
constexpr uint8_t ALARM_SILENT = 0x10;
constexpr uint8_t ALARM_FIRING = 0x00;
constexpr uint8_t FAN_ON_BIT = 0x10;     // byte 14
constexpr uint8_t DOOR_OPEN_BIT = 0x01;  // byte 15
constexpr uint8_t TURBO_BIT = 0x10;      // byte 15
constexpr size_t FRAME_MIN = 16;         // Gravity 980
constexpr size_t FRAME_EXT = 20;         // newer firmware / Auto Akorn

enum Probe : uint8_t { PROBE_PIT = 0, PROBE_FOOD1 = 1, PROBE_FOOD2 = 2, PROBE_COUNT = 3 };

// Command ids. This project sends the setpoint ids below and 0x04, the grill's
// flags (turbo, power), one flag at a time only (one_flag_command): several at
// once crashed the stock controller's Wi-Fi side. 0x01 (timer) is never sent;
// 0x05 only shows a pairing code and isn't used. See docs/protocol.md.
constexpr uint8_t CMD_TARGET_ID[PROBE_COUNT] = {0x00, 0x02, 0x03};
constexpr uint16_t TARGET_MIN_F[PROBE_COUNT] = {200, 50, 50};
constexpr uint16_t TARGET_MAX_F[PROBE_COUNT] = {700, 350, 350};

struct ProbeReading {
  bool present{false};
  uint16_t temp_f{0};
  bool has_target{false};
  uint16_t target_f{0};
};

struct Status {
  ProbeReading probe[PROBE_COUNT];
  bool alarm_firing{false};
  bool fan_on{false};
  bool fan_turbo{false};
  bool door_open{false};
  uint8_t raw[FRAME_EXT]{};
  size_t raw_len{0};
};

/// True if a status frame plausibly starts at buf[i] (alarm byte known, reserved byte zero).
bool looks_like_frame_start(const uint8_t *buf, size_t len, size_t i);

/// Parse one status frame (>= 16 bytes). Returns false if it fails sanity checks.
bool parse_status(const uint8_t *data, size_t len, Status &out);

/// Extract the status payload from a BLE notification `00 19 <len> 00 <payload>`.
/// Returns false if the notification is something else (Wi-Fi info, scan result...).
bool ble_status_payload(const uint8_t *data, size_t len, const uint8_t **payload, size_t *payload_len);

/// Command 0x04 (the grill's flags, from the Char-Griller app): four hex digits, F = leave alone, 0 or 1 = set; true
/// when exactly one digit is 0 or 1 and the rest are F (e.g. 0x0FFF power off, 0xFF1F turbo on, 0xFF0F turbo off).
inline bool one_flag_command(uint16_t v) {
  int set = 0;
  for (int i = 0; i < 4; i++) {
    uint8_t d = (v >> (12 - 4 * i)) & 0xF;
    if (d == 0xF) continue;
    if (d > 1) return false;
    set++;
  }
  return set == 1;
}

/// Build a setpoint command. Returns false (and builds nothing) if out of range.
/// `ble` prefixes the BLE framing `00 19 04 00`.
bool build_target_command(Probe probe, uint16_t value_f, bool ble, std::vector<uint8_t> &out);

// ---- Grill Wi-Fi setup over BLE (the Char-Griller app's provisioning commands; layout per cg980app's protocol.md)
// Wi-Fi scan result notification: [00][10][len lo][len hi][ssid_len][ssid][bssid6][security][signal][flags].
struct WifiScanResult {
  std::string ssid;
  uint8_t bssid[6]{};
  uint8_t security{0};
  uint8_t signal{0};
};
constexpr size_t WIFI_SSID_MAX = 32;   // longer SSIDs don't exist: such a result is rejected
constexpr size_t WIFI_SCAN_MAX = 32;   // results kept per scan
bool parse_wifi_scan_result(const uint8_t *data, size_t len, WifiScanResult &out);
// Set credentials: [01][00][len lo][len hi][bssid6][security=1 (WPA/WPA2)][pass_len][password]. False if too long.
bool build_wifi_credentials(const uint8_t bssid[6], const std::string &password, std::vector<uint8_t> &out);

// ---- Link security (pure decisions, unit tested). Anyone in Bluetooth range can advertise as a Gravity 980, and a
// Wi-Fi info notification can name any IP address: these decide whom the bridge trusts with what.
constexpr uint32_t REMEMBER_AFTER_MS = 2u * 60u * 1000u;   // a new grill is remembered after 2 min of valid status
constexpr uint32_t GRILL_TRUST_MS = 10u * 60u * 1000u;     // ...and trusted with the Wi-Fi password 10 min after that
constexpr uint32_t TAKEOVER_SILENT_MS = 10u * 60u * 1000u;  // a remembered grill silent this long may be stood in for
                                                           // (connected to, never remembered or trusted instead)
constexpr uint32_t TAKEOVER_SILENT_NEW_MS = 60000u;        // the same for one found this boot and not yet remembered
constexpr int CREDENTIALS_MIN_RSSI = -75;                  // dBm: a weaker link isn't trusted with the password
constexpr uint32_t WIFI_INFO_WINDOW_MS = 30000u;           // a grill IP is taken only this soon after we asked
constexpr int LINK_PIT_TOLERANCE_F = 15;                   // Wi-Fi and Bluetooth readings further apart: disagree
constexpr uint32_t LINK_DISAGREE_MS = 30000u;              // ...for this long: the Wi-Fi link is dropped

/// Whether the Wi-Fi password may be sent to the device connected over Bluetooth.
struct CredentialCheck {
  uint64_t peer{0};                 // address of the connected device (0 = not connected)
  uint64_t fixed{0};                // the address set in the YAML (0 = none)
  uint64_t remembered{0};           // the grill remembered in flash (0 = none)
  bool remembered_at_boot{false};   // `remembered` was already saved before this boot
  uint32_t remembered_at{0};        // millis() when it was remembered this boot
  uint32_t now{0};
  bool status_on_link{false};       // the peer has delivered valid status frames on this connection
  int rssi{0};                      // dBm, 0 = unknown
};
/// "" if allowed, otherwise why not, in words for the Wi-Fi status text.
std::string credentials_refusal(const CredentialCheck &c);

/// How an advertisement matches the grill. NAME: "<prefix>-…" (the grill's own name); WEAK: "BLEWIFI APP" (the
/// grill starting up), the bare prefix, or only the 0xAAAA service (anything can claim those).
enum class GrillMatch : uint8_t { NONE, WEAK, NAME };
GrillMatch grill_match(const std::string &name, const std::string &prefix, bool has_service);

/// Whether an advertisement from `candidate` may replace the address the client connects to (no fixed address).
struct TakeoverCheck {
  uint64_t current{0};              // the address we connect to (0 = none yet)
  uint64_t candidate{0};
  uint64_t remembered{0};           // the grill remembered in flash (0 = none)
  GrillMatch match{GrillMatch::NONE};
  bool idle{false};                 // the client isn't connected or connecting
  uint32_t now{0};
  uint32_t current_seen_at{0};      // last advertisement from `current` (0 = not since boot: counts from boot)
  bool wifi_setup_pending{false};   // a scan, join or credential send is under way
};
/// A takeover only changes where the client connects for now: the remembered grill stays remembered (only "Forget
/// the grill" replaces it), the stand-in is never trusted with the Wi-Fi password, and the remembered grill takes
/// the link back as soon as it's heard (wifi setup permitting).
bool may_take_over(const TakeoverCheck &t);

/// True if `ip` (host byte order, as reported by the grill) may be connected to: a private (RFC 1918) address in the
/// bridge's own subnet (`own`/`mask`, host order; mask 0 = /24), not the bridge itself, the network or broadcast.
bool grill_ip_ok(uint32_t ip, uint32_t own, uint32_t mask);

/// The same grill read over Wi-Fi and Bluetooth: pit more than LINK_PIT_TOLERANCE_F apart, or any target differs.
bool statuses_disagree(const Status &a, const Status &b);

/// Times a disagreement between the two links. update() returns true once it has lasted LINK_DISAGREE_MS.
class LinkCrossCheck {
 public:
  bool update(bool disagree, uint32_t now) {
    if (!disagree) {
      running_ = false;
      return false;
    }
    if (!running_) {
      running_ = true;
      since_ = now;
    }
    return now - since_ >= LINK_DISAGREE_MS;
  }
  void reset() { running_ = false; }

 protected:
  bool running_{false};
  uint32_t since_{0};
};

/// Reassembles status frames from a TCP byte stream (frames have no header).
class FrameAssembler {
 public:
  /// Feed received bytes. Calls `on_frame` for each complete frame.
  template<typename F> void feed(const uint8_t *data, size_t len, F &&on_frame) {
    if (buf_.size() + len > MAX_BUF) {
      buf_.clear();
      frame_size_ = 0;
      errors_++;
    }
    buf_.insert(buf_.end(), data, data + len);
    while (true) {
      size_t n = next_frame_len_();
      if (n == 0)
        break;
      // Copy out and consume first: the callback may reset this assembler (re-entrancy).
      uint8_t frame[FRAME_EXT];
      std::copy(buf_.begin(), buf_.begin() + n, frame);
      buf_.erase(buf_.begin(), buf_.begin() + n);
      lone_delivered_ = false;
      on_frame(frame, n);
    }
  }
  /// Return a single buffered frame when only one has arrived (stride unknown).
  bool take_lone_frame(Status &out);
  void reset() {
    buf_.clear();
    frame_size_ = 0;
    lone_delivered_ = false;
  }
  size_t frame_size() const { return frame_size_; }
  uint32_t errors() const { return errors_; }

 protected:
  size_t next_frame_len_();
  static constexpr size_t MAX_BUF = 256;
  std::vector<uint8_t> buf_;
  size_t frame_size_{0};
  uint32_t errors_{0};
  bool lone_delivered_{false};
};

inline float f_to_c(float f) { return (f - 32.0f) * 5.0f / 9.0f; }
inline float c_to_f(float c) { return c * 9.0f / 5.0f + 32.0f; }

}  // namespace g980proto
