// Host unit tests for the pure-C++ core (protocol, predictor, history, programs).
// Build & run:  make -C tests
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "../components/govee_h5198/h5198_decode.h"
#include "../components/cook_assistant/fuel.h"
#include "../components/cook_assistant/history.h"
#include "../components/cook_assistant/predictor.h"
#include "../components/cook_assistant/program.h"
#include "../components/gravity980/protocol.h"
#include "../components/standalone/pin_auth.h"

static int failures = 0;
#define CHECK(cond)                                                     \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
      failures++;                                                       \
    }                                                                   \
  } while (0)
#define NEAR(a, b, tol) CHECK(std::fabs((a) - (b)) <= (tol))

using namespace g980proto;

// ---------------------------------------------------------------- protocol

static std::vector<uint8_t> frame(uint16_t p1, uint16_t s1, uint16_t p2, uint16_t s2, uint16_t p3, uint16_t s3,
                                  bool alarm, bool fan, bool door, size_t len = 16) {
  std::vector<uint8_t> f(len, 0);
  auto put = [&](size_t o, uint16_t v) {
    f[o] = v >> 8;
    f[o + 1] = v & 0xFF;
  };
  put(0, p1);
  put(2, s1);
  f[4] = alarm ? ALARM_FIRING : ALARM_SILENT;
  put(6, p2);
  put(8, s2);
  put(10, p3);
  put(12, s3);
  f[14] = fan ? FAN_ON_BIT : 0;
  f[15] = door ? DOOR_OPEN_BIT : 0;
  if (len > 16) {
    f[16] = 0x10;
    f[18] = 0x11;
  }
  return f;
}

static void test_protocol() {
  std::printf("protocol\n");
  // Example from the protocol doc.
  const uint8_t doc[] = {0x00, 0x69, 0x00, 0xE1, 0x10, 0x00, 0x00, 0x45, 0x00, 0x60, 0x00, 0x49, 0x00, 0x5F, 0x10, 0x00};
  Status s;
  CHECK(parse_status(doc, sizeof(doc), s));
  CHECK(s.probe[PROBE_PIT].temp_f == 105 && s.probe[PROBE_PIT].target_f == 225);
  CHECK(s.probe[PROBE_FOOD1].temp_f == 69 && s.probe[PROBE_FOOD1].target_f == 96);
  CHECK(s.probe[PROBE_FOOD2].temp_f == 73 && s.probe[PROBE_FOOD2].target_f == 95);
  CHECK(!s.alarm_firing && s.fan_on && !s.door_open);

  auto f = frame(1000, 4096, 150, 4096, 1000, 4096, false, false, true);
  CHECK(parse_status(f.data(), f.size(), s));
  CHECK(!s.probe[PROBE_PIT].present && !s.probe[PROBE_PIT].has_target);
  CHECK(s.probe[PROBE_FOOD1].present && s.door_open);

  // Stream reassembly: 16-byte frames, split arbitrarily, with leading garbage.
  for (size_t flen : {size_t(16), size_t(20)}) {
    FrameAssembler a;
    std::vector<uint8_t> stream = {0xAB, 0xCD, 0x01};
    for (int i = 0; i < 6; i++) {
      auto fr = frame(200 + i, 225, 100 + i, 203, 1000, 4096, i == 3, true, false, flen);
      stream.insert(stream.end(), fr.begin(), fr.end());
    }
    std::vector<Status> got;
    for (size_t i = 0; i < stream.size(); i += 7) {
      size_t n = std::min<size_t>(7, stream.size() - i);
      a.feed(stream.data() + i, n, [&](const uint8_t *d, size_t len) {
        Status st;
        if (parse_status(d, len, st))
          got.push_back(st);
      });
    }
    CHECK(a.frame_size() == flen);
    CHECK(got.size() >= 5);
    if (got.size() >= 5) {
      CHECK(got[0].probe[PROBE_PIT].temp_f == 200 || got[0].probe[PROBE_PIT].temp_f == 201);
      CHECK(got.back().probe[PROBE_FOOD1].temp_f == 104 || got.back().probe[PROBE_FOOD1].temp_f == 105);
    }
  }

  // BLE heartbeat payload.
  std::vector<uint8_t> ble = {0x00, 0x19, 0x10, 0x00};
  auto fr = frame(250, 250, 160, 203, 1000, 4096, false, true, false);
  ble.insert(ble.end(), fr.begin(), fr.end());
  const uint8_t *pl;
  size_t pll;
  CHECK(ble_status_payload(ble.data(), ble.size(), &pl, &pll) && pll == 16);
  const uint8_t wifi[] = {0x07, 0x10, 0x50, 0, 0, 3, 'a', 'b', 'c'};
  CHECK(!ble_status_payload(wifi, sizeof(wifi), &pl, &pll));

  // Commands: only setpoints, range checked.
  std::vector<uint8_t> cmd;
  CHECK(build_target_command(PROBE_PIT, 250, false, cmd));
  CHECK(cmd == std::vector<uint8_t>({0xFF, 0x00, 0x00, 0xFA}));
  CHECK(build_target_command(PROBE_FOOD2, 203, true, cmd));
  CHECK(cmd == std::vector<uint8_t>({0x00, 0x19, 0x04, 0x00, 0xFF, 0x03, 0x00, 0xCB}));
  CHECK(!build_target_command(PROBE_PIT, 150, false, cmd));
  CHECK(!build_target_command(PROBE_FOOD1, 400, false, cmd));
}

// ---------------------------------------------------------------- cook simulation
//
// "Truth" model used to test the predictor. It is deliberately different from
// the predictor's internal model: a two-node (surface/core) heat model with
// moisture-limited evaporative cooling, which produces a realistic stall.

struct Meat {
  float core, surface, moisture;
  float k_surf, k_core, evap, evap_depletion;
};

