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

std::string Guard::set_pin(const std::string &pin, const std::string &current) {
  if (this->pin_set()) {
    if (this->locked_for() > 0) return "Too many wrong PINs: wait and try again";
    if (!this->verify_(current)) {
      this->login("");  // counts as a failure (adds to the lockout)
      return "The current PIN is wrong";
    }
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
  this->failures_ = 0;
  return "";
}

void Guard::clear() {
  this->stored_ = Stored{};
  this->sessions_.clear();
  this->gen_++;
  this->failures_ = 0;
  this->locked_until_ = 0;
  this->locked_ = false;
}

uint32_t Guard::locked_for() const {
  if (!this->locked_) return 0;  // (locked_until_ alone can't tell: millis() wraps, 0 reads as "locked" after 24.8 days)
  int32_t left = int32_t(this->locked_until_ - this->now_());
  return left > 0 ? uint32_t(left + 999) / 1000 : 0;
}

std::string Guard::new_token_() {
  uint8_t r[32];
  this->random_(r, sizeof(r));
  std::string t = to_hex(r, sizeof(r));
  if (this->sessions_.size() >= 4) this->sessions_.erase(this->sessions_.begin());
  this->sessions_.push_back({t, this->now_() + uint32_t(12UL * 3600 * 1000)});
  this->gen_++;
  return t;
}

std::string Guard::login(const std::string &pin) {
  if (this->locked_for() > 0) return "";
  this->locked_ = false;  // any lockout has passed (locked_for() was 0)
  if (!pin.empty() && this->verify_(pin)) {
    this->failures_ = 0;
    return this->new_token_();
  }
  if (this->failures_ < 255) this->failures_++;
  if (this->failures_ >= 5) {
    uint32_t secs = 30;
    for (int i = 5; i < this->failures_ && secs < 3600; i++) secs *= 2;
    this->locked_until_ = this->now_() + (secs > 3600 ? 3600 : secs) * 1000;
    this->locked_ = true;
  }
  return "";
}

bool Guard::check(const std::string &token) {
  if (token.size() != 64) return false;
  const uint32_t now = this->now_();
  for (auto it = this->sessions_.begin(); it != this->sessions_.end(); ++it) {
    if (int32_t(it->expires - now) <= 0) {
      this->sessions_.erase(it);
      this->gen_++;
      return this->check(token);
    }
    if (it->token.size() == token.size() &&
        equal_ct(reinterpret_cast<const uint8_t *>(it->token.data()), reinterpret_cast<const uint8_t *>(token.data()),
                 token.size())) {
      it->expires = now + uint32_t(12UL * 3600 * 1000);
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

void Guard::restore(const std::vector<std::string> &tokens) {
  this->sessions_.clear();
  for (auto &t : tokens) {
    if (t.size() != 64 || this->sessions_.size() >= 4) continue;
    bool hex = true;
    for (char ch : t) hex = hex && ((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'));
    if (hex) this->sessions_.push_back({t, this->now_() + uint32_t(12UL * 3600 * 1000)});
  }
}

}  // namespace pinauth
