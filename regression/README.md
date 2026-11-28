# Regression suite

One command runs every test in the repo, turns the results into one report with stable check IDs, and lists what
each feature is covered by. It follows the owner's project standard (`~/.claude/standards/STANDARD.md` section 3;
`.github/standard.yaml` lists what this suite does beyond it and where it differs): the global Claude Code commands
**`/regression`** (every stage, three reviewers: bugs, claims, exposure = an outsider on the LAN), **`/walkthrough`**
(both dashboards crawled on desktop and phone, two UX reviewers) and **`/full-check`** (both at once) read
`profile.yaml` and this file. It is run every few releases or after a big feature set, not on every change: CI runs the
core tests and builds on every pull request.

**What the global skills need to know here** (the rest is in `profile.yaml`):
- The venvs below (`ESPHOME_PYTHON`, `HA_PYTHON`, `QUALITY_PYTHON`); `HA_URL` for the live stage (never committed).
- A `<PREFIX>-RUN` failure is usually a port in use (`pkill -f tools/fake_grill.py`, `pkill -f webui_bridge.py`;
  the runner clears stale ones itself) or a missing package. Don't start a second run while one is going.
- `regression/manual.yaml` has a check for the signing environment's branch rule (a GitHub setting): ask the owner.
- Walkthrough coverage: the controller's own page (via `tests/webui_bridge.py` over its own copy of the test build,
  ports API 6553, grill 13833, page 18580) and the Home Assistant dashboard (`page.html` with the mock states of
  `tests/render_page.py`), at 1280x900 and 390x844, Basic and Advanced, each with its Setup page. A cook in progress,
  the first-run wizard and a locked page are reached only as far as the fake grill and mock states take them: the
  report says so. Its UX checks are the standard's, with phone tap targets at 40 px (`WT-` IDs).
- Reviewers judge against `docs/security.md` (convenient, never a way in for code); reports use public-safe words only.

```
regression/
  run.py            runs the stages -> out/<stage>.json (and out/logs/)
  standard.py       the standard's shared tooling, vendored unchanged: brief, log, summary, manual, schema
  profile.yaml      the project's profile for the global skills; claims.yaml every security claim;
                    published.yaml the report URLs; manual-log.yaml manual results per version
  report.py         out/*.json + out/findings/*.json + catalogue -> out/report.html (publishable page) and out/report.md
  walkthrough.py    the walkthrough's crawl (both pages x desktop/phone x Basic/Advanced) -> out/walkthrough/
  walkthrough_report.py  out/walkthrough/ + findings -> out/walkthrough.html (and out/walkthrough/report.html)
  tests/            tests of the tooling itself (stage selection, walkthrough checks, both reports)
  catalogue.py      reads catalogue/*.yaml
  catalogue/*.yaml  every feature, the release it arrived in, its docs, and the checks that cover it
  ids/<stage>.yaml  stable check IDs (append-only)
  manual.yaml       checks that need a person at the grill
  RUNS.md           one line per full run (public: no names, hosts or device ids)
  WALKTHROUGHS.md   one line per walkthrough (public, likewise)
  out/              results, logs, screenshots, the report (git-ignored)
```

## Running it

```bash
export ESPHOME_PYTHON=/path/to/esphome-venv/bin/python   # esphome, aioesphomeapi, aiohttp
export HA_PYTHON=/path/to/ha-venv/bin/python             # pip install -r tests/requirements-integration.txt
export QUALITY_PYTHON=/path/to/quality-venv/bin/python   # pip install bandit pip-audit (ruff from PATH)
python3 regression/run.py check                           # ci + quality + core: before a pull request is marked ready
python3 regression/run.py                                 # every regression stage (live only with HA_URL set)
python3 regression/run.py --with-walkthrough              # ... and the walkthrough's crawl, side by side
python3 regression/run.py --stage walkthrough             # the crawl alone
HA_URL=https://<your home assistant> python3 regression/run.py --stage live
python3 regression/run.py brief [--full|--walkthrough]    # reviewer briefs -> out/briefs/ (standard.py)
REPORT_TZ=Europe/London python3 regression/run.py report [--walkthrough]   # out/report.html, out/walkthrough.html
python3 regression/run.py log [--walkthrough|--full-check]   # the RUNS.md / WALKTHROUGHS.md row (standard.py)
python3 regression/run.py summary                         # <= 40 lines (standard.py)
python3 regression/run.py manual "<key>" pass --note "..."   # a manual check's result for this version
```

`--no-compile` skips the firmware compiles (they're cached after the first run).

The system `python3` needs Playwright (and Chromium) for the page and device stages, and PyYAML. `--stage NAME`
(repeatable) runs some stages only; `--from-logs` re-reads the last run's suite output without running it again
(useful after changing how a stage parses its output).

Stages run side by side: the quick ones (ci, core, page, integration, package, manual) in one lane, the firmware
stage then the simulated grill in another, the device page test in a third; live last. The simulated grill runs the
end-to-end test and the three scenario groups at once, each on its own copy of the test build with its own ports
(`tests/host-bridge.yaml` substitutions; compiled once, then cached). With `--compile` the device test waits for the
firmware stage, which rebuilds the test build it uses. A run takes about 7 minutes on four cores (the simulated grill
sets the pace, ~6 min); the first run in a fresh session adds the compiles.

| Stage | Prefix | What runs | Notes |
|---|---|---|---|
| quality | `QA-` | ruff (Python errors), bandit (static security scan of the integration and tools), pip-audit of every pinned requirements file, the C++ with `-Wall -Wextra`, the pages' JavaScript parses | the audit skips offline |
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
| walkthrough | `WT-` | `walkthrough.py`: both dashboards, desktop 1280 and phone 390, Basic and Advanced and the Setup page: menu label = heading, no duplicate labels, no horizontal scroll, nothing off screen or wider than its container, phone tap targets ≥ 40 px, no dead links, no console errors | only with `--with-walkthrough` or `--stage walkthrough`; own build and ports |

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

A full run (`/regression`) also has three independent reviewers (briefed by `run.py brief`) write
`out/findings/bugs.json` (`BUG-`), `out/findings/claims.json` (`SEC-`, plus `claims`: each claim in `claims.yaml`,
held or not) and `out/findings/exposure.json` (`EXP-`), in the standard's schema (`run.py schema findings`):
`{id, severity critical|high|medium|low|info, area, title, file, line, description, scenario, recommendation,
verified}`. The older `out/findings-*.json` names still load. `out/notes.json` (`{summary, observations}`) adds the summary and observations. The run
itself fixes nothing in product code. Afterwards every finding with a clear fix goes into the next release without
asking; the owner is asked only when a fix is uncertain, weakens a security setting, changes a legal or governance
rule, or merges or removes pages (keep-separate items stay as they are). The summary says which findings will be
fixed and which need the owner (project standard 3.6).

## Live checks

The live stage is read-only by design: it reads `/api/states`, asks Home Assistant's own config check, and reads the
public GitHub release. It finds the smoker's entities by name pattern, so no entity id, host or token is in this
repo. It never controls the grill, switches the AI advisor, or touches any other device.
