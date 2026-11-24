#pragma once
// "Local only": is a URL's host on the home network? Pure C++ (unit tested in tests/test_core.cpp).
// Local: a dotted IPv4 address in a private range (no leading zeros: lwIP would read 010 as octal), a name ending
// .local/.lan/.home/.internal/.home.arpa, or a name without a dot. Never: credentials in the URL, IPv6, a bare number.
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <string>

namespace local_url {

inline bool is_local(const std::string &url) {
  size_t a = url.find("://");
  if (a == std::string::npos)
    return false;
  a += 3;
  size_t b = url.find_first_of(":/?#", a);
  const size_t auth_end = url.find_first_of("/?#", a);
  if (url.substr(a, auth_end == std::string::npos ? std::string::npos : auth_end - a).find('@') != std::string::npos)
    return false;  // credentials in the URL: never treated as local
  if (url.find('\0') != std::string::npos)
    return false;
  std::string host = url.substr(a, b == std::string::npos ? std::string::npos : b - a);
  if (host.empty() || host[0] == '[')
    return false;  // IPv6: not treated as local
  for (auto &ch : host)
    ch = char(std::tolower(static_cast<unsigned char>(ch)));
  // All digits and dots: only a plain dotted IPv4 address with no leading zeros (lwIP reads 010 as octal, a lone
  // number as a whole address) can be judged; anything else isn't local.
  if (host.find_first_not_of("0123456789.") == std::string::npos) {
    if (std::count(host.begin(), host.end(), '.') != 3)
      return false;
    size_t s0 = 0;
    while (s0 <= host.size()) {
      size_t e = host.find('.', s0);
      std::string part = host.substr(s0, e == std::string::npos ? std::string::npos : e - s0);
      if (part.empty() || part.size() > 3 || (part.size() > 1 && part[0] == '0'))
        return false;
      if (e == std::string::npos)
        break;
      s0 = e + 1;
    }
  }
  unsigned o[4];
  char tail;
  if (std::sscanf(host.c_str(), "%u.%u.%u.%u%c", &o[0], &o[1], &o[2], &o[3], &tail) == 4) {
    if (o[0] > 255 || o[1] > 255 || o[2] > 255 || o[3] > 255)
      return false;
    return o[0] == 10 || o[0] == 127 || (o[0] == 172 && o[1] >= 16 && o[1] <= 31) || (o[0] == 192 && o[1] == 168) ||
           (o[0] == 169 && o[1] == 254);
  }
  if (host.find('.') == std::string::npos)
    return true;  // a bare name on the home network ("nas")
  for (const char *suf : {".local", ".lan", ".home", ".internal", ".home.arpa"}) {
    const size_t n = std::strlen(suf);
    if (host.size() > n && host.compare(host.size() - n, n, suf) == 0)
      return true;
  }
  return false;
}

}  // namespace local_url
