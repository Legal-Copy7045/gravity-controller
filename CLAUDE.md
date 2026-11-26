# CLAUDE.md: gravity-controller

ESPHome bridge/controller for a Char-Griller Gravity 980 (firmware/, components/), the Smoker Home Assistant
integration (custom_components/smoker, installed through HACS) and the Home Assistant package
(homeassistant/packages/smoker.yaml). This repo is **public**: never commit anything that identifies the owner, his
family or his home (names, addresses, entity/device ids or hostnames from the real Home Assistant, emails, Wi-Fi
names, credentials, his grill photo).

## Releases

- `VERSION`, `custom_components/smoker/manifest.json` and `firmware/base.yaml` (`project_version`) carry the same
  version, plus a `CHANGELOG.md` entry (`.github/scripts/check_versions.py`). A push to `main` with a new VERSION
  builds, tests and creates release `v<VERSION>` (firmware, integration zip, package zip) and the web installer
  (GitHub Pages).
- Brand files: edit `brand/`, then `python3 tools/brand_sync.py` (CI checks it).
- Before pushing a release, run the quick suites locally (`make -C tests`, the host build compile, pytest
  `tests/integration`, `tests/ha_check.py`, `tests/ha_templates.py`, `tests/render_page.py`, and a scenario group only
  when a scenario changed: `SCENARIO_GROUP=A|B|C python3 tests/e2e_scenarios.py`). Don't run the whole scenario suite
  locally as well: the release build runs everything (scenario groups side by side, ~15 min) and publishes only if it
  all passes. The full local run is for `/regression`.

## The package travels with the integration (keep them in step)

- `homeassistant/packages/smoker.yaml` is the source. **Whenever you change it, copy it to
  `custom_components/smoker/package/smoker.yaml`** (the integration ships that copy; a test fails if they differ).
- The action `smoker.install_package` (admin) writes the bundled copy to `/config/packages/smoker.yaml`, filling in the
  phone's notify action, the AI task and the weather entity, and records those choices on the file's first line.
- From 0.2.19, every start of the integration (so every HACS update) rewrites a package it installed when the bundled
  one differs (same choices, backup kept, last 3) and reloads input_*/timer/template/script/automation, so an update
  needs only the one restart HACS asks for. A package copied in by hand is never touched.

## Rolling out a release to the owner's Home Assistant (he asked for this to happen on every update)

After the release exists: HACS update entity `update.smoker_gravity_980` → `update.install` with `version: v<VERSION>`;
`POST /api/config/core/check_config` must be valid; restart Home Assistant (needs the owner's go-ahead in the session if
the permission classifier asks); then refresh and install `update.smoker_firmware` (OTA, ~1 min). The package then
updates itself (see above): confirm the "Smoker package" notification or the file's first line. Never control the
grill, never turn the AI advisor on/off for him, and never touch other devices.

## The two dashboards share their layout

`custom_components/smoker/frontend/page.html` (Home Assistant) and `firmware/device-ui/ui.js` (the controller) carry two
identical shared blocks, checked by tests/render_page.py: the cook program editor, the page sections (`SECT`: the
same `data-sect` sections, folding from the heading, planning first while idle), cook plan, serve together, cook replay
and the food list (What's cooking). Change both copies together.

## Regression suite (`regression/`, `/regression`, `/walkthrough`, `/full-check`)

Three commands (`.claude/skills/<name>/SKILL.md`): `/regression` (every stage + bug, security-claims and LAN-outsider
reviews), `/walkthrough` (both dashboards crawled on desktop and phone + two UX reviewers), `/full-check` (both at once).

The full regression (every test suite, a bug and a security review, one published report) is run every few releases
or after a big feature set, when the owner asks ("/regression" runs `.claude/skills/regression/SKILL.md`). Every
feature PR keeps it current: add tests for the feature, a `regression/catalogue/<area>.yaml` entry whose `match` finds
them, a `regression/manual.yaml` entry for what only the real grill can show, and commit new IDs in
`regression/ids/`. IDs are append-only. `regression/out/` is git-ignored; `regression/RUNS.md` keeps one public-safe
entry per run. Live checks are read-only and take the Home Assistant URL from the environment, never the repo.

## Security posture (docs/security.md)

Convenient, not full of holes, never a way in for code. Keep the hard lines (signed updates only, no LAN firmware
upload, other websites refused, keys write-only, AI/outside data treated as data, pinned CI); don't add friction
(PINs, windows, hidden buttons) against people the owner already trusts. Reviews use this threat model.

