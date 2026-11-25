---
name: regression
description: Run the Smoker full regression suite (every stage in regression/: controller unit tests, firmware builds, simulated grill scenarios, both dashboards, integration, package, release checks, read-only live checks), a fresh bug and security review, and publish the report. Use when asked to "run the full regression", "/regression", or for a release-health check after a big feature set. Not for ordinary changes (CI covers those).
---

# Full regression run

The suite lives in `regression/` (read `regression/README.md` first). A run has five steps. Work through them in
order; the owner usually reads the report the next morning, so finish every step and leave nothing waiting on him.

## 1. Bring the suite up to date

- Read `CHANGELOG.md` from the version of the last run onward (the newest entry in `regression/RUNS.md`).
- Every new feature, setting, service, alert or page section needs an entry in `regression/catalogue/<area>.yaml`
  whose `match` (or `checks`) finds at least one automatic check: a C++ test (`tests/test_core.cpp`), a simulated
  grill scenario (`tests/e2e_scenarios.py`), a page check (`tests/render_page.py`, `tests/webui_e2e.py`), a pytest
  (`tests/integration`) or a template check (`tests/ha_templates.py`). Write the missing tests now (tests only).
- Something only the real grill can show goes in `regression/manual.yaml` with steps.
- A new test suite gets a stage in `regression/run.py` and a line in the README's stage table.

## 2. Run the stages

Set up the venvs if the session has none (`ESPHOME_PYTHON`: `pip install esphome aioesphomeapi aiohttp`; `HA_PYTHON`:
`pip install -r tests/requirements-integration.txt`; system python3 needs playwright + pyyaml, Chromium is preinstalled
in cloud sessions). Then, in the background (the stages run side by side; see the README for the timing):

```bash
python3 regression/run.py --compile
HA_URL=https://<the owner's Home Assistant> python3 regression/run.py --stage live
```

The live stage is read-only (states, config check, GitHub release). The HA URL comes from the session's connected
services, never from the repo. If HA isn't reachable, its checks skip; say so. Check the console summary: a
`<PREFIX>-RUN` failure means a stage broke (a port in use: `pkill -f tools/fake_grill.py`, though the runner clears stale ones itself; a missing package); fix
the environment and re-run that stage with `--stage`. New check IDs land in `regression/ids/*.yaml`: commit them.

## 3. Review (two fresh agents, in parallel, while the stages run)

Start two general-purpose agents with a brief that gives them the code, not your conclusions:

- **Bugs** -> `regression/out/findings-bugs.json`: a list of `{id: BUG-001.., severity critical|high|medium|low|info,
  area, title, file, line, description, scenario, recommendation, verified}`. Focus on what changed since the last
  run, then the risky paths: power-cut recovery, alerts, programs (keep/Turbo), the update guard/rollback, local
  only, the scheduler, replay.
- **Security** -> `regression/out/findings-security.json`: `{findings: [SEC-001..], claims: [{claim, where, held,
  note}]}`, every security claim in the README and docs checked against the code (PIN, write-only secrets, other
  origins, local only, signed updates, two-tap power, notification codes, AI plan limits, sharing anonymisation,
  workflow secrets).

Both: read-only, no test suites (ports are in use), verify each finding end to end, nothing identifying the owner.
Give both the threat model in `docs/security.md`: convenience matters more than hardening against people the owner
already trusts; what must never happen is a way in for someone else's code, a leaked key, or bad outside data pushing
the grill past safe limits. Findings outside that model are `info` at most, and a fix must not add friction for it.

## 4. Report

Write `regression/out/notes.json`: `{"summary": "two or three plain sentences", "observations": ["..."]}`
(observations: coverage gaps, flaky checks, things that passed but look fragile, manual checks overdue). Then:

```bash
REPORT_TZ=<the owner's time zone, e.g. from Home Assistant's /api/config> python3 regression/report.py
```

Publish `regression/out/report.html` as a private artifact (Artifact tool; first publish `icon: "check"`), then add an
entry at the top of `regression/RUNS.md` (date, version, totals, stage counts, failing IDs, finding IDs, the report
link). RUNS.md is public: no names, hosts or device ids.

## 5. Commit

Commit the suite changes (catalogue, ids, manual.yaml, new tests, RUNS.md) and push (branch, then main as usual: no
version bump for regression-only changes). **Fix nothing in product code during the run**: the report lists the
failures and findings, and the owner decides what gets fixed in the next release. Tell him the totals, the failures,
the high findings and the report link.