static Meat make_meat(float weight_kg, bool stalls) {
  float s = std::pow(3.6f / weight_kg, 2.0f / 3.0f);
  return {4.0f, 4.0f, stalls ? 1.0f : 0.0f, 1.2f * s, 0.32f * s, 100.0f, 0.18f / std::sqrt(weight_kg / 3.6f)};
}

static void step_meat(Meat &m, float pit, float dt_h, bool wrapped) {
  float e = 0;
  if (m.moisture > 0 && m.surface > 63.0f) {
    float act = std::min(1.0f, (m.surface - 63.0f) / 8.0f);
    e = m.evap * act * std::sqrt(m.moisture) * (wrapped ? 0.15f : 1.0f);
    m.moisture -= m.evap_depletion * act * dt_h * (wrapped ? 0.6f : 1.0f) * (1.0f + (pit - 107.0f) / 60.0f);
    if (m.moisture < 0)
      m.moisture = 0;
  }
  float dsurf = m.k_surf * (pit - m.surface) - e - m.k_core * 1.5f * (m.surface - m.core);
  float dcore = m.k_core * (m.surface - m.core) * 2.0f;
  m.surface += dsurf * dt_h;
  m.core += dcore * dt_h;
}

struct CookResult {
  float actual_total_min;
  std::vector<std::pair<float, float>> checkpoints;  // (elapsed_min, predicted_remaining_min)
  bool stall_detected;
  cook::CookRecord record;
  bool have_record;
};

static CookResult run_cook(float weight_kg, float pit_c, float target_c, int profile, const cook::Priors &pri,
                           bool wrap_at_stall, const std::vector<cook::PlanSegment> &plan_template, bool verbose,
                           float pit_bias = 0.0f) {
  cook::Predictor p;
  p.set_profile(profile);
  p.set_target(target_c);
  p.set_weight(weight_kg);
  p.set_priors(pri);
  Meat m = make_meat(weight_kg, cook::profiles()[profile].stalls);
  CookResult r{NAN, {}, false, {}, false};
  const float dt = 1.0f / 3600.0f * 10;  // 10 s
  double t = 0;
  bool wrapped = false;
  float pit = pit_c;
  std::vector<cook::PlanSegment> plan = plan_template;
  for (int i = 0; i < int(30 * 360); i++) {
    // Pit noise: slow wobble.
    float pit_meas = pit + pit_bias + 4.0f * std::sin(float(t) * 3.0f);
    step_meat(m, pit_meas, dt, wrapped);
    t += dt;
    float probe = m.core + 0.1f * std::sin(float(t) * 50.0f);
    p.add_sample(t, probe, pit_meas, pit);
    if (p.take_stall_started()) {
      r.stall_detected = true;
      if (wrap_at_stall) {
        wrapped = true;
        p.set_wrapped(true);
      }
    }
    // Plan for this simple test: pit change when core hits a threshold.
    if (!plan.empty() && plan.size() > 1 && plan[0].until == cook::PlanSegment::FOOD_GTE && m.core >= plan[0].value) {
      plan.erase(plan.begin());
      pit = plan[0].pit_c;
    }
    int minute = int(t * 60 + 0.5);
    if (i % 6 == 0 && minute % 60 == 0 && minute > 0) {
      auto pr = p.predict(plan, pit);
      r.checkpoints.push_back({float(minute), pr.valid ? pr.minutes : NAN});
      if (verbose)
        std::printf("    t=%4d min core=%5.1f %-9s rate=%5.1f k=%.3f pred=%6.0f [%4.0f..%4.0f]\n", minute, m.core,
                    cook::phase_name(p.phase()), p.rate_c_per_h(), p.k_pre(), pr.minutes, pr.minutes_low,
                    pr.minutes_high);
    }
    if (m.core >= target_c && std::isnan(r.actual_total_min)) {
      r.actual_total_min = float(t * 60);
    }
    if (!std::isnan(r.actual_total_min) && t * 60 > r.actual_total_min + 7) {
      r.have_record = p.take_completed(r.record);
      break;
    }
  }
  return r;
}

static float mean_abs_error_pct(const CookResult &r, float from_frac) {
  double s = 0;
  int n = 0;
  for (auto &c : r.checkpoints) {
    if (std::isnan(c.second) || c.first < from_frac * r.actual_total_min)
      continue;
    float actual_remaining = r.actual_total_min - c.first;
    if (actual_remaining < 30)
      continue;
    s += std::fabs(c.second - actual_remaining) / r.actual_total_min;
    n++;
  }
  return n ? float(100 * s / n) : NAN;
}

