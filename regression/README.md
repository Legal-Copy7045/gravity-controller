# Regression suite

One command runs every test in the repo, turns the results into one report with stable check IDs, and lists what
each feature is covered by. It is run every few releases or after a big feature set (`/regression` in a Claude Code
session runs the whole thing, reviews included; see `.claude/skills/regression/SKILL.md`), not on every push: CI
already runs the core tests and builds on every push.

```
regression/
  run.py            runs the stages -> out/<stage>.json (and out/logs/)
  report.py         out/*.json + catalogue -> out/report.html (publishable page) and out/report.md
  catalogue.py      reads catalogue/*.yaml
  catalogue/*.yaml  every feature, the release it arrived in, its docs, and the checks that cover it
  ids/<stage>.yaml  stable check IDs (append-only)
  manual.yaml       checks that need a person at the grill
  RUNS.md           one line per full run (public: no names, hosts or device ids)
  out/              results, logs, screenshots, the report (git-ignored)
```

## Running it

```bash
export ESPHOME_PYTHON=/path/to/esphome-venv/bin/python   # esphome, aioesphomeapi, aiohttp
export HA_PYTHON=/path/to/ha-venv/bin/python             # pip install -r tests/requirements-integration.txt
python3 regression/run.py --compile                       # every stage but live (see the timing below)
HA_URL=https://<your home assistant> python3 regression/run.py --stage live
REPORT_TZ=Europe/London python3 regression/report.py
```

The system `python3` needs Playwright (and Chromium) for the page and device stages, and PyYAML. `--stage NAME`
(repeatable) runs some stages only; `--from-logs` re-reads the last run's suite output without running it again
(useful after changing how a stage parses its output).

Stages run side by side: the quick ones (ci, core, page, integration, package, manual) in one lane, the firmware
stage then the simulated grill in another, the device page test in a third; live last. The simulated grill runs the
end-to-end test and the three scenario groups at once, each on its own copy of the test build with its own ports
(`tests/host-bridge.yaml` substitutions; compiled once, then cached). With `--compile` the device test waits for the
firmware stage, which rebuilds the test build it uses.

| Stage | Prefix | What runs | Notes |
|---|---|---|---|
| ci | `CI-` | `check_versions.py`, `brand_sync.py --check`, `privacy_guard.py`, `release_notes.py`, package copy, shared blocks, workflow hygiene | seconds |
| core | `CORE-` | `make -C tests` (C++ unit tests: protocol, programs, predictor, fuel, PIN, local-only hosts) | one result per test section |
| firmware | `FW-` | `esphome config` of the bridge, the no-HA build and the host build; `--compile` compiles them (throwaway signing key, deleted after) | plus firmware config assertions |
| sim | `SIM-` | `tests/e2e.py` and `tests/e2e_scenarios.py`: the host build against `tools/fake_grill.py` | power cuts, alerts, programs |
| device | `DEV-` | `tests/webui_e2e.py`: the controller's own page in Chromium against the host build | 1440 and 390 px, PIN, other origins |
| page | `PAGE-` | `tests/render_page.py`: the Home Assistant dashboard with mock states | failure-only test: grouped into named checks |
| integration | `INT-` | `pytest tests/integration` | one result per test |
| package | `PKG-` | `tests/ha_check.py` (HA's config check) and `tests/ha_templates.py` | |
| live | `LIVE-` | read-only: installed versions, pending updates, config check, entities available, local only off, GitHub release | needs `HA_URL`; never switches anything |
| manual | `MAN-` | `manual.yaml` | listed as "need a person" |

## Results

Each stage writes `out/<stage>.json`:

```json
{"stage": "sim", "started": "...", "finished": "...", "environment": {},
 "results": [{"id": "SIM-031", "feature": "Power-cut recovery: ...", "check": "scenarios: scenario 6: grill turned back on",
              "status": "pass|fail|skip|manual", "detail": "...", "evidence": "regression/out/logs/sim-scenarios.log"}]}
```

A stage that crashes or exits with an error but no failed check adds `<PREFIX>-RUN` (fail).

**IDs are stable.** A check's key is its words without the values it printed (`pit + changed the grill's target
(225.0 -> 230.0)` -> `pit + changed the grill's target`), under its section (`1440px`, `scenario 6`). The first run
of a new check gives it the next free number in `ids/<stage>.yaml`; commit that file. Never renumber or reuse an ID.
Renamed a check? Edit its key in `ids/<stage>.yaml` so it keeps its ID. A key that a run no longer produces shows as
skipped ("not produced by this run") until its line is deleted; its number is never given out again.

## The catalogue

`catalogue/<area>.yaml` lists every feature:

```yaml
- feature: "Power-cut recovery: controller restart and grill power loss; grill turned back on"
  since: 1.4.0
  docs: docs/features.md
  checks: [SIM-031]                         # optional: exact IDs
  match: ["^sim:scenarios: scenario (4|6|6b|7):", "^manual:.*power cut"]   # regexes over "<stage>:<check>"
```

A feature is **pass** when every check it covers passed (manual/skipped ones aside), **fail** when any failed,
**not run** when nothing matched this run, **uncovered** when it lists no checks at all. The report also lists
checks that belong to no feature.

**Adding a feature (every feature PR):** add tests to the suite that fits (C++ in `tests/test_core.cpp`, a scenario in
`tests/e2e_scenarios.py`, a page check in `tests/render_page.py` / `tests/webui_e2e.py`, pytest in
`tests/integration`, a template check in `tests/ha_templates.py`), then a catalogue entry whose `match` finds them. A
behaviour that only the real grill can show gets a `manual.yaml` entry. A new test suite gets a stage in `run.py`.

## Review findings

A full run (`/regression`) also has two independent reviews write `out/findings-bugs.json` (`BUG-`) and
`out/findings-security.json` (`SEC-`, plus `claims`: each security claim in the README and docs, checked against the
code). Finding: `{id, severity critical|high|medium|low|info, area, title, file, line, description, scenario,
recommendation, verified}`. `out/notes.json` (`{summary, observations}`) adds the summary and observations. The run
fixes nothing in product code: findings go to the report and are fixed afterwards, in a release of their own.

## Live checks

The live stage is read-only by design: it reads `/api/states`, asks Home Assistant's own config check, and reads the
public GitHub release. It finds the smoker's entities by name pattern, so no entity id, host or token is in this
repo. It never controls the grill, switches the AI advisor, or touches any other device.
