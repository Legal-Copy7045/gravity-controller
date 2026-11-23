#pragma once
// Capture mode: the controller pretends to be the grill over Bluetooth so the Char-Griller app connects to it, and
// records what the app writes (looking for its Power and Turbo commands). This file is the part with no ESPHome or
// Bluetooth in it: the records, what they're shown as, hiding Wi-Fi passwords, and the fake grill's status. Unit
// tested in tests/test_core.cpp. The Bluetooth side is capture_ble.cpp; how to use it is in docs/protocol.md.

#include <cstddef>
#include <cstdint>
#include <string>

#include "protocol.h"

namespace g980proto {

constexpr size_t CAPTURE_SLOTS = 64;               // the last 64 records are kept
constexpr size_t CAPTURE_BYTES = 16;               // a write longer than this keeps only its first 4 bytes
constexpr uint32_t CAPTURE_MS = 10u * 60u * 1000u;  // capture mode turns itself off after 10 minutes
constexpr uint32_t CAPTURE_NOTIFY_MS = 2000;       // the fake grill's status, this often (the real one: about 1 s)
constexpr uint16_t CAPTURE_SVC_UUID = 0xAAAA;
constexpr uint16_t CAPTURE_WRITE_UUID = 0xBBB0;
constexpr uint16_t CAPTURE_NOTIFY_UUID = 0xBBB1;

enum class CaptureEvent : uint8_t {
  WRITE,        // the app wrote something
  CONNECT,      // a phone connected
  DISCONNECT,   // ...and went
  SUBSCRIBE,    // it turned status notifications on
  UNSUBSCRIBE,  // ...or off
  REFUSED,      // a second phone, turned away (one at a time)
  STARTED,      // capture mode on (advertising)
  STOPPED,      // capture mode off
};

/// Why a write's bytes weren't all kept.
enum class CaptureRedaction : uint8_t {
  NONE,
  CREDENTIALS,  // a Wi-Fi credentials message (type 0x01): only its first 2 bytes, never the password
  LONG,         // longer than CAPTURE_BYTES: only the first 4 bytes
};

struct CaptureRecord {
  uint32_t ms{0};  // since capture mode started
  CaptureEvent ev{CaptureEvent::WRITE};
  CaptureRedaction redacted{CaptureRedaction::NONE};
  uint16_t uuid{0};  // the characteristic written
  uint16_t len{0};   // how many bytes were written
  uint8_t kept{0};   // how many of them are in data
  uint8_t data[CAPTURE_BYTES]{};
};

/// A write from the app, with anything that could be a Wi-Fi password left out (see CaptureRedaction).
CaptureRecord capture_write(uint32_t ms, uint16_t uuid, const uint8_t *data, size_t len);
/// Anything else that happened (connect, subscribe...).
CaptureRecord capture_event(uint32_t ms, CaptureEvent ev);
/// True for a message that may carry the user's Wi-Fi password: type 0x01, alone or in the `00 19 <len> 00` framing.
bool capture_is_credentials(const uint8_t *data, size_t len);

/// The bytes kept, "FF 04 00 01"; "01 00 …" for a redacted write.
std::string capture_hex(const CaptureRecord &r);
/// What a write probably is ("pit target 225°F", "power? (FF 04)"), or what happened; "" when unknown.
std::string capture_guess(const CaptureRecord &r);
/// One line for the log: "+12.3 s BBB0 4 bytes: FF 04 00 01 (power? (FF 04))".
std::string capture_line(const CaptureRecord &r);

/// The last CAPTURE_SLOTS records (a ring buffer: fixed memory, the oldest drop off).
class CaptureLog {
 public:
  void add(const CaptureRecord &r);
  void clear() {
    count_ = 0;
    head_ = 0;
    total_ = 0;
  }
  size_t size() const { return count_; }
  uint32_t total() const { return total_; }  // added since the last clear (including those dropped)
  /// 0 = the newest. Only for i < size().
  const CaptureRecord &newest(size_t i) const { return slots_[(head_ + CAPTURE_SLOTS - 1 - i) % CAPTURE_SLOTS]; }
  /// The newest few writes and events, newest first, cut to whole entries within max_len (for a text sensor).
  std::string summary(size_t max_len = 255) const;
  /// JSON array of the records, newest first: {"t":ms,"ev":"write","uuid":"BBB0","len":4,"hex":"…","guess":"…"}.
  std::string json() const;

 protected:
  CaptureRecord slots_[CAPTURE_SLOTS];
  size_t head_{0};  // next slot to write
  size_t count_{0};
  uint32_t total_{0};
};

/// The default status: a real frame from a 980 that was on, idle at 65 °F with the pit target 200 °F, no food probes,
/// alarm silent, fan on, lid closed. The app's Power button probably only works while the grill looks on.
constexpr uint8_t CAPTURE_DEFAULT_FRAME[FRAME_MIN] = {0x00, 0x41, 0x00, 0xC8, 0x10, 0x00, 0x03, 0xE8,
                                                      0x10, 0x00, 0x03, 0xE8, 0x10, 0x00, 0x10, 0x00};

/// The status the fake grill sends: the bridge's last real status when that grill was on (it had a pit target), or
/// CAPTURE_DEFAULT_FRAME. Target writes from the app change it; nothing else does (an unknown command, such as a
/// power command, leaves it looking on, so it can be pressed again).
class FakeGrill {
 public:
  FakeGrill() { this->reset(nullptr); }
  /// Start from `last` (nullptr or a grill that wasn't on: the default frame).
  void reset(const Status *last);
  /// A write from the app. Returns true if it changed a target (FF 00/02/03 <hi> <lo>, in range, with or without the
  /// `00 19 04 00` framing).
  bool apply_write(const uint8_t *data, size_t len);
  /// The notification: `00 19 10 00` + the 16-byte frame.
  static constexpr size_t NOTIFY_LEN = 4 + FRAME_MIN;
  void notification(uint8_t out[NOTIFY_LEN]) const;
  const uint8_t *frame() const { return frame_; }

 protected:
  uint8_t frame_[FRAME_MIN]{};
};

}  // namespace g980proto