static void test_predictor() {
  std::printf("predictor\n");
  cook::CookHistory hist;
  int pork = cook::profile_index("Pork shoulder");
  CHECK(pork > 0);

  // 1) First pork shoulder, no history.
  auto pri = hist.priors(pork, 3.6f, 107.0f, false);
  std::printf("  cook 1 (no history): k=%.3f stall=%.1fh\n", pri.k, pri.stall_h);
  auto r1 = run_cook(3.6f, 107.0f, 93.0f, pork, pri, false, {}, true);
  float e1 = mean_abs_error_pct(r1, 0.0f);
  std::printf("  actual %.0f min, stall detected %d, mean |error| %.1f%% of cook\n", r1.actual_total_min,
              r1.stall_detected, e1);
  CHECK(r1.stall_detected);
  CHECK(!std::isnan(r1.actual_total_min) && r1.actual_total_min > 8 * 60 && r1.actual_total_min < 20 * 60);
  CHECK(r1.have_record);
  CHECK(mean_abs_error_pct(r1, 0.5f) < 15.0f);

  // 2) Learn from it, then cook a similar (slightly bigger) shoulder.
  hist.add(r1.record);
  std::printf("  record: k_pre=%.3f k_post=%.3f stall=%.2fh total=%.2fh onset=%.1f\n", r1.record.k_pre,
              r1.record.k_post, r1.record.stall_h, r1.record.total_h, r1.record.stall_onset_c);
  auto pri2 = hist.priors(pork, 4.0f, 107.0f, false);
  std::printf("  cook 2 (1 similar cook): k=%.3f stall=%.1fh conf=%.2f\n", pri2.k, pri2.stall_h, pri2.confidence);
  auto r2 = run_cook(4.0f, 107.0f, 93.0f, pork, pri2, false, {}, false);
  float e2_early = mean_abs_error_pct(r2, 0.0f);
  // Same cook without history, for comparison.
  auto r2n = run_cook(4.0f, 107.0f, 93.0f, pork, hist.priors(-1, 4.0f, 107.0f, false), false, {}, false);
  (void) r2n;
  cook::CookHistory empty;
  auto r2b = run_cook(4.0f, 107.0f, 93.0f, pork, empty.priors(pork, 4.0f, 107.0f, false), false, {}, false);
  float e2b_early = mean_abs_error_pct(r2b, 0.0f);
  std::printf("  cook 2 error: with history %.1f%%, without %.1f%%\n", e2_early, e2b_early);
  CHECK(e2_early < e2b_early);

  // 3) Pre-cook estimate from history should be close to the actual time.
  {
    cook::Predictor p;
    p.set_profile(pork);
    p.set_target(93.0f);
    p.set_priors(pri2);
    float est = p.estimate_total_minutes(4.0f, 107.0f, {});
    std::printf("  pre-cook estimate %.0f min vs actual %.0f min\n", est, r2.actual_total_min);
    CHECK(std::fabs(est - r2.actual_total_min) / r2.actual_total_min < 0.25f);
  }

  // 4) Program plan: 107 °C until 74 °C (165 °F), then 149 °C (300 °F): faster than staying at 107.
  {
    std::vector<cook::PlanSegment> plan(2);
    plan[0].pit_c = 107.0f;
    plan[0].until = cook::PlanSegment::FOOD_GTE;
    plan[0].value = 74.0f;
    plan[1].pit_c = 149.0f;
    auto r4 = run_cook(3.6f, 107.0f, 93.0f, pork, hist.priors(pork, 3.6f, 107.0f, false), false, plan, false);
    std::printf("  programmed cook actual %.0f min, error %.1f%%\n", r4.actual_total_min, mean_abs_error_pct(r4, 0.0f));
    CHECK(r4.actual_total_min < r1.actual_total_min);
    CHECK(mean_abs_error_pct(r4, 0.3f) < 20.0f);
  }

  // 5) Wrapping at the stall shortens the cook and the predictor follows.
  {
    auto r5 = run_cook(3.6f, 107.0f, 93.0f, pork, hist.priors(pork, 3.6f, 107.0f, true), true, {}, false);
    std::printf("  wrapped cook actual %.0f min, error after stall %.1f%%\n", r5.actual_total_min,
                mean_abs_error_pct(r5, 0.5f));
    CHECK(r5.actual_total_min < r1.actual_total_min);
  }

  // 6) Poultry: no stall expected.
  {
    int poultry = cook::profile_index("Poultry");
    auto r6 = run_cook(2.0f, 150.0f, 74.0f, poultry, hist.priors(poultry, 2.0f, 150.0f, false), false, {}, false);
    std::printf("  poultry actual %.0f min, stall %d, error %.1f%%\n", r6.actual_total_min, r6.stall_detected,
                mean_abs_error_pct(r6, 0.0f));
    CHECK(!r6.stall_detected);
  }

  // 6b) Cold, windy day: the pit holds 12 °C under its setpoint. The predictor
  // is told the setpoint but should plan with what the pit actually holds.
  {
    auto r = run_cook(3.6f, 107.0f, 93.0f, pork, hist.priors(pork, 3.6f, 107.0f, false), false, {}, false, -12.0f);
    float e = mean_abs_error_pct(r, 0.3f);
    std::printf("  cold-day cook (pit 12 C under setpoint) actual %.0f min, error %.1f%%\n", r.actual_total_min, e);
    CHECK(e < 20.0f);
  }
  // 6c) Environment changes priors: dry air lengthens the expected stall.
  {
    cook::Environment dry, humid;
    dry.humidity = 15;
    humid.humidity = 85;
    auto pd = empty.priors(pork, 3.6f, 107.0f, false, dry);
    auto ph = empty.priors(pork, 3.6f, 107.0f, false, humid);
    CHECK(pd.stall_h > ph.stall_h);
  }

  // 7) History persistence round trip and capacity.
  {
    cook::CookHistory h;
    for (int i = 0; i < 45; i++) {
      cook::CookRecord rec = r1.record;
      rec.weight_kg = 3.0f + i * 0.01f;
      h.add(rec);
    }
    CHECK(h.count() == cook::CookHistory::CAPACITY);
    cook::CookRecord blob[cook::CookHistory::CAPACITY];
    h.save(blob, cook::CookHistory::CAPACITY);
    cook::CookHistory h2;
    h2.load(blob, cook::CookHistory::CAPACITY);
    CHECK(h2.count() == h.count());
    CHECK(std::fabs(h2.records().back().weight_kg - (3.0f + 44 * 0.01f)) < 1e-4f);
  }

  // 8) Probe slip detection.
  {
    cook::Predictor p;
    p.set_target(93.0f);
    double t = 0;
    for (int i = 0; i < 120; i++, t += 1.0 / 60)
      p.add_sample(t, 40.0f + i * 0.1f, 110.0f);
    CHECK(!p.probe_suspect());
    p.add_sample(t, 100.0f, 110.0f);
    t += 1.0 / 60;
    p.add_sample(t, 101.0f, 110.0f);
    CHECK(p.probe_suspect());
  }
}

