#pragma once
// Cook programs: a tiny step language and its runner. Pure C++ (unit tested).
//
// A program is a list of steps separated by ';' or new lines. Each step has
// actions, optionally followed by `until` and one or more conditions joined
// by `or`:
//
//   pit 250 until food1 >= 165 for 30m;
//   pit 300 until food1 >= 200;
//   hold 160 notify "Pork done - resting"
//
// Actions:     pit N          set the pit target
//              hold N         set the pit target and stay here (no auto-advance)
//              notify "text"  send a notification when the step starts
//              shutdown       end the cook (pit target cleared, fan off on the replacement controller)
// Conditions:  <probe> >= N [for N(m|h)]     (also <=; probe names: pit, food1, food2, ...)
//              <probe> done                  probe reached its own target
//              after N(m|h)                  time spent in this step
//              at HH:MM                      wall-clock time (needs time sync)
//              stall_start <probe> / stall_end <probe>
// Temperatures use the configured unit, or an explicit suffix: 165F, 74C.
// A first line `name: Pork shoulder` names the program.

#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

#include "predictor.h"

namespace cook {

struct Condition {
  enum Type : uint8_t { PROBE_GTE, PROBE_LTE, PROBE_DONE, AFTER, AT_CLOCK, STALL_START, STALL_END };
  Type type{PROBE_GTE};
  int probe{-1};
  float value{0};     // °C, minutes, or minute-of-day
  float hold_min{0};  // condition must hold this long
};

struct Step {
  float pit_c{NAN};
  bool hold{false};
  bool shutdown{false};
  std::string notify;
  std::vector<Condition> until;
};

struct Program {
  std::string name;
  std::vector<Step> steps;
};

/// Parse program text. `probes` lists valid probe names (index = probe id).
/// Returns false and sets `error` (with the step number) on a syntax error.
bool parse_program(const std::string &text, const std::vector<std::string> &probes, bool fahrenheit,
                   Program &out, std::string &error);

/// Format a program back to text (canonical form) in the given unit.
std::string format_program(const Program &p, const std::vector<std::string> &probes, bool fahrenheit);

struct RunnerInputs {
  std::vector<float> temp_c;      // per probe, NAN = absent
  std::vector<bool> done;         // per probe: reached own target
  std::vector<bool> stall_started;  // per probe: event this tick
  std::vector<bool> stall_ended;    // per probe: event this tick
  int minute_of_day{-1};          // -1 = clock unknown
};

struct RunnerOutputs {
  bool set_pit{false};
  float pit_c{NAN};
  bool shutdown{false};
  std::vector<std::string> notifications;
  bool step_changed{false};
  bool finished{false};
};

class ProgramRunner {
 public:
  enum class State : uint8_t { IDLE, RUNNING, PAUSED, FINISHED };

  void load(const Program &p);
  const Program &program() const { return prog_; }
  bool loaded() const { return !prog_.steps.empty(); }

  /// Start from step 0 (or `step`).
  RunnerOutputs start(double now_min, size_t step = 0);
  void pause(double now_min, const char *reason);
  RunnerOutputs resume(double now_min = 0);
  RunnerOutputs skip(double now_min);
  void stop();

  /// Evaluate conditions. Call about once a second or on new data.
  RunnerOutputs tick(double now_min, const RunnerInputs &in);

  State state() const { return state_; }
  const char *state_name() const;
  size_t step() const { return step_; }
  double step_elapsed_min(double now_min) const;
  const std::string &pause_reason() const { return pause_reason_; }
  /// Commanded pit target of the current step (NAN if none).
  float commanded_pit() const { return commanded_pit_; }

  /// Human-readable progress, e.g. "Step 2/3: food1 158/165°F, held 0/30 min".
  std::string describe(double now_min, const RunnerInputs &in, const std::vector<std::string> &probes,
                       bool fahrenheit) const;

  /// Pit plan from the current step onwards as seen by one probe, for the predictor.
  std::vector<PlanSegment> plan_for_probe(int probe, double now_min, float probe_target_c) const;

  /// Restore after a reboot.
  void restore(size_t step, double step_elapsed_min, double now_min, bool running);

 protected:
  RunnerOutputs enter_step_(size_t idx, double now_min);
  bool condition_true_(const Condition &c, const RunnerInputs &in, double now_min) const;

  Program prog_;
  State state_{State::IDLE};
  size_t step_{0};
  double step_start_min_{0};
  double paused_at_min_{0};
  std::vector<double> held_since_;  // per condition of the current step, -1 = not holding
  float commanded_pit_{NAN};
  std::string pause_reason_;
};

}  // namespace cook
