#pragma once
// A label photo in the AI requests. The JSON library (ArduinoJson 7) holds strings of up to 65,535 characters, and a
// photo is ~100-360 KB of base64, so it's read from the page's request and put into the provider's request by hand.
// Base64 never holds a quote or a backslash, so it needs no escaping either way.
#include <string>

namespace ai_photo {

// Stands in for the photo while the provider's request is built.
static constexpr char SLOT[] = "@@photo@@";

// The "image" value of the page's {"image": "<base64>"}, or "".
inline std::string from_request(const std::string &body) {
  size_t k = body.find("\"image\"");
  if (k == std::string::npos) return "";
  k = body.find_first_not_of(" \t\r\n", k + 7);
  if (k == std::string::npos || body[k] != ':') return "";
  k = body.find_first_not_of(" \t\r\n", k + 1);
  if (k == std::string::npos || body[k] != '"') return "";
  const size_t e = body.find('"', k + 1);
  if (e == std::string::npos) return "";
  return body.substr(k + 1, e - k - 1);
}

// A photo's base64 as the page sends it: only A-Z a-z 0-9 + / and = padding at the end, a whole number of 4-character
// groups. Checked in full (a single pass over at most ~380 KB), so nothing else ever reaches the provider's request.
inline bool is_base64(const std::string &b64) {
  if (b64.empty() || b64.size() % 4 != 0) return false;
  size_t pad = 0;
  for (size_t i = 0; i < b64.size(); i++) {
    const char c = b64[i];
    if (c == '=') {
      if (++pad > 2) return false;
      continue;
    }
    if (pad) return false;  // '=' only at the end
    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '+' || c == '/')) return false;
  }
  return true;
}

// Puts the photo where SLOT is in a built request; false if there's no SLOT.
inline bool put(std::string &request, const std::string &b64) {
  const size_t at = request.find(SLOT);
  if (at == std::string::npos) return false;
  request.replace(at, sizeof(SLOT) - 1, b64);
  return true;
}

}  // namespace ai_photo