// ---------------------------------------------------------------- programs

static void test_program() {
  std::printf("program\n");
  std::vector<std::string> probes = {"pit", "food1", "food2"};
  cook::Program prog;
  std::string err;
  const char *text =
      "name: Pork butt\n"
      "pit 250 until food1 >= 165 for 30m\n"
      "pit 300 until food1 >= 200; hold 160 notify \"Pork done - resting\"";
  CHECK(cook::parse_program(text, probes, true, prog, err));
  CHECK(prog.name == "Pork butt");
  CHECK(prog.steps.size() == 3);
  NEAR(prog.steps[0].pit_c, (250 - 32) * 5.0f / 9.0f, 0.01f);
  CHECK(prog.steps[0].until.size() == 1 && prog.steps[0].until[0].hold_min == 30);
  CHECK(prog.steps[2].hold && prog.steps[2].notify == "Pork done - resting");

  // Round trip.
  std::string canon = cook::format_program(prog, probes, true);
  cook::Program p2;
  CHECK(cook::parse_program(canon, probes, true, p2, err));
  CHECK(p2.steps.size() == 3);

  // Errors are reported with the step number.
  CHECK(!cook::parse_program("pit 250 until food9 >= 160", probes, true, p2, err));
  CHECK(err.find("step 1") != std::string::npos && err.find("food9") != std::string::npos);
  CHECK(!cook::parse_program("pit 250; pit until", probes, true, p2, err));
  CHECK(err.find("step 2") != std::string::npos);

  // Mixed units and other conditions.
  CHECK(cook::parse_program("pit 110C until food2 done or after 2h; pit 275F until stall_end food1; shutdown",
                            probes, true, p2, err));
  CHECK(p2.steps[0].until.size() == 2 && p2.steps[0].until[1].type == cook::Condition::AFTER &&
        p2.steps[0].until[1].value == 120);
  NEAR(p2.steps[1].pit_c, (275 - 32) * 5.0f / 9.0f, 0.01f);
  CHECK(p2.steps[2].shutdown);

  // Run it.
  cook::ProgramRunner run;
  run.load(prog);
  auto o = run.start(0);
  CHECK(o.set_pit && std::fabs(o.pit_c - 121.11f) < 0.1f);
  cook::RunnerInputs in;
  in.temp_c = {121, 60, NAN};
  in.done = {false, false, false};
  in.stall_started = in.stall_ended = {false, false, false};
  double t = 0;
  for (; t < 100; t += 1) {
    o = run.tick(t, in);
    CHECK(!o.step_changed);
  }
  in.temp_c[1] = 74.0f;  // 165.2 °F
  bool advanced = false, dipped = false;
  for (int i = 0; i < 40 && !advanced; i++, t += 1) {
    o = run.tick(t, in);
    if (o.step_changed) {
      advanced = true;
      CHECK(i >= 29);  // held 30 minutes
      CHECK(std::fabs(o.pit_c - 148.89f) < 0.1f);
    }
    // A brief dip resets the hold timer.
    if (i == 10 && !dipped) {
      dipped = true;
      in.temp_c[1] = 73.0f;
      run.tick(t, in);
      in.temp_c[1] = 74.0f;
      i = -1;  // restart count
    }
  }
  CHECK(advanced && run.step() == 1);
  std::string d = run.describe(t, in, probes, true);
  std::printf("  %s\n", d.c_str());
  CHECK(d.find("Step 2/3") != std::string::npos);

  // Plan for the predictor.
  auto plan = run.plan_for_probe(1, t, NAN);
  CHECK(plan.size() == 2 && plan[0].until == cook::PlanSegment::FOOD_GTE);

  in.temp_c[1] = 93.5f;
  o = run.tick(t, in);
  CHECK(o.step_changed && o.notifications.size() == 1 && o.finished);
  CHECK(run.state() == cook::ProgramRunner::State::FINISHED);
  NEAR(run.commanded_pit(), 71.11f, 0.1f);

  // Pause / resume re-asserts the setpoint.
  cook::ProgramRunner r2;
  r2.load(prog);
  r2.start(0);
  r2.pause(1, "manual setpoint change");
  CHECK(r2.state() == cook::ProgramRunner::State::PAUSED);
  auto ro = r2.resume(5);
  CHECK(ro.set_pit && r2.state() == cook::ProgramRunner::State::RUNNING);
  auto so = r2.skip(6);
  CHECK(so.step_changed && r2.step() == 1);
}

