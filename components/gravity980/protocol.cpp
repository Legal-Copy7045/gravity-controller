#include "protocol.h"

#include <cstdlib>

namespace g980proto {

static uint16_t be16(const uint8_t *p) { return (uint16_t(p[0]) << 8) | p[1]; }

bool looks_like_frame_start(const uint8_t *buf, size_t len, size_t i) {
  return i + 6 <= len && (buf[i + 4] == ALARM_SILENT || buf[i + 4] == ALARM_FIRING) && buf[i + 5] == 0x00;
}

bool parse_status(const uint8_t *f, size_t len, Status &out) {
  if (len < FRAME_MIN || !looks_like_frame_start(f, len, 0))
    return false;
  static const size_t OFF[PROBE_COUNT] = {0, 6, 10};
  Status s;
  for (int p = 0; p < PROBE_COUNT; p++) {
    uint16_t cur = be16(f + OFF[p]);
    uint16_t tgt = be16(f + OFF[p] + 2);
    s.probe[p].present = cur != TEMP_ABSENT;
    s.probe[p].temp_f = cur;
    s.probe[p].has_target = tgt != TARGET_NONE;
    s.probe[p].target_f = tgt;
    // Sanity: real temperatures are < 1000 °F; anything else means misalignment.
    if (s.probe[p].present && cur > 999)
      return false;
  }
  s.alarm_firing = f[4] == ALARM_FIRING;
  s.fan_on = f[14] & FAN_ON_BIT;
  s.door_open = f[15] & DOOR_OPEN_BIT;
  s.fan_turbo = f[15] & TURBO_BIT;
  s.raw_len = len > FRAME_EXT ? FRAME_EXT : len;
  for (size_t i = 0; i < s.raw_len; i++)
    s.raw[i] = f[i];
  out = s;
  return true;
}

bool ble_status_payload(const uint8_t *data, size_t len, const uint8_t **payload, size_t *payload_len) {
  if (len < 4 || data[0] != 0x00 || data[1] != 0x19)
    return false;
  size_t n = data[2];
  if (n < FRAME_MIN || len < 4 + n)
    return false;
  *payload = data + 4;
  *payload_len = n;
  return true;
}

bool build_target_command(Probe probe, uint16_t value_f, bool ble, std::vector<uint8_t> &out) {
  if (probe >= PROBE_COUNT || value_f < TARGET_MIN_F[probe] || value_f > TARGET_MAX_F[probe])
    return false;
  out.clear();
  if (ble)
    out.insert(out.end(), {0x00, 0x19, 0x04, 0x00});
  out.insert(out.end(), {0xFF, CMD_TARGET_ID[probe], uint8_t(value_f >> 8), uint8_t(value_f & 0xFF)});
  return true;
}

size_t FrameAssembler::next_frame_len_() {
  while (buf_.size() >= FRAME_MIN) {
    if (!looks_like_frame_start(buf_.data(), buf_.size(), 0)) {
      size_t next = 1;
      while (next + 6 <= buf_.size() && !looks_like_frame_start(buf_.data(), buf_.size(), next))
        next++;
      buf_.erase(buf_.begin(), buf_.begin() + next);
      errors_++;
      continue;
    }
    if (frame_size_ == 0) {
      bool at16 = buf_.size() >= FRAME_MIN + 6 && looks_like_frame_start(buf_.data(), buf_.size(), FRAME_MIN);
      bool at20 = buf_.size() >= FRAME_EXT + 6 && looks_like_frame_start(buf_.data(), buf_.size(), FRAME_EXT);
      if (at16 && !at20) {
        // A 20-byte stream can look like a 16-byte boundary by coincidence;
        // wait for enough data to rule it out unless 20 can't match.
        if (buf_.size() < FRAME_EXT + 6 && buf_.size() < 2 * FRAME_MIN + 6)
          return 0;
        frame_size_ = FRAME_MIN;
      } else if (at20 && !at16) {
        frame_size_ = FRAME_EXT;
      } else if (at16 && at20) {
        // Ambiguous: check the next boundary for each stride.
        bool s16 = buf_.size() >= 2 * FRAME_MIN + 6 && looks_like_frame_start(buf_.data(), buf_.size(), 2 * FRAME_MIN);
        bool s20 = buf_.size() >= 2 * FRAME_EXT + 6 && looks_like_frame_start(buf_.data(), buf_.size(), 2 * FRAME_EXT);
        if (s16 && !s20)
          frame_size_ = FRAME_MIN;
        else if (s20 && !s16)
          frame_size_ = FRAME_EXT;
        else if (buf_.size() >= 2 * FRAME_EXT + 6)
          frame_size_ = FRAME_MIN;  // both plausible; 980 default
        else
          return 0;
      } else if (buf_.size() >= FRAME_EXT + 6) {
        buf_.erase(buf_.begin());
        errors_++;
        continue;
      } else {
        return 0;
      }
    }
    if (buf_.size() < frame_size_)
      return 0;
    // Validate the frame itself; on failure drop a byte and resync.
    Status tmp;
    if (!parse_status(buf_.data(), frame_size_, tmp)) {
      buf_.erase(buf_.begin());
      frame_size_ = 0;
      errors_++;
      continue;
    }
    return frame_size_;
  }
  return 0;
}

bool FrameAssembler::take_lone_frame(Status &out) {
  // Only once per buffered frame: a quiet grill must not look alive by re-delivering the same bytes.
  if (lone_delivered_ || frame_size_ != 0 || buf_.size() < FRAME_MIN)
    return false;
  if (!parse_status(buf_.data(), FRAME_MIN, out))
    return false;
  lone_delivered_ = true;
  return true;
}

bool parse_wifi_scan_result(const uint8_t *data, size_t len, WifiScanResult &out) {
  if (len < 5 || data[0] != 0x00 || data[1] != 0x10)
    return false;
  size_t n = data[4];
  if (n > WIFI_SSID_MAX || len < 5 + n + 9)
    return false;
  out.ssid.clear();
  for (size_t i = 0; i < n; i++) {
    char ch = char(data[5 + i]);
    out.ssid += (ch >= 0x20 && ch < 0x7F) ? ch : '?';
  }
  for (int i = 0; i < 6; i++)
    out.bssid[i] = data[5 + n + i];
  out.security = data[11 + n];
  out.signal = data[12 + n];
  return !out.ssid.empty();
}

bool build_wifi_credentials(const uint8_t bssid[6], const std::string &password, std::vector<uint8_t> &out) {
  if (password.size() > 63)
    return false;
  uint16_t plen = uint16_t(6 + 1 + 1 + password.size());
  out = {0x01, 0x00, uint8_t(plen & 0xFF), uint8_t(plen >> 8)};
  out.insert(out.end(), bssid, bssid + 6);
  out.push_back(0x01);  // WPA/WPA2 (provisioning uses its own encoding, not the scan's)
  out.push_back(uint8_t(password.size()));
  out.insert(out.end(), password.begin(), password.end());
  return true;
}

std::string credentials_refusal(const CredentialCheck &c) {
  if (c.peer == 0)
    return "the grill isn't connected over Bluetooth";
  if (c.fixed != 0) {
    if (c.peer != c.fixed)
      return "the device connected over Bluetooth isn't the grill set in the YAML (bluetooth: mac_address)";
  } else {
    if (c.remembered == 0 || c.peer != c.remembered)
      return "the device connected over Bluetooth isn't a known grill yet: keep it connected for 12 minutes, or set "
             "its address in the YAML (bluetooth: mac_address)";
    if (!c.remembered_at_boot && c.now - c.remembered_at < GRILL_TRUST_MS) {
      unsigned left = unsigned((GRILL_TRUST_MS - (c.now - c.remembered_at) + 59999) / 60000);
      return "this grill was only found this session: try again in " + std::to_string(left) +
             " min, or set its address in the YAML (bluetooth: mac_address)";
    }
  }
  if (!c.status_on_link)
    return "the device connected over Bluetooth hasn't sent the grill's status yet";
  if (c.rssi != 0 && c.rssi < CREDENTIALS_MIN_RSSI)
    return "the Bluetooth signal is too weak (" + std::to_string(c.rssi) +
           " dBm; move the controller closer to the grill)";
  return "";
}

GrillMatch grill_match(const std::string &name, const std::string &prefix, bool has_service) {
  if (!prefix.empty() && name.compare(0, prefix.size(), prefix) == 0) {
    const bool dash = prefix.back() == '-' ? name.size() > prefix.size()
                                           : name.size() > prefix.size() + 1 && name[prefix.size()] == '-';
    return dash ? GrillMatch::NAME : GrillMatch::WEAK;
  }
  if (name == "BLEWIFI APP" || has_service)
    return GrillMatch::WEAK;
  return GrillMatch::NONE;
}

bool may_take_over(const TakeoverCheck &t) {
  if (t.candidate == 0 || t.match == GrillMatch::NONE || t.wifi_setup_pending)
    return false;
  const uint64_t current = t.current != 0 ? t.current : t.remembered;
  if (t.candidate == current)
    return false;
  if (current == 0)
    return true;  // nothing chosen yet: the first grill heard
  if (!t.idle)
    return false;
  const uint32_t silent = t.now - t.current_seen_at;  // seen_at 0: millis() started at 0, so it counts from boot
  if (t.remembered != 0)
    return t.match == GrillMatch::NAME && silent >= TAKEOVER_SILENT_MS;
  return silent >= TAKEOVER_SILENT_NEW_MS;
}

bool grill_ip_ok(uint32_t ip, uint32_t own, uint32_t mask) {
  const bool priv = (ip >> 24) == 10 || (ip >> 20) == ((172u << 4) | 1u) || (ip >> 16) == ((192u << 8) | 168u);
  if (!priv || own == 0 || ip == own)
    return false;
  if (mask == 0)
    mask = 0xFFFFFF00u;
  if ((ip & mask) != (own & mask))
    return false;
  const uint32_t host = ip & ~mask;
  return host != 0 && host != (~mask);
}

bool statuses_disagree(const Status &a, const Status &b) {
  const auto &pa = a.probe[PROBE_PIT], &pb = b.probe[PROBE_PIT];
  if (pa.present != pb.present)
    return true;
  if (pa.present && std::abs(int(pa.temp_f) - int(pb.temp_f)) > LINK_PIT_TOLERANCE_F)
    return true;
  for (int p = 0; p < PROBE_COUNT; p++) {
    const auto &x = a.probe[p], &y = b.probe[p];
    if (x.has_target != y.has_target || (x.has_target && x.target_f != y.target_f))
      return true;
  }
  return false;
}

}  // namespace g980proto
