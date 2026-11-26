#pragma once
// "Does this text hold a link?" for an AI's cook program, whose step notifications go straight to the owner's phone
// (phones turn web addresses into tappable links). A link is http:/https:, anything with ://, www., or a bare domain
// such as example.co/x: labels joined by dots ending in a common top-level domain, or in any 2+ letters with a path
// after it (that's how phones decide what to make tappable). "2.5h", "225.0", "e.g." or "165F.Then" aren't.
#include <cctype>
#include <string>

namespace links {

inline bool has_link(const std::string &text) {
  std::string t;
  t.reserve(text.size());
  for (char c : text) t += char(std::tolower(static_cast<unsigned char>(c)));
  if (t.find("http:") != std::string::npos || t.find("https:") != std::string::npos ||
      t.find("://") != std::string::npos || t.find("www.") != std::string::npos)
    return true;
  auto word = [](char c) { return std::isalnum(static_cast<unsigned char>(c)) || c == '-'; };
  // Each run of word characters and dots (a domain stops at '/', a space or other punctuation).
  for (size_t i = 0; i < t.size();) {
    if (!word(t[i])) { i++; continue; }
    size_t j = i;
    while (j < t.size() && (word(t[j]) || t[j] == '.')) j++;
    std::string tok = t.substr(i, j - i);
    while (!tok.empty() && tok.back() == '.') tok.pop_back();  // a full stop isn't part of it
    const size_t dot = tok.rfind('.');
    if (dot != std::string::npos && dot > 0 && tok[dot - 1] != '.') {
      const std::string tld = tok.substr(dot + 1), before = tok.substr(0, dot);
      bool letters = tld.size() >= 2;
      for (char c : tld) letters = letters && std::isalpha(static_cast<unsigned char>(c));
      // the label before the last dot: 2+ characters with a letter in it ("e.g", "u.s" and "1.5" aren't domains)
      const size_t lp = before.rfind('.');
      const std::string label = lp == std::string::npos ? before : before.substr(lp + 1);
      bool has_alpha = false;
      for (char c : label) has_alpha = has_alpha || std::isalpha(static_cast<unsigned char>(c));
      static const char *const TLDS[] = {"com", "net", "org", "io", "co", "uk", "us", "ca", "au", "de", "fr", "nl", "eu",
                                         "info", "biz", "app", "dev", "shop", "store", "site", "online", "xyz", "me", "tv",
                                         "ly", "gl", "ai", "link", "click", "top", "gg", "to", "be", "tk", "ru", "cn", "in"};
      bool known = false;
      for (const char *k : TLDS) known = known || tld == k;
      const bool path = j < t.size() && t[j] == '/';
      if (letters && label.size() >= 2 && has_alpha && (known || path)) return true;
    }
    i = j;
  }
  return false;
}

}  // namespace links