// Regression tests for review findings.
static void test_regressions() {
  std::printf("regressions\n");
  std::vector<std::string> probes = {"pit", "food1", "food2"};
  std::string err;
  cook::Program p;
  // Pause doesn't count towards 'after'; step elapsed stays correct while paused.
  CHECK(cook::parse_program("pit 250 until after 2h; pit 275", probes, true, p, err));
  cook::ProgramRunner r;
  r.load(p);
  r.start(300);
  r.pause(400, "test");
  NEAR(r.step_elapsed_min(450), 100.0, 0.01);
  r.resume(500);
  cook::RunnerInputs in;
  in.temp_c = {120, 60, NAN};
  in.done = in.stall_started = in.stall_ended = {false, false, false};
  CHECK(!r.tick(519, in).step_changed);  // 100 + 19 = 119 min elapsed
  CHECK(r.tick(521, in).step_changed);   // 121 min
  // A probe dropout freezes a 'for' timer instead of resetting it.
  CHECK(cook::parse_program("pit 250 until food1 >= 165 for 30m; pit 275", probes, true, p, err));
  cook::ProgramRunner r2;
  r2.load(p);
  r2.start(0);
  in.temp_c[1] = cook::profiles()[0].stall_onset_c + 20;  // well above 165F
  for (int m = 0; m < 29; m++)
    r2.tick(m, in);
  in.temp_c[1] = NAN;
  r2.tick(29, in);
  in.temp_c[1] = 80;
  CHECK(!r2.tick(30, in).step_changed);  // the dropout minute doesn't count towards the 30
  CHECK(r2.tick(31, in).step_changed);
  // 'for' after every condition type round-trips; units with a space; mismatched units rejected.
  CHECK(cook::parse_program("pit 250 until food1 stall ends for 30m or after 2 h", probes, true, p, err));
  CHECK(p.steps[0].until[0].hold_min == 30 && p.steps[0].until[1].value == 120);
  cook::Program p3;
  CHECK(cook::parse_program(cook::format_program(p, probes, true), probes, true, p3, err));
  CHECK(cook::parse_program("pit 250 until food1 >= 165 F", probes, true, p, err));
  NEAR(p.steps[0].until[0].value, 73.89f, 0.01f);
  CHECK(!cook::parse_program("pit 30m", probes, true, p, err));
  CHECK(!cook::parse_program("pit 250 until after 2F", probes, true, p, err));
  CHECK(!cook::parse_program("pit 250 until after 17:30", probes, true, p, err));

  // Briefly stepping the target below the current temperature doesn't record a cook.
  {
    cook::Predictor pr;
    pr.set_target(93.0f);
    double t = 0;
    float core = 20;
    for (int i = 0; i < 300; i++, t += 1.0 / 60) {
      core += 0.15f;
      pr.add_sample(t, core, 110.0f, 110.0f);
    }
    pr.set_target(40.0f);  // stepped below for 2 minutes
    for (int i = 0; i < 2; i++, t += 1.0 / 60)
      pr.add_sample(t, core, 110.0f, 110.0f);
    pr.set_target(93.0f);
    for (int i = 0; i < 10; i++, t += 1.0 / 60)
      pr.add_sample(t, core, 110.0f, 110.0f);
    cook::CookRecord rec;
    CHECK(!pr.take_completed(rec));
    CHECK(pr.phase() != cook::Phase::DONE);
  }
  // Pause, resume, then a dropout: the pause isn't counted twice.
  {
    cook::Program pp;
    std::string e2;
    CHECK(cook::parse_program("pit 250 until food1 >= 165 for 30m; pit 275", {"pit", "food1"}, true, pp, e2));
    cook::ProgramRunner rr;
    rr.load(pp);
    rr.start(0);
    cook::RunnerInputs ii;
    ii.temp_c = {120, 80};
    ii.done = ii.stall_started = ii.stall_ended = {false, false};
    for (int m = 0; m <= 20; m++)
      rr.tick(m, ii);
    rr.pause(20, "test");
    rr.resume(80);
    ii.temp_c[1] = NAN;
    rr.tick(81, ii);
    ii.temp_c[1] = 80;
    bool adv = false;
    double at = 0;
    for (int m = 82; m < 200 && !adv; m++)
      if (rr.tick(m, ii).step_changed) {
        adv = true;
        at = m;
      }
    CHECK(adv && at >= 90 && at <= 92);
  }
  // Target lowered 2 minutes after done while the food stays above it: still one record.
  {
    cook::Predictor pr;
    pr.set_target(70.0f);
    double t = 0;
    float core = 20;
    for (int i = 0; i < 400 && core < 72; i++, t += 1.0 / 60) {
      core += 0.15f;
      pr.add_sample(t, core, 110.0f, 110.0f);
    }
    for (int i = 0; i < 2; i++, t += 1.0 / 60)
      pr.add_sample(t, core, 110.0f, 110.0f);
    pr.set_target(69.0f);
    int records = 0;
    cook::CookRecord rec;
    for (int i = 0; i < 12; i++, t += 1.0 / 60) {
      pr.add_sample(t, core, 110.0f, 110.0f);
      if (pr.take_completed(rec))
        records++;
    }
    CHECK(records == 1);
  }
  // Pulling the probe 2 minutes after done still records the cook (once), and unplugging too.
  for (int mode = 0; mode < 2; mode++) {
    cook::Predictor pr;
    pr.set_target(70.0f);
    double t = 0;
    float core = 20;
    for (int i = 0; i < 400 && core < 72; i++, t += 1.0 / 60) {
      core += 0.15f;
      pr.add_sample(t, core, 110.0f, 110.0f);
    }
    for (int i = 0; i < 2; i++, t += 1.0 / 60)
      pr.add_sample(t, core, 110.0f, 110.0f);
    int records = 0;
    cook::CookRecord rec;
    for (int i = 0; i < 20; i++, t += 1.0 / 60) {
      pr.add_sample(t, mode == 0 ? 25.0f : NAN, 110.0f, 110.0f);  // pulled to room temp / unplugged
      if (pr.take_completed(rec))
        records++;
    }
    CHECK(records == 1);
    CHECK(records == 0 || (rec.total_h > 5.0f && rec.total_h < 6.5f));
  }
}

// ---------------------------------------------------------------- fuel gauge, forecast, rest

