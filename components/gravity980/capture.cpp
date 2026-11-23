#include "capture.h"

#include <cstdio>
#include <cstring>

namespace g980proto {

// `00 19 <n> 00 <payload>` (the grill's Bluetooth framing, n = payload length): the payload; anything else as it is.
static const uint8_t *unwrap(const uint8_t *d, size_t len, size_t *plen, bool *framed) {
  *framed = len >= 5 && d[0] == 0x00 && d[1] == 0x19 && d[3] == 0x00 && size_t(d[2]) == len - 4;
  *plen = *framed ? len - 4 : len;
  return *framed ? d + 4 : d;
}

bool capture_is_credentials(const uint8_t *data, size_t len) {
  size_t n;
  bool framed;
  const uint8_t *p = unwrap(data, len, &n, &framed);
  // The credentials message is `01 00 <len lo> <len hi> <bssid×6> <security> <pass_len> <password>`. A short `01 xx`
  // that isn't `01 00` is kept (it can't hold a password worth having); anything longer or `01 00…` isn't.
  return n >= 1 && p[0] == 0x01 && (n < 2 || p[1] == 0x00 || n > 6);
}

CaptureRecord capture_write(uint32_t ms, uint16_t uuid, const uint8_t *data, size_t len) {
  CaptureRecord r;
  r.ms = ms;
  r.ev = CaptureEvent::WRITE;
  r.uuid = uuid;
  r.len = len > 0xFFFF ? 0xFFFF : uint16_t(len);
  size_t keep = len;
  if (capture_is_credentials(data, len)) {
    size_t n;
    bool framed;
    unwrap(data, len, &n, &framed);
    keep = (framed ? 4 : 0) + (n < 2 ? n : 2);  // the type bytes only: never the password
    r.redacted = CaptureRedaction::CREDENTIALS;
  } else if (len > CAPTURE_BYTES) {
    keep = 4;
    r.redacted = CaptureRedaction::LONG;
  }
  if (data == nullptr)
    keep = 0;
  r.kept = uint8_t(keep);
  if (keep)
    std::memcpy(r.data, data, keep);
  return r;
}

CaptureRecord capture_event(uint32_t ms, CaptureEvent ev) {
  CaptureRecord r;
  r.ms = ms;
  r.ev = ev;
  return r;
}

std::string capture_hex(const CaptureRecord &r) {
  std::string s;
  char b[4];
  for (size_t i = 0; i < r.kept; i++) {
    std::snprintf(b, sizeof b, i ? " %02X" : "%02X", r.data[i]);
    s += b;
  }
  if (r.kept < r.len)
    s += s.empty() ? "…" : " …";
  return s;
}

static std::string ff_guess(uint8_t id, size_t n, uint16_t v) {
  char b[64];
  if (n != 4) {
    std::snprintf(b, sizeof b, "command FF %02X of an unusual length", id);
    return b;
  }
  const char *what = nullptr;
  switch (id) {
    case 0x00:
    case 0x02:
    case 0x03: {
      const char *who = id == 0x00 ? "pit" : id == 0x02 ? "food 1" : "food 2";
      if (v == TARGET_NONE)
        std::snprintf(b, sizeof b, "%s target off", who);
      else
        std::snprintf(b, sizeof b, "%s target %u°F", who, unsigned(v));
      return b;
    }
    case 0x01: what = "timer?"; break;
    case 0x04: what = "power?"; break;
    case 0x05: what = "silence the alarm?"; break;
    case 0x06: what = "fan speed?"; break;
    default: break;
  }
  if (what != nullptr)
    std::snprintf(b, sizeof b, "%s (FF %02X, value %u)", what, id, unsigned(v));
  else
    std::snprintf(b, sizeof b, "unknown command FF %02X, value %u", id, unsigned(v));
  return b;
}

std::string capture_guess(const CaptureRecord &r) {
  switch (r.ev) {
    case CaptureEvent::CONNECT: return "phone connected";
    case CaptureEvent::DISCONNECT: return "phone disconnected";
    case CaptureEvent::SUBSCRIBE: return "the app turned status notifications on";
    case CaptureEvent::UNSUBSCRIBE: return "the app turned status notifications off";
    case CaptureEvent::REFUSED: return "another phone was turned away (one at a time)";
    case CaptureEvent::STARTED: return "capture on";
    case CaptureEvent::STOPPED: return "capture off";
    case CaptureEvent::WRITE: break;
  }
  if (r.redacted == CaptureRedaction::CREDENTIALS)
    return "(Wi-Fi credentials: not recorded)";
  if (r.uuid != CAPTURE_WRITE_UUID || r.kept == 0)
    return "";
  // The framing check needs the full length; a long write kept only its start, which is all a guess needs.
  bool framed = r.len >= 5 && r.kept >= 4 && r.data[0] == 0x00 && r.data[1] == 0x19 && r.data[3] == 0x00 &&
                size_t(r.data[2]) == size_t(r.len) - 4;
  const uint8_t *p = framed ? r.data + 4 : r.data;
  const size_t n = framed ? r.len - 4 : r.len;            // payload length as written
  const size_t have = framed ? r.kept - 4 : r.kept;       // ...and as kept
  std::string g;
  if (have >= 2 && p[0] == 0xFF)
    g = ff_guess(p[1], n, have >= 4 ? uint16_t(p[2] << 8 | p[3]) : 0);
  else if (n == 4 && have == 4 && p[0] == 0x06 && p[1] == 0 && p[2] == 0 && p[3] == 0)
    g = "Wi-Fi: join the saved network";
  else if (n == 6 && have == 6 && p[0] == 0 && p[1] == 0 && p[2] == 0x02 && p[3] == 0 && p[4] == 0x01 && p[5] == 0x02)
    g = "Wi-Fi: scan";
  if (!g.empty() && framed)
    g += " (Bluetooth framing)";
  return g;
}

static std::string stamp(uint32_t ms) {
  char b[24];
  std::snprintf(b, sizeof b, "+%u.%u s", unsigned(ms / 1000), unsigned(ms % 1000 / 100));
  return b;
}

std::string capture_line(const CaptureRecord &r) {
  std::string g = capture_guess(r);
  if (r.ev != CaptureEvent::WRITE)
    return stamp(r.ms) + " " + g;
  char b[40];
  std::snprintf(b, sizeof b, " %04X %u bytes: ", unsigned(r.uuid), unsigned(r.len));
  return stamp(r.ms) + b + capture_hex(r) + (g.empty() ? "" : " (" + g + ")");
}

void CaptureLog::add(const CaptureRecord &r) {
  this->slots_[this->head_] = r;
  this->head_ = (this->head_ + 1) % CAPTURE_SLOTS;
  if (this->count_ < CAPTURE_SLOTS)
    this->count_++;
  this->total_++;
}

std::string CaptureLog::summary(size_t max_len) const {
  std::string out;
  for (size_t i = 0; i < this->count_; i++) {
    const CaptureRecord &r = this->newest(i);
    if (r.ev != CaptureEvent::WRITE)
      continue;
    char b[16];
    std::snprintf(b, sizeof b, "+%us ", unsigned(r.ms / 1000));
    std::string g = capture_guess(r);
    std::string e = b + capture_hex(r) + (g.empty() ? "" : " = " + g);
    std::string next = out.empty() ? e : out + " | " + e;
    if (next.size() > max_len) {
      if (out.empty())  // even the newest alone is too long: cut it
        out = e.substr(0, max_len);
      break;
    }
    out = next;
  }
  return out.empty() ? "No writes from the app yet" : out;
}

static const char *ev_name(CaptureEvent e) {
  switch (e) {
    case CaptureEvent::WRITE: return "write";
    case CaptureEvent::CONNECT: return "connect";
    case CaptureEvent::DISCONNECT: return "disconnect";
    case CaptureEvent::SUBSCRIBE: return "subscribe";
    case CaptureEvent::UNSUBSCRIBE: return "unsubscribe";
    case CaptureEvent::REFUSED: return "refused";
    case CaptureEvent::STARTED: return "started";
    case CaptureEvent::STOPPED: return "stopped";
  }
  return "?";
}

// Every string here is made above from fixed ASCII text, hex and numbers (plus "°"): no quotes or backslashes to escape.
std::string CaptureLog::json() const {
  std::string out = "[";
  char b[64];
  for (size_t i = 0; i < this->count_; i++) {
    const CaptureRecord &r = this->newest(i);
    std::snprintf(b, sizeof b, "%s{\"t\":%u,\"ev\":\"%s\"", i ? "," : "", unsigned(r.ms), ev_name(r.ev));
    out += b;
    if (r.ev == CaptureEvent::WRITE) {
      std::snprintf(b, sizeof b, ",\"uuid\":\"%04X\",\"len\":%u,\"hex\":\"", unsigned(r.uuid), unsigned(r.len));
      out += b + capture_hex(r) + "\"";
      if (r.redacted != CaptureRedaction::NONE)
        out += r.redacted == CaptureRedaction::CREDENTIALS ? ",\"redacted\":\"credentials\"" : ",\"redacted\":\"long\"";
    }
    out += ",\"guess\":\"" + capture_guess(r) + "\"}";
  }
  return out + "]";
}

void FakeGrill::reset(const Status *last) {
  // The real grill's last frame only if it was on (a pit target set): one switched off would show the app an idle
  // grill, whose Power button may do nothing.
  if (last != nullptr && last->raw_len >= FRAME_MIN && last->probe[PROBE_PIT].has_target)
    std::memcpy(this->frame_, last->raw, FRAME_MIN);
  else
    std::memcpy(this->frame_, CAPTURE_DEFAULT_FRAME, FRAME_MIN);
}

bool FakeGrill::apply_write(const uint8_t *data, size_t len) {
  size_t n;
  bool framed;
  const uint8_t *p = unwrap(data, len, &n, &framed);
  if (n != 4 || p[0] != 0xFF)
    return false;
  const uint16_t v = uint16_t(p[2] << 8 | p[3]);
  for (int i = 0; i < PROBE_COUNT; i++) {
    if (p[1] != CMD_TARGET_ID[i])
      continue;
    if (v != TARGET_NONE && (v < TARGET_MIN_F[i] || v > TARGET_MAX_F[i]))
      return false;  // out of range: the real grill wouldn't take it either
    const size_t at = i == PROBE_PIT ? 2 : i == PROBE_FOOD1 ? 8 : 12;
    if (this->frame_[at] == p[2] && this->frame_[at + 1] == p[3])
      return false;
    this->frame_[at] = p[2];
    this->frame_[at + 1] = p[3];
    return true;
  }
  return false;
}

void FakeGrill::notification(uint8_t out[NOTIFY_LEN]) const {
  out[0] = 0x00;
  out[1] = 0x19;
  out[2] = uint8_t(FRAME_MIN);
  out[3] = 0x00;
  std::memcpy(out + 4, this->frame_, FRAME_MIN);
}

}  // namespace g980proto
