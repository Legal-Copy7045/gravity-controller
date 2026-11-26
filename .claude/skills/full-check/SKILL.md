---
name: full-check
description: The Smoker full regression and the UI walkthrough together, as one run: every regression stage and the walkthrough's crawl side by side, all five reviewers at once (bugs, security claims, outsider on the LAN, desktop UX, phone UX), both reports published, and one summary. Use when asked for "/full-check", or for a complete health check before or after a big release.
---

# Full check

`/regression` (`.claude/skills/regression/SKILL.md`) and `/walkthrough` (`.claude/skills/walkthrough/SKILL.md`) in one
go. Read both first: this skill only says how they fit together; the steps themselves are theirs.

## 1. Bring the suite up to date

The regression skill's step 1.

## 2. Run everything at once

```bash
python3 regression/run.py --compile --with-walkthrough
HA_URL=https://<the owner's Home Assistant> python3 regression/run.py --stage live
```

The walkthrough's crawl runs in its own lane: its own copy of the test build (`smoker-host-test-w`), its own ports
(API 6553, grill 13833, page 18580) and its own output folder (`regression/out/walkthrough/`), so it can't collide with
the simulated grill or the device page test. Don't start a second run while this one is going (each run clears stale
test processes when it starts).

## 3. All five reviewers, in parallel, while the stages run

Launch them together in one message: the regression skill's three (bugs, security claims, outsider on the LAN: step 3
there) and the walkthrough's two (desktop, phone: step 2 there). The walkthrough reviewers need the crawl's inventory
and screenshots: start them once `regression/out/walkthrough/inventory.json` exists (about 2 minutes in), the others
straight away.

## 4. Both reports

The regression skill's step 4 (notes.json, `report.py`, publish, RUNS.md) and the walkthrough skill's step 3
(findings.json, `walkthrough_report.py`, publish, WALKTHROUGHS.md). The regression report also lists the walkthrough's
WT- checks (they're a stage like any other); the walkthrough report is where its findings are.

## 5. Commit, and one summary

Both skills' last step, in one commit. Then tell the owner, in one message: the totals and failing IDs, the security
findings by severity (high first, with the one-line why), the walkthrough findings by group (the top three), and both
links. Fix nothing in product code.
