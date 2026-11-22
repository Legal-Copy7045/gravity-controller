#pragma once
// Char-Griller Gravity 980 stock-controller protocol: pure C++, no ESPHome
// dependencies, so it can be unit tested on a PC (see tests/).
//
// Protocol credit: github.com/grzbiet/cg980app (MIT). Summary in docs/protocol.md.

#include <cstddef>
#include <algorithm>
#include <cstdint>
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

// Command ids. ONLY the setpoint ids are ever sent by this project. 0x01
// (timer), 0x04 (power) and 0x05 (silence) are reported to crash the stock
// controller's Wi-Fi side and need re-provisioning; they are deliberately absent.
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

/// Build a setpoint command. Returns false (and builds nothing) if out of range.
/// `ble` prefixes the BLE framing `00 19 04 00`.
bool build_target_command(Probe probe, uint16_t value_f, bool ble, std::vector<uint8_t> &out);

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