static void test_fuel() {
  std::printf("fuel\n");
  // A "true" grill that burns 30 % faster than the default k; learn it from start/top-up/end readings.
  cook::FuelGauge g;
  const float cap = g.capacity_kg();
  float true_k = g.k(cook::FuelGauge::BRIQUETTES) * 1.3f;
  for (int cookn = 0; cookn < 3; cookn++) {
    double t = 0;
    float truth = 0.75f * cap;  // started 3/4 full
    g.level(t, 0.75f);
    bool topped = false;
    for (int m = 0; m < 6 * 60; m++, t += 1.0 / 60) {
      float pit = 107, amb = 5, fan = 0.35f;
      truth -= true_k * (pit - amb) * (0.3f + 0.7f * fan) / 60.0f;
      g.update(t, pit, amb, fan);
      if (!topped && m == 3 * 60) {
        // "Added a quarter of a hopper" (exact amount): stays calibratable.
        truth += 0.25f * cap;
        g.add(t, 0.25f);
        topped = true;
      }
    }
    float remaining = truth / cap;
    float est = g.level_fraction();
    std::printf("  cook %d: estimated %.0f%% vs actual %.0f%% before the end reading (k %.4f, true %.4f)\n", cookn + 1,
                100 * est, 100 * remaining, g.k(cook::FuelGauge::BRIQUETTES), true_k);
    if (cookn == 2)
      CHECK(std::fabs(est - remaining) < 0.05f);
    g.end(t, remaining);
  }
  NEAR(g.k(cook::FuelGauge::BRIQUETTES), true_k, true_k * 0.12f);
  // "Topped back up to 1/2" (amount unknown): no calibration from that stretch, estimate continues from 1/2.
  cook::FuelGauge h;
  h.level(0, 0.75f);
  for (int m = 1; m <= 120; m++)
    h.update(m / 60.0, 120, 10, 0.5f);
  float before = h.level_fraction();
  h.refill_to(2.0, 0.5f);
  NEAR(h.level_fraction(), 0.5f, 1e-4);
  CHECK(before < 0.75f && before > 0.4f);
  CHECK(!h.take_k_updated());
  // Hours left and lump vs briquettes are separate.
  h.update(2.5, 120, 10, 0.5f);
  CHECK(h.hours_left() > 1.0f && h.hours_left() < 20.0f);
  h.set_fuel(cook::FuelGauge::LUMP);
  CHECK(h.model_rate(120, 10, 0.5f) != 0);
}

static void test_forecast_and_rest() {
  std::printf("forecast and rest\n");
  int pork = cook::profile_index("Pork shoulder");
  cook::CookHistory hist;
  auto pri = hist.priors(pork, 3.6f, 107.0f, false);
  // Same cook state; a forecast 15 °C colder later should push the finish out.
  auto setup = [&](cook::Predictor &p) {
    p.set_profile(pork);
    p.set_target(93.0f);
    p.set_priors(pri);
    cook::Environment e;
    e.ambient_c = 10;
    p.set_environment(e);
    double t = 0;
    float core = 20;
    for (int i = 0; i < 180; i++, t += 1.0 / 60) {
      core += 0.18f;
      p.add_sample(t, core, 107.0f, 107.0f);
    }
  };
  cook::Predictor a, b;
  setup(a);
  setup(b);
  b.set_ambient_forecast({{0, 10}, {120, 0}, {240, -5}, {720, -5}});
  auto pa = a.predict({}, 107.0f), pb = b.predict({}, 107.0f);
  std::printf("  ETA %.0f min (steady) vs %.0f min (colder forecast)\n", pa.minutes, pb.minutes);
  CHECK(pa.valid && pb.valid && pb.minutes > pa.minutes);

  // Rest coach: pull, carryover peak, then cooling towards room temperature.
  cook::Predictor r;
  r.set_profile(pork);
  r.set_target(93.0f);
  r.set_priors(pri);
  NEAR(r.pull_at(), 93.0f - pri.carryover_c, 0.01f);
  double t = 0;
  float core = 60;
  for (int i = 0; i < 240; i++, t += 1.0 / 60) {
    core = std::min(91.0f, core + 0.2f);
    r.add_sample(t, core, 107.0f, 107.0f);
  }
  r.set_pulled(t, true);
  CHECK(r.phase() == cook::Phase::RESTING);
  // Pulled at "pull at", below the target: the cook is still recorded and the rest belongs to it.
  {
    cook::CookRecord pr;
    CHECK(r.take_completed(pr));
    NEAR(pr.target_c, 93.0f, 0.01f);
    CHECK(pr.total_h > 0);
    CHECK(r.rest_has_record());
  }
  float rest_before = r.rest_minutes_to(65.0f, 21.0f);
  // coast up 2.5 °C over 15 min, then Newton cooling with k = 0.4/h
  float peak = core + 2.5f;
  for (int i = 0; i < 90; i++, t += 1.0 / 60) {
    float T = i < 15 ? core + 2.5f * i / 15.0f : 21.0f + (peak - 21.0f) * std::exp(-0.4f * (i - 15) / 60.0f);
    r.add_sample(t, T, 30.0f, NAN);
  }
  float carry = 0, k = 0;
  CHECK(r.take_rest_result(carry, k));
  std::printf("  carryover %.1f C, cooling k %.2f/h, rest-to-65C estimate before: %.0f min\n", carry, k, rest_before);
  NEAR(carry, 2.5f, 0.4f);
  NEAR(k, 0.4f, 0.08f);
  float left = r.rest_minutes_to(65.0f, 21.0f);
  CHECK(!std::isnan(left) && left > 0);
  // Toggling "pulled" off and on again doesn't reopen the stored rest result.
  r.set_pulled(t, false);
  r.set_pulled(t, true);
  CHECK(!r.rest_has_record());
  // A finish pending commit survives a source switch (end_cook), then the slot starts afresh.
  {
    cook::Predictor q;
    q.set_profile(pork);
    q.set_target(70.0f);
    q.set_priors(pri);
    double tq = 0;
    float cq = 30;
    for (int i = 0; i < 137; i++, tq += 1.0 / 60) {  // done at ~134: still within the 5-min commit window
      cq = std::min(71.0f, cq + 0.3f);
      q.add_sample(tq, cq, 107.0f, 107.0f);
    }
    CHECK(q.phase() == cook::Phase::DONE);
    cook::CookRecord qr;
    CHECK(!q.take_completed(qr));  // not committed yet
    q.end_cook();
    CHECK(q.take_completed(qr));
    CHECK(q.phase() == cook::Phase::NO_PROBE);
  }
  // History learns carryover for the next similar cook.
  cook::CookRecord rec;
  rec.profile = uint8_t(pork);
  rec.weight_kg = 3.6f;
  rec.pit_c = 107;
  rec.k_pre = 0.2f;
  uint32_t seq = hist.add(rec);
  CHECK(hist.set_rest(seq, 5.0f, 0.4f));
  auto pri2 = hist.priors(pork, 3.6f, 107.0f, false);
  CHECK(pri2.carryover_c > pri.carryover_c);
  CHECK(pri2.rests == 1 && pri.rests == 0);
}

