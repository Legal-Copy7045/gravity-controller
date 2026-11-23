#include "pin_auth.h"

#include <cstring>

namespace pinauth {

namespace {
constexpr uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98,
    0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8,
    0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2};
inline uint32_t ror(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

struct Sha {
  uint32_t h[8]{0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  uint8_t buf[64]{};
  size_t n{0};
  uint64_t bits{0};
  void block(const uint8_t *p) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++)
      w[i] = uint32_t(p[4 * i]) << 24 | uint32_t(p[4 * i + 1]) << 16 | uint32_t(p[4 * i + 2]) << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
      uint32_t s0 = ror(w[i - 15], 7) ^ ror(w[i - 15], 18) ^ (w[i - 15] >> 3);
      uint32_t s1 = ror(w[i - 2], 17) ^ ror(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++) {
      uint32_t t1 = hh + (ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
      uint32_t t2 = (ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  void update(const uint8_t *p, size_t len) {
    bits += uint64_t(len) * 8;
    while (len--) {
      buf[n++] = *p++;
      if (n == 64) { block(buf); n = 0; }
    }
  }
  Digest final() {
    uint64_t b = bits;
    uint8_t one = 0x80, zero = 0;
    update(&one, 1);
    while (n != 56) update(&zero, 1);
    uint8_t len[8];
    for (int i = 0; i < 8; i++) len[i] = uint8_t(b >> (56 - 8 * i));
    update(len, 8);
    Digest d;
    for (int i = 0; i < 8; i++)
      for (int j = 0; j < 4; j++) d[4 * i + j] = uint8_t(h[i] >> (24 - 8 * j));
    return d;
  }
};
}  // namespace

Digest sha256(const uint8_t *data, size_t len) {
  Sha s;
  s.update(data, len);
  return s.final();
}

Digest hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len) {
  uint8_t k[64]{};
  if (key_len > 64) {
    Digest d = sha256(key, key_len);
    std::memcpy(k, d.data(), 32);
  } else {
    std::memcpy(k, key, key_len);
  }
  uint8_t ipad[64], opad[64];
  for (int i = 0; i < 64; i++) { ipad[i] = k[i] ^ 0x36; opad[i] = k[i] ^ 0x5c; }
  Sha in;
  in.update(ipad, 64);
  in.update(msg, msg_len);
  Digest inner = in.final();
  Sha out;
  out.update(opad, 64);
  out.update(inner.data(), 32);
  return out.final();
}

void (*pbkdf2_yield)() = nullptr;

void pbkdf2_sha256(const uint8_t *pw, size_t pw_len, const uint8_t *salt, size_t salt_len, uint32_t iterations,
                   uint8_t *out, size_t out_len) {
  std::vector<uint8_t> msg(salt, salt + salt_len);
  msg.resize(salt_len + 4);
  for (uint32_t blk = 1; out_len > 0; blk++) {
    msg[salt_len] = uint8_t(blk >> 24); msg[salt_len + 1] = uint8_t(blk >> 16);
    msg[salt_len + 2] = uint8_t(blk >> 8); msg[salt_len + 3] = uint8_t(blk);
    Digest u = hmac_sha256(pw, pw_len, msg.data(), msg.size()), t = u;
    for (uint32_t i = 1; i < iterations; i++) {
      u = hmac_sha256(pw, pw_len, u.data(), 32);
      if (pbkdf2_yield != nullptr && (i % 1000) == 0) pbkdf2_yield();
      for (int j = 0; j < 32; j++) t[j] ^= u[j];
    }
    size_t n = out_len < 32 ? out_len : 32;
    std::memcpy(out, t.data(), n);
    out += n;
    out_len -= n;
  }
}

bool equal_ct(const uint8_t *a, const uint8_t *b, size_t n) {
  uint8_t d = 0;
  for (size_t i = 0; i < n; i++) d |= a[i] ^ b[i];
  return d == 0;
}

std::string to_hex(const uint8_t *d, size_t n) {
  static const char *H = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; i++) { s += H[d[i] >> 4]; s += H[d[i] & 15]; }
  return s;
}

std::string pin_problem(const std::string &pin) {
  if (pin.size() < PIN_MIN) return "Use at least 6 characters";
  if (pin.size() > PIN_MAX) return "Use at most 32 characters";
  bool all_same = true, sequence = true;
  for (size_t i = 1; i < pin.size(); i++) {
    if (pin[i] != pin[0]) all_same = false;
    if (pin[i] != pin[i - 1] + 1 && pin[i] != pin[i - 1] - 1) sequence = false;
  }
  if (all_same || sequence) return "Too easy to guess (repeated or in sequence)";
  return "";
}

bool Guard::verify_(const std::string &pin) const {
  if (!this->pin_set()) return false;
  uint8_t h[HASH_LEN];
  pbkdf2_sha256(reinterpret_cast<const uint8_t *>(pin.data()), pin.size(), this->stored_.salt, SALT_LEN,
                PIN_ITERATIONS, h, HASH_LEN);
  return equal_ct(h, this->stored_.hash, HASH_LEN);
}

const char *const FIRST_PIN_CLOSED =
    "Power the controller off and on (or hold its BOOT button 10 s), then set the PIN within 15 minutes";

void Guard::open_first_pin_() {
  this->first_open_ = true;
  this->first_from_ = this->now_();
}

uint32_t Guard::first_pin_for() const {
  if (this->pin_set() || !this->first_open_) return 0;
  const uint32_t gone = this->now_() - this->first_from_;
  return gone < FIRST_PIN_MS ? (FIRST_PIN_MS - gone + 999) / 1000 : 0;
}

std::string Guard::set_pin(const std::string &pin, const std::string &current, const std::string &client) {
  if (this->pin_set()) {
    if (this->locked_for(client) > 0) return "Too many wrong PINs: wait and try again";
    if (!well_formed(current)) return "Enter the current PIN";
    if (!this->verify_(current)) {
      this->fail_(client);  // counts as a wrong PIN (adds to the lockout)
      return "The current PIN is wrong";
    }
  } else if (this->first_pin_for() == 0) {
    return FIRST_PIN_CLOSED;  // anyone on the Wi-Fi could otherwise claim the page
  }
  std::string why = pin_problem(pin);
  if (!why.empty()) return why;
  Stored s;
  s.set = 1;
  this->random_(s.salt, SALT_LEN);
  pbkdf2_sha256(reinterpret_cast<const uint8_t *>(pin.data()), pin.size(), s.salt, SALT_LEN, PIN_ITERATIONS, s.hash,
                HASH_LEN);
  this->stored_ = s;
  this->sessions_.clear();  // a new PIN logs everyone out
  this->gen_++;
  this->first_open_ = false;
  this->forget_(client);
  return "";
}

void Guard::clear() {
  this->stored_ = Stored{};
  this->sessions_.clear();
  this->gen_++;
  this->clients_.clear();
  this->global_on_ = false;
  this->overflow_ = false;
  this->open_first_pin_();
}

uint32_t Guard::locked_for(const std::string &client) const {
  const uint32_t now = this->now_();
  int64_t left = 0;
  const Client *c = this->find_(client);
  if (c != nullptr && c->locked) left = int32_t(c->locked_until - now);
  // The backstop: while GLOBAL_MAX or more wrong PINs are outstanding, a client with wrong PINs of its own waits; one
  // without any (the owner) doesn't, unless guessers have overflowed the client list (then nobody can be told apart).
  if (this->global_on_ && (this->overflow_ || (c != nullptr && c->failures > 0))) {
    int64_t g = int64_t(int32_t(this->global_until_ - now)) - int64_t(GLOBAL_MAX - 1) * GLOBAL_LEAK_MS;
    if (g > left) left = g;
  }
  return left > 0 ? uint32_t((left + 999) / 1000) : 0;
}

void Guard::tick() {
  const uint32_t now = this->now_();
  if (this->first_open_ && (this->pin_set() || now - this->first_from_ >= FIRST_PIN_MS)) this->first_open_ = false;
  if (this->global_on_ && int32_t(this->global_until_ - now) <= 0) this->global_on_ = this->overflow_ = false;
  for (auto it = this->clients_.begin(); it != this->clients_.end();) {
    if (it->locked && int32_t(it->locked_until - now) <= 0) it->locked = false;
    if (!it->locked && now - it->last >= FORGET_MS) it = this->clients_.erase(it);
    else ++it;
  }
  this->prune_();
}

void Guard::prune_() {
  const uint32_t now = this->now_(), epoch = this->epoch_now_();
  for (auto it = this->sessions_.begin(); it != this->sessions_.end();) {
    if (this->expired_(*it, now, epoch)) {
      it = this->sessions_.erase(it);
      this->gen_++;
      continue;
    }
    if (epoch != 0 && it->epoch_expires == 0)  // the clock is set now: the expiry on it, for after a restart
      it->epoch_expires = epoch + (it->life - (now - it->from)) / 1000;
    ++it;
  }
}

const Guard::Client *Guard::find_(const std::string &ip) const {
  for (auto &c : this->clients_)
    if (c.ip == ip) return &c;
  return nullptr;
}

Guard::Client &Guard::client_(const std::string &ip, uint32_t now) {
  for (auto &c : this->clients_)
    if (c.ip == ip) return c;
  if (this->clients_.size() >= CLIENTS) {
    // Make room: the least recent client, preferring one that isn't locked out (a locked one stays locked).
    auto worst = this->clients_.begin();
    for (auto it = this->clients_.begin(); it != this->clients_.end(); ++it) {
      bool better = it->locked != worst->locked ? !it->locked : now - it->last > now - worst->last;
      if (better) worst = it;
    }
    this->clients_.erase(worst);
    if (this->global_on_) this->overflow_ = true;  // a guesser forgotten: it could come back as a "new" client
  }
  this->clients_.push_back({ip, 0, false, 0, now});
  return this->clients_.back();
}

void Guard::forget_(const std::string &ip) {
  for (auto it = this->clients_.begin(); it != this->clients_.end(); ++it)
    if (it->ip == ip) { this->clients_.erase(it); return; }
}

void Guard::fail_(const std::string &ip) {
  const uint32_t now = this->now_();
  if (!this->global_on_ || int32_t(this->global_until_ - now) <= 0) {
    this->global_until_ = now;
    this->overflow_ = false;
  }
  this->global_until_ += GLOBAL_LEAK_MS;
  this->global_on_ = true;
  Client &c = this->client_(ip, now);
  if (c.locked && int32_t(c.locked_until - now) <= 0) c.locked = false;
  if (!c.locked && now - c.last >= FORGET_MS) c.failures = 0;  // a quiet day since its last wrong PIN
  c.last = now;
  if (c.failures < 255) c.failures++;
  if (c.failures >= 5) {
    uint32_t secs = 30;
    for (int i = 5; i < c.failures && secs < 3600; i++) secs *= 2;
    c.locked_until = now + (secs > 3600 ? 3600 : secs) * 1000;
    c.locked = true;
  }
}

std::string Guard::new_token_() {
  uint8_t r[32];
  this->random_(r, sizeof(r));
  std::string t = to_hex(r, sizeof(r));
  if (this->sessions_.size() >= 4) this->sessions_.erase(this->sessions_.begin());
  const uint32_t epoch = this->epoch_now_();
  this->sessions_.push_back({t, this->now_(), SESSION_MS, epoch ? epoch + SESSION_MS / 1000 : 0});
  this->gen_++;
  return t;
}

std::string Guard::login(const std::string &pin, const std::string &client) {
  if (!well_formed(pin) || !this->pin_set()) return "";  // not a PIN, or nothing to log in to: not counted
  if (this->locked_for(client) > 0) return "";
  if (this->verify_(pin)) {
    this->forget_(client);
    return this->new_token_();
  }
  this->fail_(client);
  return "";
}

bool Guard::check(const std::string &token) {
  if (token.size() != 64) return false;
  this->prune_();
  const uint32_t now = this->now_(), epoch = this->epoch_now_();
  for (auto &s : this->sessions_) {
    if (s.token.size() == token.size() &&
        equal_ct(reinterpret_cast<const uint8_t *>(s.token.data()), reinterpret_cast<const uint8_t *>(token.data()),
                 token.size())) {
      s.from = now;  // renewed: 12 h from now
      s.life = SESSION_MS;
      s.epoch_expires = epoch ? epoch + SESSION_MS / 1000 : 0;
      return true;
    }
  }
  return false;
}

void Guard::logout(const std::string &token) {
  for (auto it = this->sessions_.begin(); it != this->sessions_.end(); ++it)
    if (it->token == token) { this->sessions_.erase(it); this->gen_++; return; }
}

std::vector<std::string> Guard::tokens() const {
  std::vector<std::string> out;
  for (auto &s : this->sessions_) out.push_back(s.token);
  return out;
}

std::vector<SavedSession> Guard::saved() const {
  std::vector<SavedSession> out;
  const uint32_t now = this->now_(), epoch = this->epoch_now_();
  for (auto &s : this->sessions_) {
    if (this->expired_(s, now, epoch)) continue;
    const uint32_t left_s = (s.life - (now - s.from)) / 1000;
    if (left_s == 0) continue;
    out.push_back({s.token, left_s, epoch ? epoch + left_s : s.epoch_expires});
  }
  return out;
}

void Guard::restore(const std::vector<SavedSession> &sessions) {
  this->sessions_.clear();
  const uint32_t now = this->now_();
  for (auto &v : sessions) {
    if (v.token.size() != 64 || v.left_s == 0 || this->sessions_.size() >= 4) continue;
    bool hex = true;
    for (char ch : v.token) hex = hex && ((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'));
    if (!hex) continue;
    // Only the time it had left (never more than a session's life): a restart doesn't extend it.
    const uint32_t life = v.left_s >= SESSION_MS / 1000 ? SESSION_MS : v.left_s * 1000;
    this->sessions_.push_back({v.token, now, life, v.epoch_expires});
  }
  this->gen_++;
  this->prune_();  // already past its expiry on the clock (the controller was off): gone
}

void Guard::restore(const std::vector<std::string> &tokens, uint32_t left_s) {
  std::vector<SavedSession> v;
  for (auto &t : tokens) v.push_back({t, left_s, 0});
  this->restore(v);
}

}  // namespace pinauth
