#include <algorithm>
#include "program.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>

namespace cook {

namespace {

float to_c(float v, bool f) { return f ? (v - 32.0f) * 5.0f / 9.0f : v; }
float from_c(float c, bool f) { return f ? c * 9.0f / 5.0f + 32.0f : c; }

std::string lower(std::string s) {
  for (auto &ch : s)
    ch = char(std::tolower((unsigned char) ch));
  return s;
}

// Tokenizer: words, numbers (with optional unit suffix), operators, quoted strings.
struct Tok {
  enum Kind { WORD, NUM, OP, STR, END } kind;
  std::string text;
  float num{0};
  char unit{0};  // 'F', 'C', 'm', 'h' or 0
};

bool tokenize(const std::string &s, std::vector<Tok> &out, std::string &err) {
  size_t i = 0;
  while (i < s.size()) {
    char c = s[i];
    if (std::isspace((unsigned char) c) || c == ',') {
      i++;
      continue;
    }
    if (c == '"' || c == '\'') {
      size_t j = s.find(c, i + 1);
      if (j == std::string::npos) {
        err = "unterminated quote";
        return false;
      }
      out.push_back({Tok::STR, s.substr(i + 1, j - i - 1)});
      i = j + 1;
      continue;
    }
    if (c == '>' || c == '<' || c == '=') {
      std::string op(1, c);
      if (i + 1 < s.size() && s[i + 1] == '=') {
        op += '=';
        i++;
      }
      i++;
      if (op == ">")
        op = ">=";
      if (op == "<")
        op = "<=";
      out.push_back({Tok::OP, op});
      continue;
    }
    if (std::isdigit((unsigned char) c) || c == '.') {
      size_t j = i;
      while (j < s.size() && (std::isdigit((unsigned char) s[j]) || s[j] == '.' || s[j] == ':'))
        j++;
      Tok t{Tok::NUM, s.substr(i, j - i)};
      if (t.text.find(':') != std::string::npos) {
        int hh = 0, mm = 0;
        if (std::sscanf(t.text.c_str(), "%d:%d", &hh, &mm) != 2 || hh > 23 || mm > 59) {
          err = "bad time '" + t.text + "'";
          return false;
        }
        t.num = float(hh * 60 + mm);
        t.unit = 't';
      } else {
        t.num = std::strtof(t.text.c_str(), nullptr);
      }
      // Optional unit suffix (°, F, C, m, min, h), attached or after one space.
      {
        size_t k = j;
        while (k < s.size() && s[k] == ' ')
          k++;
        size_t e = k;
        if (e < s.size() && (unsigned char) s[e] == 0xC2 && e + 1 < s.size() && (unsigned char) s[e + 1] == 0xB0)
          e += 2;
        size_t w = e;
        while (w < s.size() && std::isalpha((unsigned char) s[w]))
          w++;
        std::string word = lower(s.substr(e, w - e));
        static const char *const UNITS[] = {"f", "c", "m", "min", "mins", "minutes", "h", "hr", "hrs", "hour", "hours"};
        bool unit_word = false;
        for (auto *u : UNITS)
          if (word == u)
            unit_word = true;
        if (k > j && (unit_word || e > k))
          j = e;  // skip the space (and degree sign) so the unit attaches
      }
      if (j < s.size() && (unsigned char) s[j] == 0xC2 && j + 1 < s.size() && (unsigned char) s[j + 1] == 0xB0)
        j += 2;  // UTF-8 degree sign
      if (j < s.size() && std::isalpha((unsigned char) s[j])) {
        size_t k = j;
        while (k < s.size() && std::isalpha((unsigned char) s[k]))
          k++;
        std::string u = lower(s.substr(j, k - j));
        if (u == "f")
          t.unit = 'F';
        else if (u == "c")
          t.unit = 'C';
        else if (u == "m" || u == "min" || u == "mins" || u == "minutes")
          t.unit = 'm';
        else if (u == "h" || u == "hr" || u == "hrs" || u == "hour" || u == "hours")
          t.unit = 'h';
        else {
          err = "unknown unit '" + u + "'";
          return false;
        }
        j = k;
      }
      out.push_back(t);
      i = j;
      continue;
    }
    if (std::isalpha((unsigned char) c) || c == '_') {
      size_t j = i;
      while (j < s.size() && (std::isalnum((unsigned char) s[j]) || s[j] == '_'))
        j++;
      out.push_back({Tok::WORD, lower(s.substr(i, j - i))});
      i = j;
      continue;
    }
    err = std::string("unexpected '") + c + "'";
    return false;
  }
  out.push_back({Tok::END, ""});
  return true;
}

int probe_idx(const std::string &w, const std::vector<std::string> &probes) {
  for (size_t i = 0; i < probes.size(); i++)
    if (lower(probes[i]) == w)
      return int(i);
  return -1;
}

bool is_temp_tok(const Tok &t) { return t.kind == Tok::NUM && (t.unit == 0 || t.unit == 'F' || t.unit == 'C'); }

float temp_value(const Tok &t, bool f) {
  if (t.unit == 'F')
    return to_c(t.num, true);
  if (t.unit == 'C')
    return t.num;
  return to_c(t.num, f);
}

bool duration_min(const Tok &t, float &out) {
  if (t.kind != Tok::NUM || t.unit == 'F' || t.unit == 'C' || t.unit == 't')
    return false;
  out = t.unit == 'h' ? t.num * 60.0f : t.num;  // default minutes
  return true;
}

bool parse_step(const std::string &text, const std::vector<std::string> &probes, bool f, Step &step,
                std::string &err) {
  std::vector<Tok> t;
  if (!tokenize(text, t, err))
    return false;
  size_t i = 0;
  auto need_num = [&](const char *what) -> bool {
    if (!is_temp_tok(t[i])) {
      err = std::string("expected a temperature after '") + what + "'";
      return false;
    }
    return true;
  };
  bool any_action = false;
  // Actions
  while (t[i].kind == Tok::WORD && t[i].text != "until") {
    const std::string &w = t[i].text;
    if (w == "pit" || w == "hold" || w == "set") {
      bool hold = w == "hold";
      i++;
      if (t[i].kind == Tok::WORD && t[i].text == "to")
        i++;
      if (!need_num(hold ? "hold" : "pit"))
        return false;
      step.pit_c = temp_value(t[i], f);
      step.hold = step.hold || hold;
      i++;
    } else if (w == "notify" || w == "alert") {
      i++;
      if (t[i].kind != Tok::STR) {
        err = "notify needs a quoted message";
        return false;
      }
      step.notify = t[i].text;
      i++;
    } else if (w == "shutdown" || w == "stop" || w == "off") {
      step.shutdown = true;
      i++;
    } else if (w == "then") {
      i++;
      continue;
    } else {
      err = "unknown action '" + w + "'";
      return false;
    }
    any_action = true;
  }
  if (!any_action) {
    err = "step has no action (pit / hold / notify / shutdown)";
    return false;
  }
  if (t[i].kind == Tok::END)
    return true;
  if (!(t[i].kind == Tok::WORD && t[i].text == "until")) {
    err = "expected 'until'";
    return false;
  }
  i++;
  while (true) {
    Condition c;
    if (t[i].kind != Tok::WORD) {
      err = "expected a condition after 'until'/'or'";
      return false;
    }
    std::string w = t[i].text;
    if (w == "after") {
      i++;
      c.type = Condition::AFTER;
      if (!duration_min(t[i], c.value)) {
        err = "after needs a duration, e.g. 'after 2h'";
        return false;
      }
      i++;
    } else if (w == "at") {
      i++;
      if (t[i].kind != Tok::NUM || t[i].unit != 't') {
        err = "at needs a time, e.g. 'at 17:30'";
        return false;
      }
      c.type = Condition::AT_CLOCK;
      c.value = t[i].num;
      i++;
    } else if (w == "stall_start" || w == "stall_end") {
      c.type = w == "stall_start" ? Condition::STALL_START : Condition::STALL_END;
      i++;
      if (t[i].kind != Tok::WORD || (c.probe = probe_idx(t[i].text, probes)) < 0) {
        err = w + " needs a probe name";
        return false;
      }
      i++;
    } else {
      c.probe = probe_idx(w, probes);
      if (c.probe < 0) {
        err = "unknown probe '" + w + "'";
        return false;
      }
      i++;
      if (t[i].kind == Tok::WORD && t[i].text == "done") {
        c.type = Condition::PROBE_DONE;
        i++;
      } else if (t[i].kind == Tok::WORD && t[i].text == "stall") {
        // "<probe> stall ends" / "<probe> stall starts"
        i++;
        c.type = Condition::STALL_START;
        if (t[i].kind == Tok::WORD && (t[i].text == "ends" || t[i].text == "end" || t[i].text == "over")) {
          c.type = Condition::STALL_END;
          i++;
        } else if (t[i].kind == Tok::WORD && (t[i].text == "starts" || t[i].text == "start")) {
          i++;
        }
      } else if (t[i].kind == Tok::OP && (t[i].text == ">=" || t[i].text == "<=")) {
        c.type = t[i].text == ">=" ? Condition::PROBE_GTE : Condition::PROBE_LTE;
        i++;
        if (!need_num(">="))
          return false;
        c.value = temp_value(t[i], f);
        i++;
      } else {
        err = "expected >=, <=, 'done' or 'stall' after '" + w + "'";
        return false;
      }
    }
    if (t[i].kind == Tok::WORD && t[i].text == "for") {
      i++;
      if (!duration_min(t[i], c.hold_min)) {
        err = "for needs a duration, e.g. 'for 30m'";
        return false;
      }
      i++;
    }
    step.until.push_back(c);
    if (t[i].kind == Tok::WORD && t[i].text == "or") {
      i++;
      continue;
    }
    break;
  }
  // A notification after the conditions ("pit 275 until food1 >= 165 notify \"Wrap it\"", as an AI writes it) is
  // the step's notification, as if it came first.
  if (t[i].kind == Tok::WORD && (t[i].text == "notify" || t[i].text == "alert") && step.notify.empty()) {
    i++;
    if (t[i].kind != Tok::STR) {
      err = "notify needs a quoted message";
      return false;
    }
    step.notify = t[i].text;
    i++;
  }
  if (t[i].kind != Tok::END) {
    err = "unexpected '" + t[i].text + "' at end of step";
    return false;
  }
  return true;
}

std::string fmt_temp(float c, bool f) {
  char buf[16];
  std::snprintf(buf, sizeof(buf), "%.0f", from_c(c, f));
  return buf;
}

std::string fmt_dur(float min) {
  char buf[16];
  if (min >= 60 && std::fmod(min, 60.0f) == 0)
    std::snprintf(buf, sizeof(buf), "%.0fh", min / 60.0f);
  else
    std::snprintf(buf, sizeof(buf), "%.0fm", min);
  return buf;
}

}  // namespace

bool parse_program(const std::string &text, const std::vector<std::string> &probes, bool fahrenheit,
                   Program &out, std::string &error) {
  Program p;
  std::vector<std::string> parts;
  std::string cur;
  bool in_quote = false;
  char q = 0;
  for (char c : text) {
    if (in_quote) {
      cur += c;
      if (c == q)
        in_quote = false;
      continue;
    }
    if (c == '"' || c == '\'') {
      in_quote = true;
      q = c;
      cur += c;
      continue;
    }
    if (c == ';' || c == '\n' || c == '\r') {
      parts.push_back(cur);
      cur.clear();
      continue;
    }
    cur += c;
  }
  parts.push_back(cur);
  int n = 0;
  for (auto &part : parts) {
    size_t a = part.find_first_not_of(" \t");
    if (a == std::string::npos)
      continue;
    std::string s = part.substr(a);
    // Allow "1:" / "1." step numbers and a "name:" header.
    if (lower(s.substr(0, 5)) == "name:") {
      size_t b = s.find_first_not_of(" \t", 5);
      p.name = b == std::string::npos ? "" : s.substr(b);
      while (!p.name.empty() && std::isspace((unsigned char) p.name.back()))
        p.name.pop_back();
      continue;
    }
    size_t k = 0;
    while (k < s.size() && std::isdigit((unsigned char) s[k]))
      k++;
    if (k > 0 && k < s.size() && (s[k] == ':' || s[k] == '.' || s[k] == ')'))
      s = s.substr(k + 1);
    n++;
    Step st;
    std::string err;
    if (!parse_step(s, probes, fahrenheit, st, err)) {
      error = "step " + std::to_string(n) + ": " + err;
      return false;
    }
    p.steps.push_back(st);
  }
  if (p.steps.empty()) {
    error = "program has no steps";
    return false;
  }
  out = p;
  return true;
}

std::string format_program(const Program &p, const std::vector<std::string> &probes, bool f) {
  std::string s;
  if (!p.name.empty())
    s += "name: " + p.name + "\n";
  for (const auto &st : p.steps) {
    std::string line;
    if (!std::isnan(st.pit_c))
      line += std::string(st.hold ? "hold " : "pit ") + fmt_temp(st.pit_c, f);
    if (!st.notify.empty()) {  // quoted with whichever quote the text doesn't contain (the parser takes both), so it reads back
      const char q = st.notify.find('"') == std::string::npos ? '"' : '\'';
      std::string n = st.notify;
      n.erase(std::remove(n.begin(), n.end(), q), n.end());
      line += std::string(line.empty() ? "" : " ") + "notify " + q + n + q;
    }
    if (st.shutdown)
      line += std::string(line.empty() ? "" : " ") + "shutdown";
    for (size_t i = 0; i < st.until.size(); i++) {
      const auto &c = st.until[i];
      line += i == 0 ? " until " : " or ";
      std::string pn = c.probe >= 0 && size_t(c.probe) < probes.size() ? probes[c.probe] : "?";
      switch (c.type) {
        case Condition::PROBE_GTE:
          line += pn + " >= " + fmt_temp(c.value, f);
          break;
        case Condition::PROBE_LTE:
          line += pn + " <= " + fmt_temp(c.value, f);
          break;
        case Condition::PROBE_DONE:
          line += pn + " done";
          break;
        case Condition::AFTER:
          line += "after " + fmt_dur(c.value);
          break;
        case Condition::AT_CLOCK: {
          char b[16];
          std::snprintf(b, sizeof(b), "%02d:%02d", int(c.value) / 60, int(c.value) % 60);
          line += std::string("at ") + b;
          break;
        }
        case Condition::STALL_START:
          line += "stall_start " + pn;
          break;
        case Condition::STALL_END:
          line += "stall_end " + pn;
          break;
      }
      if (c.hold_min > 0)
        line += " for " + fmt_dur(c.hold_min);
    }
    s += line + "\n";
  }
  return s;
}

// ---------------- Runner ----------------

void ProgramRunner::load(const Program &p) {
  prog_ = p;
  state_ = State::IDLE;
  step_ = 0;
  commanded_pit_ = NAN;
}

const char *ProgramRunner::state_name() const {
  switch (state_) {
    case State::IDLE:
      return "Idle";
    case State::RUNNING:
      return "Running";
    case State::PAUSED:
      return "Paused";
    case State::FINISHED:
      return "Finished";
  }
  return "?";
}

double ProgramRunner::step_elapsed_min(double now_min) const {
  if (state_ == State::PAUSED)
    return paused_at_min_ - step_start_min_;
  if (state_ != State::RUNNING)
    return 0;
  return now_min - step_start_min_;
}

RunnerOutputs ProgramRunner::enter_step_(size_t idx, double now_min) {
  RunnerOutputs out;
  // Steps with no conditions (and not 'hold') complete immediately; chain them.
  for (int guard = 0; guard < 64; guard++) {
    step_ = idx;
    step_start_min_ = now_min;
    const Step &s = prog_.steps[idx];
    held_since_.assign(s.until.size(), -1);
    out.step_changed = true;
    if (!std::isnan(s.pit_c)) {
      out.set_pit = true;
      out.pit_c = s.pit_c;
      commanded_pit_ = s.pit_c;
    }
    if (!s.notify.empty())
      out.notifications.push_back(s.notify);
    if (s.shutdown) {
      out.shutdown = true;
      commanded_pit_ = NAN;
      state_ = State::FINISHED;
      out.finished = true;
      return out;
    }
    bool last = idx + 1 >= prog_.steps.size();
    if (!s.until.empty() || s.hold) {
      if (last && s.until.empty()) {
        // Final hold step: program is "finished" but keeps the setpoint.
        state_ = State::FINISHED;
        out.finished = true;
      }
      return out;
    }
    if (last) {
      state_ = State::FINISHED;
      out.finished = true;
      return out;
    }
    idx++;
  }
  return out;
}

RunnerOutputs ProgramRunner::start(double now_min, size_t step) {
  if (!loaded() || step >= prog_.steps.size())
    return {};
  state_ = State::RUNNING;
  last_tick_min_ = -1;
  pause_reason_.clear();
  return enter_step_(step, now_min);
}

void ProgramRunner::pause(double now_min, const char *reason) {
  if (state_ != State::RUNNING)
    return;
  state_ = State::PAUSED;
  paused_at_min_ = now_min;
  last_tick_min_ = -1;
  pause_reason_ = reason ? reason : "";
}

RunnerOutputs ProgramRunner::resume(double now_min) {
  RunnerOutputs out;
  if (state_ != State::PAUSED)
    return out;
  // Paused time doesn't count towards 'after' or 'for' timers.
  double paused_for = now_min - paused_at_min_;
  if (paused_for > 0) {
    step_start_min_ += paused_for;
    for (auto &h : held_since_)
      if (h >= 0)
        h += paused_for;
  }
  state_ = State::RUNNING;
  last_tick_min_ = -1;
  pause_reason_.clear();
  // Re-assert this step's setpoint (it may have been overridden).
  if (!std::isnan(commanded_pit_)) {
    out.set_pit = true;
    out.pit_c = commanded_pit_;
  }
  return out;
}

RunnerOutputs ProgramRunner::skip(double now_min) {
  if (!loaded() || state_ == State::IDLE)
    return {};
  if (step_ + 1 >= prog_.steps.size()) {
    state_ = State::FINISHED;
    RunnerOutputs o;
    o.finished = true;
    return o;
  }
  state_ = State::RUNNING;
  pause_reason_.clear();
  return enter_step_(step_ + 1, now_min);
}

void ProgramRunner::stop() {
  state_ = State::IDLE;
  last_tick_min_ = -1;
  commanded_pit_ = NAN;
  pause_reason_.clear();
}

void ProgramRunner::restore(size_t step, double step_elapsed_min, double now_min, bool running) {
  if (!loaded() || step >= prog_.steps.size())
    return;
  step_ = step;
  step_start_min_ = now_min - step_elapsed_min;
  held_since_.assign(prog_.steps[step].until.size(), -1);
  commanded_pit_ = prog_.steps[step].pit_c;
  // Walk back for the most recent explicit setpoint.
  for (int i = int(step); i >= 0 && std::isnan(commanded_pit_); i--)
    commanded_pit_ = prog_.steps[i].pit_c;
  state_ = running ? State::RUNNING : State::PAUSED;
  paused_at_min_ = now_min;
  last_tick_min_ = -1;
  if (!running)
    pause_reason_ = "restored after restart";
}

bool ProgramRunner::condition_true_(const Condition &c, const RunnerInputs &in, double now_min) const {
  auto temp = [&](int p) -> float { return p >= 0 && size_t(p) < in.temp_c.size() ? in.temp_c[p] : NAN; };
  auto flag = [&](const std::vector<bool> &v, int p) { return p >= 0 && size_t(p) < v.size() && v[p]; };
  switch (c.type) {
    case Condition::PROBE_GTE: {
      float t = temp(c.probe);
      return !std::isnan(t) && t >= c.value;
    }
    case Condition::PROBE_LTE: {
      float t = temp(c.probe);
      return !std::isnan(t) && t <= c.value;
    }
    case Condition::PROBE_DONE:
      return flag(in.done, c.probe);
    case Condition::AFTER:
      return now_min - step_start_min_ >= c.value;
    case Condition::AT_CLOCK:
      return in.minute_of_day >= 0 && in.minute_of_day == int(c.value);
    case Condition::STALL_START:
      return flag(in.stall_started, c.probe);
    case Condition::STALL_END:
      return flag(in.stall_ended, c.probe);
  }
  return false;
}

RunnerOutputs ProgramRunner::tick(double now_min, const RunnerInputs &in) {
  RunnerOutputs out;
  if (state_ != State::RUNNING) {
    last_tick_min_ = -1;
    return out;
  }
  struct TickMark {  // remember when this tick ran, for the dropout freeze
    double &ref;
    double v;
    ~TickMark() { ref = v; }
  } mark{last_tick_min_, now_min};
  const Step &s = prog_.steps[step_];
  if (s.until.empty())
    return out;  // hold step
  bool advance = false;
  for (size_t i = 0; i < s.until.size(); i++) {
    const Condition &c = s.until[i];
    bool ok = condition_true_(c, in, now_min);
    // A probe that is briefly unavailable (e.g. a Bluetooth dropout) freezes its timer instead of resetting it.
    bool probe_cond = c.type == Condition::PROBE_GTE || c.type == Condition::PROBE_LTE;
    if (probe_cond && (c.probe < 0 || size_t(c.probe) >= in.temp_c.size() || std::isnan(in.temp_c[c.probe]))) {
      if (held_since_[i] >= 0 && last_tick_min_ >= 0 && now_min > last_tick_min_)
        held_since_[i] += now_min - last_tick_min_;  // the dropout doesn't count towards the hold
      continue;
    }
    // Stall events and clock times are momentary: latch them.
    bool momentary = c.type == Condition::STALL_START || c.type == Condition::STALL_END ||
                     c.type == Condition::AT_CLOCK;
    if (ok) {
      if (held_since_[i] < 0)
        held_since_[i] = now_min;
    } else if (!momentary) {
      held_since_[i] = -1;
    }
    if (held_since_[i] >= 0 && now_min - held_since_[i] >= c.hold_min - 1e-6)
      advance = true;
  }
  if (!advance)
    return out;
  if (step_ + 1 >= prog_.steps.size()) {
    state_ = State::FINISHED;
    out.finished = true;
    out.step_changed = true;
    return out;
  }
  return enter_step_(step_ + 1, now_min);
}

std::string ProgramRunner::describe(double now_min, const RunnerInputs &in, const std::vector<std::string> &probes,
                                    bool f) const {
  if (!loaded())
    return "No program";
  char buf[160];
  std::string unit = f ? "°F" : "°C";
  if (state_ == State::IDLE)
    return "Ready: " + (prog_.name.empty() ? std::string("program") : prog_.name) + " (" +
           std::to_string(prog_.steps.size()) + " steps)";
  if (state_ == State::FINISHED)
    return std::isnan(commanded_pit_) ? "Finished" : "Finished, holding " + fmt_temp(commanded_pit_, f) + unit;
  std::snprintf(buf, sizeof(buf), "Step %u/%u", unsigned(step_ + 1), unsigned(prog_.steps.size()));
  std::string s = buf;
  if (state_ == State::PAUSED)
    s += " (paused" + (pause_reason_.empty() ? std::string() : ": " + pause_reason_) + ")";
  const Step &st = prog_.steps[step_];
  if (!std::isnan(st.pit_c))
    s += ", pit " + fmt_temp(st.pit_c, f) + unit;
  for (size_t i = 0; i < st.until.size(); i++) {
    const auto &c = st.until[i];
    s += i == 0 ? ", until " : " or ";
    std::string pn = c.probe >= 0 && size_t(c.probe) < probes.size() ? probes[c.probe] : "?";
    float t = c.probe >= 0 && size_t(c.probe) < in.temp_c.size() ? in.temp_c[c.probe] : NAN;
    switch (c.type) {
      case Condition::PROBE_GTE:
      case Condition::PROBE_LTE:
        s += pn + " " + (std::isnan(t) ? std::string("--") : fmt_temp(t, f)) + "/" + fmt_temp(c.value, f) + unit;
        break;
      case Condition::PROBE_DONE:
        s += pn + " done";
        break;
      case Condition::AFTER:
        std::snprintf(buf, sizeof(buf), "%.0f/%.0f min", step_elapsed_min(now_min), c.value);
        s += buf;
        break;
      case Condition::AT_CLOCK:
        std::snprintf(buf, sizeof(buf), "%02d:%02d", int(c.value) / 60, int(c.value) % 60);
        s += buf;
        break;
      case Condition::STALL_START:
        s += pn + " stall starts";
        break;
      case Condition::STALL_END:
        s += pn + " stall ends";
        break;
    }
    if (c.hold_min > 0) {
      double held = i < held_since_.size() && held_since_[i] >= 0 ? now_min - held_since_[i] : 0;
      std::snprintf(buf, sizeof(buf), " (held %.0f/%.0f min)", held, c.hold_min);
      s += buf;
    }
  }
  return s;
}

std::vector<PlanSegment> ProgramRunner::plan_for_probe(int probe, double now_min, float probe_target_c) const {
  std::vector<PlanSegment> plan;
  if (!loaded() || (state_ != State::RUNNING && state_ != State::PAUSED))
    return plan;
  for (size_t i = step_; i < prog_.steps.size(); i++) {
    const Step &st = prog_.steps[i];
    PlanSegment seg;
    seg.pit_c = st.pit_c;
    if (i == step_) {
      if (std::isnan(seg.pit_c))
        seg.pit_c = commanded_pit_;
      seg.elapsed_min = float(step_elapsed_min(now_min));
    }
    if (st.shutdown) {
      seg.pit_c = 40.0f;  // fire out: the forecast sees the pit cooling off
      seg.until = PlanSegment::FOREVER;
      plan.push_back(seg);
      break;
    }
    seg.until = st.until.empty() ? (st.hold ? PlanSegment::FOREVER : PlanSegment::AFTER_MIN) : PlanSegment::UNKNOWN;
    // Use the first condition the simulation can evaluate for this probe.
    for (size_t ci = 0; ci < st.until.size(); ci++) {
      const auto &c = st.until[ci];
      if (c.type == Condition::PROBE_GTE && c.probe == probe) {
        seg.until = PlanSegment::FOOD_GTE;
        seg.value = c.value;
      } else if (c.type == Condition::PROBE_LTE && c.probe == probe) {
        seg.until = PlanSegment::FOOD_LTE;
        seg.value = c.value;
      } else if (c.type == Condition::PROBE_DONE && c.probe == probe && !std::isnan(probe_target_c)) {
        seg.until = PlanSegment::FOOD_GTE;
        seg.value = probe_target_c;
      } else if (c.type == Condition::AFTER) {
        seg.until = PlanSegment::AFTER_MIN;
        seg.value = c.value;
      } else {
        continue;
      }
      seg.hold_min = c.hold_min;
      if (i == step_ && ci < held_since_.size() && held_since_[ci] >= 0)
        seg.held_min = float(now_min - held_since_[ci]);
      break;
    }
    plan.push_back(seg);
    if (seg.until == PlanSegment::UNKNOWN || seg.until == PlanSegment::FOREVER)
      break;  // cannot see past this step
  }
  return plan;
}

}  // namespace cook
