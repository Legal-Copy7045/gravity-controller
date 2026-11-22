// Host unit tests for the pure-C++ core (protocol, predictor, history, programs).
// Build & run:  make -C tests
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "../components/cook_assistant/history.h"
#include "../components/cook_assistant/predictor.h"
#include "../components/cook_assistant/program.h"
#include "../components/gravity980/protocol.h"

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
                           bool wrap_at_stall, const std::vector<cook::PlanSegment> &plan_template, bool verbose) {
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
    float pit_meas = pit + 4.0f * std::sin(float(t) * 3.0f);
    step_meat(m, pit_meas, dt, wrapped);
    t += dt;
    float probe = m.core + 0.1f * std::sin(float(t) * 50.0f);
    p.add_sample(t, probe, pit_meas);
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
    if (!std::isnan(r.actual_total_min) && t * 60 > r.actual_total_min + 3) {
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
  r2.pause("manual setpoint change");
  CHECK(r2.state() == cook::ProgramRunner::State::PAUSED);
  auto ro = r2.resume(5);
  CHECK(ro.set_pit && r2.state() == cook::ProgramRunner::State::RUNNING);
  auto so = r2.skip(6);
  CHECK(so.step_changed && r2.step() == 1);
}

int main() {
  test_protocol();
  test_program();
  test_predictor();
  if (failures) {
    std::printf("\n%d check(s) FAILED\n", failures);
    return 1;
  }
  std::printf("\nall tests passed\n");
  return 0;
}