static void test_wifi_setup() {
  std::printf("grill wi-fi setup messages\n");
  using namespace g980proto;
  // Scan result: ssid "Grill-Net", bssid 11:22:33:44:55:66, security 2, signal 44, flags 0.
  std::vector<uint8_t> n = {0x00, 0x10, 0x00, 0x00, 9};
  for (char c : std::string("Grill-Net"))
    n.push_back(uint8_t(c));
  for (uint8_t b : {0x11, 0x22, 0x33, 0x44, 0x55, 0x66})
    n.push_back(b);
  n.push_back(2);
  n.push_back(44);
  n.push_back(0);
  WifiScanResult r;
  CHECK(parse_wifi_scan_result(n.data(), n.size(), r));
  CHECK(r.ssid == "Grill-Net" && r.bssid[0] == 0x11 && r.bssid[5] == 0x66 && r.security == 2 && r.signal == 44);
  CHECK(!parse_wifi_scan_result(n.data(), n.size() - 1, r));  // truncated
  n[1] = 0x19;
  CHECK(!parse_wifi_scan_result(n.data(), n.size(), r));      // a status frame, not a scan result
  // Credentials: 01 00 [len] bssid 01 [pass_len] pass
  std::vector<uint8_t> m;
  CHECK(build_wifi_credentials(r.bssid, "secret12", m));
  std::vector<uint8_t> want = {0x01, 0x00, 16, 0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x01, 8,
                               's', 'e', 'c', 'r', 'e', 't', '1', '2'};
  CHECK(m == want);
  CHECK(!build_wifi_credentials(r.bssid, std::string(64, 'x'), m));  // WPA2 passwords are at most 63
}

static void test_sources_and_upgrade() {
  std::printf("h5198 / fuel idle gap / record layout\n");
  // H5198 (layout per govee-ble; synthetic packets shaped like a real unit's 20-byte manufacturer data).
  {
    // Probes 1 & 2 (type 0x41): probe 1 at 80.00 C, high alarm 93.00 C, no low alarm; probe 2 unplugged.
    uint8_t a[20] = {0x10, 0x20, 0x00, 0x02, 0x01, 0xAA, 0x41, 0x80,
                     0x1F, 0x40, 0x24, 0x54, 0xFF, 0xFF,   // probe A: temp, high, low
                     0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};  // probe B: unplugged
    auto ra = h5198::decode(a, sizeof(a));
    CHECK(ra.first_probe == 0);
    NEAR(ra.temp_c[0], 80.0f, 0.001f);
    NEAR(ra.alarm_high_c[0], 93.0f, 0.001f);
    CHECK(std::isnan(ra.alarm_low_c[0]));
    CHECK(std::isnan(ra.temp_c[1]) && std::isnan(ra.alarm_high_c[1]));
    // Every type byte variant for probes 1&2 and 3&4.
    for (uint8_t t : {1, 65, 129, 193}) {
      a[6] = t;
      CHECK(h5198::decode(a, sizeof(a)).first_probe == 0);
    }
    for (uint8_t t : {2, 66, 130, 194}) {
      a[6] = t;
      CHECK(h5198::decode(a, sizeof(a)).first_probe == 2);
    }
    // Probe 4 (second of 3&4) at 25.00 C; 0.00 C is a real reading, not "unplugged".
    uint8_t b[20] = {0};
    b[6] = 0xC2;
    b[14] = 0x09;
    b[15] = 0xC4;
    auto rb = h5198::decode(b, sizeof(b));
    CHECK(rb.first_probe == 2);
    NEAR(rb.temp_c[0], 0.0f, 0.001f);
    NEAR(rb.temp_c[1], 25.0f, 0.001f);
    b[6] = 0x03;
    CHECK(h5198::decode(b, sizeof(b)).first_probe == -1);  // not a probe packet
    CHECK(h5198::decode(b, 16).first_probe == -1);         // wrong length
  }

  // Fuel: a check after the grill sat cold for hours (top-ups between cooks) must not teach the burn rate.
  cook::FuelGauge g;
  float k0 = g.k(cook::FuelGauge::BRIQUETTES);
  g.level(0, 1.0f);
  for (int m = 0; m <= 180; m++)
    g.update(m / 60.0, 110, 15, 0.5f);  // 3 h cooking
  for (int m = 181; m <= 60 * 15; m += 10)
    g.update(m / 60.0, 25, 15, 0);  // overnight: off, a little warmer than outside (sun, the house wall)
  g.level(15.0, 0.75f);  // "started at 3/4" next morning, after an unreported top-up
  CHECK(g.k(cook::FuelGauge::BRIQUETTES) == k0);
  CHECK(!g.take_k_updated());

  // Fuel: a 2 h grill-link dropout mid-cook must not teach a higher burn rate.
  {
    cook::FuelGauge f;
    float k0 = f.k(cook::FuelGauge::BRIQUETTES);
    f.level(0, 1.0f);
    for (int m = 1; m <= 360; m++)
      f.update(m / 60.0, (m > 120 && m <= 240) ? NAN : 110.0f, 15, 0.5f);
    float est = f.level_fraction();
    f.level(6.0, est - 0.15f);  // real fire burned more while unseen
    CHECK(f.k(cook::FuelGauge::BRIQUETTES) == k0);
    // A short dropout is bridged by the last rate: the gauge keeps falling.
    cook::FuelGauge g2;
    g2.level(0, 1.0f);
    for (int m = 1; m <= 60; m++)
      g2.update(m / 60.0, 110.0f, 15, 0.5f);
    float before = g2.level_fraction();
    for (int m = 61; m <= 70; m++)
      g2.update(m / 60.0, NAN, 15, 0.5f);
    CHECK(g2.level_fraction() < before);
    // ...but not for hours with the grill off.
    for (int m = 71; m <= 600; m += 5)
      g2.update(m / 60.0, NAN, 15, 0.5f);
    float off = g2.level_fraction();
    for (int m = 605; m <= 900; m += 5)
      g2.update(m / 60.0, NAN, 15, 0.5f);
    CHECK(g2.level_fraction() == off);
  }

  // 0.1.x records are the first 48 bytes of today's.
  CHECK(offsetof(cook::CookRecord, carryover_c) == 48);
  CHECK(sizeof(cook::CookRecord) == 56);
}

