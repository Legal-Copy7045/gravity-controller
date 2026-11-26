---
name: walkthrough
description: Independent walkthrough of every function on both Smoker dashboards (the controller's own page and the Home Assistant dashboard), on desktop and phone, Basic and Advanced: an automated browser crawl with UX checks and screenshots, then two fresh reviewers (desktop, phone), and a published report of what to merge, rename, move, remove, re-flow or keep separate. Use when asked for "/walkthrough", a usability review, or "is the UI getting confusing". Fixes nothing in product code.
---

# Walkthrough

The crawl lives in `regression/walkthrough.py` (read its docstring); the report in `regression/walkthrough_report.py`.
Four steps; finish all of them, the owner reads the report later.

**What it covers (and what it can't):** the controller's own page (served by `tests/webui_bridge.py` over a copy of the
test build with its own ports, against the fake grill) and the Home Assistant dashboard (`page.html` with the mock
states of `tests/render_page.py`), each at 1280×900 and 390×844 (phone emulation, touch), in Basic and Advanced mode,
plus the Setup page each opens. There's no screen on the controller itself and no separate phone app: the Home
Assistant companion app shows the same dashboard. A cook in progress, the first-run wizard and a locked (PIN) page are
reached only as far as the simulated grill and mock states take them: say so in the report rather than guessing.

## 1. Crawl (automated)

```bash
python3 regression/run.py --stage walkthrough      # needs ESPHOME_PYTHON (the test build and its bridge)
```

It compiles `smoker-host-test-w` once (cached), crawls 8 views (2 pages × 2 widths × 2 modes, each with its Setup
page), writes `regression/out/walkthrough/inventory.json` and `shots/*.png`, and records the UX checks under stable
`WT-` IDs in `regression/ids/walkthrough.yaml` (commit new ones): menu label matches the section's heading, no
duplicate menu labels, no horizontal scroll, nothing off screen, nothing wider than its container, phone tap targets
≥ 40×40 px, no dead links, no console errors. A `WT-RUN` failure means the crawl itself broke (a port in use:
`pkill -f webui_bridge.py`; the build missing): fix that and re-run.

## 2. Review (two fresh agents, in parallel)

Start two general-purpose agents. Give each the inventory, the screenshots (they can open images with Read) and the
code (`firmware/device-ui/ui.js` + `ui.css`, `custom_components/smoker/frontend/page.html` + `style.css`, the shared
blocks), not your own conclusions. Both are read-only and write JSON only.

- **Desktop reviewer** -> `regression/out/walkthrough/findings-desktop.json`: functions duplicated or overlapping
  (within a page, and between the two dashboards where they should match), confusing or inconsistent names (a menu
  label that isn't the heading, the same thing called two names), things in the wrong section, dead ends, flows that
  take too many steps (planning a cook, reading a label, setting a PIN), Basic vs Advanced: does Basic have what a
  first-time owner needs and nothing else.
- **Phone reviewer** -> `regression/out/walkthrough/findings-phone.json`: everything worse on a phone: layout,
  tap targets (the WT- check lists them; say which matter), the section bar, long pages and what's buried at the
  bottom, forms and keyboards, charts and tables, the Setup page.

Each finding: `{id: UX-001.. (desktop) / UX-101.. (phone), group: merge|rename|move|remove|flow|mobile|keep-separate,
title, now, proposal, affects (who: everyone, Basic users, phone users, Home Assistant users…), effort: S|M|L,
risk, evidence: ["shots/<file>.png", ...], page: device|ha|both, width: desktop|phone|both}`.

Brief both on what must stay as it is and why (`keep-separate` findings say so explicitly): power off needs two taps,
the PIN and the factory reset are deliberate, Setup is a page of its own so settings don't bury the cook, the two
dashboards share their layout code (a change goes in both: CLAUDE.md), Basic mirrors the Char-Griller app on purpose.
The threat model in `docs/security.md` applies: don't propose friction for safety's sake on a home smoker.

## 3. Report

Merge the two files into `regression/out/walkthrough/findings.json`: `{"summary": "two or three plain sentences",
"findings": [...]}` (drop duplicates between the two, keep both IDs in the title if merged). Then:

```bash
python3 regression/walkthrough_report.py
```

Publish `regression/out/walkthrough/report.html` as a private artifact (Artifact tool; first publish `icon: "layout"`),
republished to the same URL each run (the URL is in the newest `regression/WALKTHROUGHS.md` entry). Add an entry at
the top of `regression/WALKTHROUGHS.md`: date, version, commit, views, checks failing (IDs), findings per group, the
link. It's public: no names, hosts or device ids.

## 4. Commit

Commit `regression/ids/walkthrough.yaml` and `regression/WALKTHROUGHS.md` (branch, then main as usual; no version
bump). **Fix nothing in product code**: the owner picks what changes. Tell him the views crawled, the failing checks,
the findings by group (the top three), and the link.
