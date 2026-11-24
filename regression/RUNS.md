# Regression runs

One entry per full run (newest first): version, totals, failing check IDs, finding IDs, report link.
No real names, hosts or device ids: this file is public.

## 2026-11-24 — 1.4.3

- Totals: 491 pass, 0 fail, 9 manual, 1 skip (50 features catalogued, all passing or manual).
- Stages: ci 16, core 12, firmware 15 (+1 skip), sim 99, device 178, page 36, integration 36, package 91, live 8,
  manual 9.
- Failing checks: none.
- Findings (threat model: docs/security.md): BUG-001..003 (1 high, 2 medium), SEC-001..005 (1 low, 4 info).
  36 security claims checked, 2 don't hold (SEC-001/004, SEC-002).
- Report: https://claude.ai/artifact/JgWUwkGYu3pjQ3J6aCbPqu (private)

## 2026-11-24 — 1.4.2

- Totals: 484 pass, 0 fail, 9 manual, 1 skip (50 features catalogued, all passing or manual).
- Stages: ci 16, core 12, firmware 15 (+1 skip), sim 93, device 178, page 36, integration 36, package 90, live 8,
  manual 9.
- Failing checks: none.
- Findings (threat model: docs/security.md): BUG-001..007 (1 high, 4 medium, 2 low), SEC-001..008 (5 low, 3 info).
  34 security claims checked, 2 don't hold (SEC-002/003, SEC-006).
- Report: https://claude.ai/artifact/2xHCJUGZUhaPT4jgUGxV3f (private)

## 2026-11-24 — 1.4.0 (first run)

- Totals: 464 pass, 0 fail, 9 manual, 1 skip (465 automated checks; 50 features catalogued, all passing or manual).
- Stages: ci 16, core 12, firmware 11 (+1 skip: no-HA build is config only), sim 87, device 176, page 36,
  integration 36, package 82, live 8, manual 9.
- Failing checks: none.
- Findings: BUG-001..011 (3 medium, 7 low, 1 info), SEC-001..015 (3 medium, 8 low, 4 info). Docs: 17 security
  claims checked, 4 don't hold (SEC-002, SEC-004, SEC-007, SEC-013).
- Coverage gaps: no restart during a keep or Turbo step; the host build has no standalone component (watchdog,
  update guard, controller-side Local only only unit-tested or manual).
- Report: https://claude.ai/artifact/35m3zZqHzWSN6eNaNYwqbv (private)
