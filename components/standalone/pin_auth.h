#pragma once
// The device page's PIN, portable (built into the firmware and into tests/test_core):
//  - PBKDF2-HMAC-SHA256 with a random 16-byte salt and PIN_ITERATIONS rounds: only the salt and hash are stored;
//  - constant-time comparison;
//  - lockout per client (its IP address): after 5 wrong PINs, 30 s, then doubling up to 1 h (reset by a right PIN
//    from that client, forgotten a day after its last wrong one), so one machine on the Wi-Fi can't lock everyone
//    out; plus a backstop for everyone together: 50 wrong PINs an hour (each forgiven after 72 s);
//  - a PIN that can't be one (empty, too short or too long) is refused without hashing or counting;
//  - the first PIN: only within 15 minutes of the controller being powered on or of the PIN being cleared (BOOT
//    button, Home Assistant), so whoever happens to be on the Wi-Fi later can't claim the page. Without a PIN the page stays
//    open to changes, as before (the owner's choice; keys and settings still need one);
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
constexpr uint32_t FIRST_PIN_MS = 15UL * 60 * 1000;  // the first PIN's window
constexpr size_t CLIENTS = 8;                          // clients with wrong PINs remembered (the least recent goes)
constexpr uint32_t GLOBAL_MAX = 50;                    // wrong PINs an hour from everyone before everyone waits
constexpr uint32_t GLOBAL_LEAK_MS = 3600UL * 1000 / GLOBAL_MAX;
constexpr uint32_t FORGET_MS = 24UL * 3600 * 1000;     // a client's wrong PINs are forgotten after a quiet day
extern const char *const FIRST_PIN_CLOSED;             // why a first PIN is refused outside its window

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

/// Called every 1,000 PBKDF2 rounds when set (the controller: a 1-tick sleep, so hashing never starves other tasks).
extern void (*pbkdf2_yield)();

/// Why a PIN is refused as a new PIN ("" if fine).
std::string pin_problem(const std::string &pin);
/// Could this be a PIN at all? (Anything else is refused before hashing and doesn't count as a wrong PIN.)
inline bool well_formed(const std::string &pin) { return pin.size() >= PIN_MIN && pin.size() <= PIN_MAX; }

class Guard {
 public:
  // random: fills a buffer with secure random bytes; now_ms: a millisecond clock.
  Guard(std::function<void(uint8_t *, size_t)> random, std::function<uint32_t()> now_ms)
      : random_(std::move(random)), now_(std::move(now_ms)) {
    this->open_first_pin_();
  }

  void load(const Stored &s) { this->stored_ = s; }
  const Stored &stored() const { return this->stored_; }
  bool pin_set() const { return this->stored_.set == 1; }

  /// Set (first use, within its window) or change the PIN; returns "" or why not. Changing needs the current PIN.
  /// client: who's asking (an IP address), for the lockout.
  std::string set_pin(const std::string &pin, const std::string &current, const std::string &client = "");
  /// Clear the PIN (recovery: BOOT button or Home Assistant), every session and every lockout; opens the first
  /// PIN's window again.
  void clear();

  /// Log in: a session token, or "" (wrong PIN, not a PIN at all, or locked; see locked_for()).
  std::string login(const std::string &pin, const std::string &client = "");
  /// Seconds until this client may try again (0 = not locked): its own lockout or everyone's.
  uint32_t locked_for(const std::string &client = "") const;
  /// Seconds left to set the first PIN (0 = a PIN is set, or the window has closed).
  uint32_t first_pin_for() const;
  /// No window for this start (a software restart: anyone could ask for one while there's no PIN).
  void close_first_pin() { this->first_open_ = false; }
  /// Housekeeping, called often (the controller's main loop): closes the first PIN's window and ends or forgets
  /// lockouts on time, so a clock that wraps (millis(), 49.7 days) can't bring an old one back.
  void tick();
  /// Is this token a live session? Renews it.
  bool check(const std::string &token);
  void logout(const std::string &token);
  /// A session for the browser that just set the PIN (saves hashing the PIN a second time).
  std::string new_session() { return this->pin_set() ? this->new_token_() : std::string(); }

  /// The live sessions (to keep across a restart: an update or a crash shouldn't lock every browser out), and
  /// putting them back after one, each valid for 12 hours from then.
  std::vector<std::string> tokens() const;
  void restore(const std::vector<std::string> &tokens);
  /// Changes whenever the list of sessions does (login, logout, expiry, PIN change or clear).
  uint32_t generation() const { return this->gen_; }

 protected:
  bool verify_(const std::string &pin) const;
  std::string new_token_();
  void open_first_pin_();
  struct Client {
    std::string ip;
    uint8_t failures;
    bool locked;  // (locked_until alone can't tell: millis() wraps)
    uint32_t locked_until, last;
  };
  Client &client_(const std::string &ip, uint32_t now);
  const Client *find_(const std::string &ip) const;
  void fail_(const std::string &ip);
  void forget_(const std::string &ip);

  std::function<void(uint8_t *, size_t)> random_;
  std::function<uint32_t()> now_;
  Stored stored_{};
  std::vector<Client> clients_;
  bool global_on_{false};
  uint32_t global_until_{0};  // when everyone's wrong PINs are all forgiven (a leaky bucket, GLOBAL_LEAK_MS each)
  bool first_open_{false};
  uint32_t first_from_{0};
  struct Session {
    std::string token;
    uint32_t expires;
  };
  std::vector<Session> sessions_;
  uint32_t gen_{0};
};

}  // namespace pinauth