static void test_pin_auth() {
  using namespace pinauth;
  auto hex = [](const Digest &d) { return to_hex(d.data(), d.size()); };
  // Published vectors: FIPS 180-2, RFC 4231 case 1, RFC 7914 / PBKDF2-HMAC-SHA256.
  CHECK(hex(sha256((const uint8_t *) "abc", 3)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  uint8_t k[20];
  memset(k, 0x0b, 20);
  CHECK(hex(hmac_sha256(k, 20, (const uint8_t *) "Hi There", 8)) ==
        "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7");
  uint8_t out[32];
  pbkdf2_sha256((const uint8_t *) "password", 8, (const uint8_t *) "salt", 4, 1, out, 32);
  CHECK(to_hex(out, 32) == "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b");
  pbkdf2_sha256((const uint8_t *) "password", 8, (const uint8_t *) "salt", 4, 4096, out, 32);
  CHECK(to_hex(out, 32) == "c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a");

  CHECK(pin_problem("12345") != "");    // too short
  CHECK(pin_problem("123456") != "");   // sequence
  CHECK(pin_problem("111111") != "");   // repeated
  CHECK(pin_problem("482913") == "");

  uint32_t clock = 1000;
  uint8_t seed = 1;
  Guard g([&](uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) b[i] = seed++; }, [&]() { return clock; });
  CHECK(!g.pin_set());
  CHECK(g.login("482913") == "");                // no PIN yet: nothing to log in to
  CHECK(g.set_pin("482913", "") == "");
  CHECK(g.pin_set());
  // Only salt + hash are stored, never the PIN.
  CHECK(memmem(&g.stored(), sizeof(Stored), "482913", 6) == nullptr);
  std::string t = g.login("482913");
  CHECK(t.size() == 64 && g.check(t) && !g.check(std::string(64, '0')));
  // Changing needs the current PIN, and logs everyone out.
  CHECK(g.set_pin("739215", "000000") != "");
  CHECK(g.set_pin("739215", "482913") == "");
  CHECK(!g.check(t));
  // Five wrong PINs: locked 30 s, then doubling; a right PIN during the lockout is refused.
  for (int i = 0; i < 4; i++) CHECK(g.login("999999") == "" && g.locked_for() == 0);
  CHECK(g.login("999999") == "" && g.locked_for() == 30);
  CHECK(g.login("739215") == "");
  clock += 31000;
  CHECK(g.login("999999") == "" && g.locked_for() == 60);
  clock += 61000;
  t = g.login("739215");
  CHECK(t.size() == 64 && g.locked_for() == 0);
  // Sessions last 12 h from their last use.
  clock += 11UL * 3600 * 1000;
  CHECK(g.check(t));
  clock += 13UL * 3600 * 1000;
  CHECK(!g.check(t));
  // Sessions survive a restart: saved, then restored into a new Guard (12 h from then); junk is ignored.
  t = g.login("739215");
  uint32_t gen = g.generation();
  std::string t2 = g.login("739215");
  CHECK(g.generation() != gen && g.tokens().size() == 2);
  Guard g2([&](uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) b[i] = seed++; }, [&]() { return clock; });
  g2.load(g.stored());
  g2.restore({t, t2, "not-a-token", std::string(64, 'Z')});
  CHECK(g2.check(t) && g2.check(t2) && g2.tokens().size() == 2);
  gen = g2.generation();
  g2.logout(t);
  CHECK(!g2.check(t) && g2.check(t2) && g2.generation() != gen);
  // A controller up for more than 24.8 days (millis() past 2^31) that never had a wrong PIN isn't "locked".
  {
    uint32_t c2 = 0x80000100u;
    uint8_t sd = 7;
    Guard g3([&](uint8_t *b, size_t n) { for (size_t i = 0; i < n; i++) b[i] = sd++; }, [&]() { return c2; });
    CHECK(g3.set_pin("482913", "") == "");
    CHECK(g3.locked_for() == 0 && g3.login("482913").size() == 64);
    for (int i = 0; i < 5; i++) g3.login("999999");
    CHECK(g3.locked_for() == 30);
    c2 += 31000;
    CHECK(g3.locked_for() == 0 && g3.login("482913").size() == 64);
    c2 += 0x80000000u;  // the old lockout time comes round again: still not locked
    CHECK(g3.locked_for() == 0);
    CHECK(g3.new_session().size() == 64);
  }
  // Recovery clears everything.
  g.clear();
  CHECK(!g.pin_set() && g.login("739215") == "");
  printf("pin auth ok\n");
}

int main() {
  test_pin_auth();
  test_protocol();
  test_wifi_setup();
  test_sources_and_upgrade();
  test_program();
  test_regressions();
  test_fuel();
  test_forecast_and_rest();
  test_predictor();
  if (failures) {
    std::printf("\n%d check(s) FAILED\n", failures);
    return 1;
  }
  std::printf("\nall tests passed\n");
  return 0;
}
