# Walkthroughs

One entry per `/walkthrough` (or `/full-check`) run, newest first: date, version, commit, views crawled, failing UX
checks, findings by group, the report link. Public: no names, hosts or device ids.

## 2026-11-26 — 1.4.10 (/full-check, commit 110b112)

- Views: 8 (controller page and Home Assistant dashboard × desktop 1280 / phone 390 × Basic / Advanced, each with its
  Setup page). The Home Assistant phone views were re-crawled after a harness fix (viewport tag) during the run.
- UX checks: 120 pass, 18 fail (WT-002, 015, 019, 034, 040, 046, 049, 053, 060, 066, 070, 087, 103, 109, 115, 122, 130,
  136): "Chart" leads to "Temperatures", the controller page's "Now" has no heading, phone tap targets under 40 px.
- Findings: 29 (UX-001..014 desktop, UX-101..115 phone): mobile 9, flow 6, merge 5, keep-separate 4, rename 2, move 2,
  remove 1.
- Report: https://claude.ai/artifact/AzbUgDEn7YQuNKUserYGzg (private).
