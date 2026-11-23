#pragma once
// The device page's PIN, portable (built into the firmware and into tests/test_core):
//  - PBKDF2-HMAC-SHA256 with a random 16-byte salt and PIN_ITERATIONS rounds: only the salt and hash are stored;
//  - constant-time comparison;
//  - lockout: after 5 wrong PINs, 30 s, then doubling up to 1 h (reset by a right PIN);
//  - sessions: 32 random bytes as hex, 12 h, renewed on use, at most 4 (the oldest is dropped).

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace pinauth {

constexpr uint32_t PIN_ITERATIONS = 20000;
constexpr size_t SALT_LEN = 16, HASH_LEN = 32;
constexpr size_t PIN_MIN = 6, PIN_MAX = 32;

using Digest = std::array<uint8_t, 32>;
Digest sha256(const uint8_t *data, size_t len);
Digest hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len);
void pbkdf2_sha256(const uint8_t *pw, size_t pw_len, const uint8_t *salt, size_t salt_len, uint32_t iterations,
                   uint8_t *out, size_t out_len);
bool equal_ct(const uint8_t *a, const uint8_t *b, size_t n);
std::string to_hex(const uint8_t *d, size_t n);

/// Stored form of a PIN (what goes in flash).
struct Stored {
  uint8_t set{0};
  uint8_t salt[SALT_LEN]{};
  uint8_t hash[HASH_LEN]{};
};

/// Why a PIN is refused as a new PIN ("" if fine).
std::string pin_problem(const std::string &pin);

class Guard {
 public:
  // random: fills a buffer with secure random bytes; now_ms: a millisecond clock.
  Guard(std::function<void(uint8_t *, size_t)> random, std::function<uint32_t()> now_ms)
      : random_(std::move(random)), now_(std::move(now_ms)) {}

  void load(const Stored &s) { this->stored_ = s; }
  const Stored &stored() const { return this->stored_; }
  bool pin_set() const { return this->stored_.set == 1; }

  /// Set (first use) or change the PIN; returns "" or why not. Changing needs the current PIN.
  std::string set_pin(const std::string &pin, const std::string &current);
  /// Clear the PIN (recovery: BOOT button or Home Assistant), and every session.
  void clear();

  /// Log in: a session token, or "" (wrong PIN or locked; see locked_for()).
  std::string login(const std::string &pin);
  /// Seconds until another try is allowed (0 = not locked).
  uint32_t locked_for() const;
  /// Is this token a live session? Renews it.
  bool check(const std::string &token);
  void logout(const std::string &token);

  /// The live sessions (to keep across a restart: an update or a crash shouldn't lock every browser out), and
  /// putting them back after one, each valid for 12 hours from then.
  std::vector<std::string> tokens() const;
  void restore(const std::vector<std::string> &tokens);
  /// Changes whenever the list of sessions does (login, logout, expiry, PIN change or clear).
  uint32_t generation() const { return this->gen_; }

 protected:
  bool verify_(const std::string &pin) const;
  std::string new_token_();

  std::function<void(uint8_t *, size_t)> random_;
  std::function<uint32_t()> now_;
  Stored stored_{};
  uint8_t failures_{0};
  uint32_t locked_until_{0};
  struct Session {
    std::string token;
    uint32_t expires;
  };
  std::vector<Session> sessions_;
  uint32_t gen_{0};
};

}  // namespace pinauth
