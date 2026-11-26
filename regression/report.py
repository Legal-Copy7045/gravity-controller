#!/usr/bin/env python3
"""Build the regression report from regression/out/*.json and the catalogue.

Usage: python3 regression/report.py
Writes regression/out/report.md and regression/out/report.html. The HTML is a
self-contained page (no <html>/<body> wrapper, so it can be published as a
private claude.ai artifact as it is; browsers open it locally too).

Inputs:
  out/<stage>.json           stage results (see README.md)
  out/findings-*.json        review findings: [{id, severity, area, title, file, line,
                             description, scenario, recommendation, verified}]
  out/notes.json             optional {"summary": "...", "observations": ["..."]}
  catalogue/*.yaml           features and the checks that cover them (regression/catalogue.py)
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from catalogue import claims as _claims, feature_for, load_catalogue  # noqa: E402
OUT = HERE / "out"
ROOT = HERE.parent
STAGES = ["ci", "quality", "core", "firmware", "sim", "device", "page", "integration", "package", "live", "manual", "walkthrough"]
SEV = ["critical", "high", "medium", "low", "info"]
STATUS = ["fail", "pass", "manual", "skip"]
e = html.escape


def load():
    stages = {}
    for s in STAGES + sorted({p.stem for p in OUT.glob("*.json")} - set(STAGES)):
        p = OUT / f"{s}.json"
        if not p.is_file() or s.startswith("findings") or s == "notes":
            continue
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("results"), list):  # stage files only
            stages[s] = data
    findings, claims = [], []
    for p in sorted(OUT.glob("findings*.json")):
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        findings += data if isinstance(data, list) else data.get("findings", [])
        if isinstance(data, dict):
            claims += data.get("claims", [])
    findings.sort(key=lambda f: (SEV.index(f.get("severity", "info")) if f.get("severity") in SEV else 9, f.get("id", "")))
    catalogue = load_catalogue()
    for s, d in stages.items():  # features from the catalogue as it is now (it may have changed since the stage ran)
        for r in d.get("results", []):
            r["feature"] = feature_for(catalogue, s, r["id"], r.get("check", "")) or r.get("feature", "")
    notes = json.loads((OUT / "notes.json").read_text()) if (OUT / "notes.json").is_file() else {}
    notes["_claims"] = claims
    return stages, findings, catalogue, notes


def coverage(stages, catalogue):
    allr = [(s, r) for s, d in stages.items() for r in d.get("results", []) if not r["id"].endswith("-RUN")]
    rows, referenced = [], set()
    for item in catalogue:
        got = [r for s, r in allr if _claims(item, s, r["id"], r.get("check", ""))]
        referenced |= {r["id"] for r in got}
        checks = sorted({r["id"] for r in got} | set(item.get("checks") or []), key=lambda i: (i.split("-")[0], i))
        item = {k: v for k, v in item.items() if k != "_re"}
        item["checks"] = checks
        statuses = {r["status"] for r in got}
        if not item.get("checks") and not item.get("match"):
            state = "uncovered"
        elif not got:
            state = "not run"
        elif "fail" in statuses:
            state = "fail"
        elif "pass" in statuses:
            state = "pass" if statuses <= {"pass", "manual", "skip"} else "fail"
        elif "manual" in statuses:
            state = "manual"
        else:
            state = "skip"
        ids = {r["id"] for _, r in allr}
        missing = [c for c in checks if c not in ids]
        rows.append({**item, "state": state, "missing": missing})
    unlisted = sorted({r["id"] for _, r in allr} - referenced)
    return rows, unlisted


def ranges(ids):
    """['DEV-001', 'DEV-002', 'DEV-003', 'SIM-009'] -> 'DEV-001..003, SIM-009'."""
    out, run = [], []
    for i in list(ids or []) + [None]:
        if i and run and i.split("-")[0] == run[-1].split("-")[0] and i.split("-")[1].isdigit() and int(i.split("-")[1]) == int(run[-1].split("-")[1]) + 1:
            run.append(i)
            continue
        if run:
            out.append(run[0] if len(run) == 1 else f"{run[0]}..{run[-1].split('-')[1]}")
        run = [i] if i and i.split("-")[-1].isdigit() else []
        if i and not run:
            out.append(i)
    return ", ".join(out)


def counts(results):
    return {s: sum(r.get("status") == s for r in results) for s in STATUS}


def markdown(stages, findings, cov, unlisted, notes, version, when):
    allr = [r for d in stages.values() for r in d.get("results", [])]
    c = counts(allr)
    out = [f"# Smoker regression report — {version}", "", f"Run {when}.", ""]
    if notes.get("summary"):
        out += [notes["summary"], ""]
    out += ["| Stage | Pass | Fail | Manual | Skip |", "|---|---|---|---|---|"]
    for s, d in stages.items():
        k = counts(d.get("results", []))
        out.append(f"| {s} | {k['pass']} | {k['fail']} | {k['manual']} | {k['skip']} |")
    out.append(f"| **all** | **{c['pass']}** | **{c['fail']}** | **{c['manual']}** | **{c['skip']}** |")
    out += ["", "## Failures", ""]
    for s, d in stages.items():
        for r in d.get("results", []):
            if r.get("status") == "fail":
                out.append(f"- **{r['id']}** ({s}) {r.get('feature', '')}: {r.get('check', '')}. {r.get('detail', '')}")
    out += ["", "## Findings", ""]
    for f in findings:
        loc = f"{f.get('file', '')}:{f.get('line', '')}".strip(":")
        out += [f"### {f.get('id')} [{f.get('severity')}] {f.get('title')}", "", f"`{loc}` ({f.get('area')})", "",
                f.get("description", ""), "", f"*Scenario:* {f.get('scenario', '')}", "",
                f"*Recommendation:* {f.get('recommendation', '')}", ""]
    if notes.get("observations"):
        out += ["## Observations", ""] + [f"- {o}" for o in notes["observations"]] + [""]
    claims = notes.get("_claims") or []
    if claims:
        out += ["## Security claims (README and docs)", "", "| Claim | Holds | Note |", "|---|---|---|"]
        out += [f"| {c.get('claim', '')} | {'yes' if c.get('held') else '**no**'} | {c.get('note', '')} |" for c in claims]
        out.append("")
    out += ["## Coverage", "", "| Feature | Area | Since | State | Checks |", "|---|---|---|---|---|"]
    for row in cov:
        out.append(f"| {row['feature']} | {row['area']} | {row.get('since', '')} | {row['state']} | "
                   f"{ranges(row.get('checks'))} |")
    if unlisted:
        out += ["", "Checks with results but no catalogue entry: " + ", ".join(unlisted)]
    out += ["", "## Manual checks", ""]
    for s, d in stages.items():
        for r in d.get("results", []):
            if r.get("status") == "manual":
                out.append(f"- **{r['id']}** {r.get('feature', '')}: {r.get('check', '')} {r.get('detail', '')}")
    out += ["", "## Skipped", ""]
    for s, d in stages.items():
        for r in d.get("results", []):
            if r.get("status") == "skip":
                out.append(f"- **{r['id']}** {r.get('check', '')}: {r.get('detail', '')}")
    return "\n".join(out) + "\n"


CSS = """
/* Layout: a single reading column; summary first (verdict, attention, findings), detail below in folds. */
:root{
  --bg:#f5f6f9;--surface:#ffffff;--sunk:#eef0f5;--line:#dde1ea;--ink:#16192a;--ink2:#3a3f55;--muted:#5d6479;
  --accent:#6d3fd6;--pass:#18794e;--pass-bg:#e3f4ea;--fail:#c0262d;--fail-bg:#fde8e8;--warn:#a35a00;--warn-bg:#fdf0dc;
  --skip:#5d6479;--skip-bg:#eceef3;--man:#2457b5;--man-bg:#e5edfb;
  --display:"Bricolage Grotesque","Segoe UI",system-ui,sans-serif;--body:"Instrument Sans","Segoe UI",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#11131c;--surface:#181b27;--sunk:#1f2331;--line:#2c3142;--ink:#e8eaf3;--ink2:#c3c7d6;--muted:#9aa1b5;
  --accent:#a98bff;--pass:#5fd19a;--pass-bg:#16301f;--fail:#ff7b7f;--fail-bg:#3a1719;--warn:#f0b35c;--warn-bg:#33240f;
  --skip:#9aa1b5;--skip-bg:#252a38;--man:#8db4ff;--man-bg:#1a2640;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#11131c;--surface:#181b27;--sunk:#1f2331;--line:#2c3142;--ink:#e8eaf3;--ink2:#c3c7d6;--muted:#9aa1b5;
  --accent:#a98bff;--pass:#5fd19a;--pass-bg:#16301f;--fail:#ff7b7f;--fail-bg:#3a1719;--warn:#f0b35c;--warn-bg:#33240f;
  --skip:#9aa1b5;--skip-bg:#252a38;--man:#8db4ff;--man-bg:#1a2640;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--body);margin:0}
.wrap{max-width:1040px;margin:0 auto;padding-block:28px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:28px}
h1,h2,h3{font-family:var(--display);text-wrap:balance;margin:0;line-height:1.2}
h1{font-size:30px}h2{font-size:21px}h3{font-size:16px}
.eyebrow{font:600 12px var(--body);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.meta{color:var(--muted);font-size:13.5px}
.lede{max-width:68ch;color:var(--ink2)}
section{display:flex;flex-direction:column;gap:12px;min-width:0}
.tally{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font:600 26px/1.1 var(--mono);font-variant-numeric:tabular-nums}
.tile span{font-size:12.5px;color:var(--muted)}
.tile.fail b{color:var(--fail)}.tile.pass b{color:var(--pass)}.tile.manual b{color:var(--man)}.tile.skip b{color:var(--skip)}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--sunk)}
.bar i{display:block}.bar .pass{background:var(--pass)}.bar .fail{background:var(--fail)}.bar .manual{background:var(--man)}.bar .skip{background:var(--skip)}
.stages{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.stage{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.stage .n{font:500 12.5px var(--mono);color:var(--ink2);font-variant-numeric:tabular-nums}
.pill{display:inline-block;font:600 11px var(--body);letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:999px;white-space:nowrap}
.pill.pass{color:var(--pass);background:var(--pass-bg)}.pill.fail,.pill.critical,.pill.high{color:var(--fail);background:var(--fail-bg)}
.pill.medium{color:var(--warn);background:var(--warn-bg)}.pill.low,.pill.info,.pill.skip,.pill.notrun,.pill.uncovered{color:var(--skip);background:var(--skip-bg)}
.pill.manual{color:var(--man);background:var(--man-bg)}
.finding{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:6px;min-width:0}
.finding.critical,.finding.high{border-left-color:var(--fail)}.finding.medium{border-left-color:var(--warn)}.finding.low,.finding.info{border-left-color:var(--skip)}
.finding .head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.finding .loc,code{font:12.5px var(--mono);color:var(--ink2);overflow-wrap:anywhere}
.finding p{margin:0;max-width:75ch}
.finding .k{font-weight:600;color:var(--ink2)}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
details>summary{cursor:pointer;font-weight:600;padding:4px 0}
details[open]>summary{margin-bottom:8px}
summary:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tbl{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:7px 8px;border-top:1px solid var(--line);vertical-align:top}
th{font:600 11px var(--body);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border-top:0}
td.id{font:12.5px var(--mono);white-space:nowrap;color:var(--ink2)}
td.d{color:var(--ink2);min-width:16ch}
ul.plain{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:6px;max-width:80ch}
.empty{color:var(--muted)}
@media (max-width:600px){h1{font-size:25px}.tile b{font-size:22px}}
"""


def pill(s):
    cls = s.replace(" ", "")
    return f'<span class="pill {e(cls)}">{e(s)}</span>'


def bar(k):
    tot = sum(k.values()) or 1
    return '<div class="bar" aria-hidden="true">' + "".join(
        f'<i class="{s}" style="width:{100 * k[s] / tot:.2f}%"></i>' for s in ("pass", "fail", "manual", "skip") if k[s]) + "</div>"


def result_table(rows, with_stage=False):
    if not rows:
        return '<p class="empty">None.</p>'
    head = "<tr><th>ID</th>" + ("<th>Stage</th>" if with_stage else "") + "<th>Feature</th><th>Check</th><th>Result</th><th>Detail</th></tr>"
    body = "".join(
        f"<tr><td class=\"id\">{e(r['id'])}</td>" + (f"<td>{e(r.get('_stage', ''))}</td>" if with_stage else "")
        + f"<td>{e(r.get('feature', ''))}</td><td>{e(r.get('check', ''))}</td><td>{pill(r.get('status', ''))}</td>"
        f"<td class=\"d\">{e(r.get('detail', '') or '')}</td></tr>" for r in rows)
    return f'<div class="tbl"><table>{head}{body}</table></div>'


def page(stages, findings, cov, unlisted, notes, version, when):
    allr = []
    for s, d in stages.items():
        for r in d.get("results", []):
            allr.append({**r, "_stage": s})
    c = counts(allr)
    sev = {s: sum(f.get("severity") == s for f in findings) for s in SEV}
    fails = [r for r in allr if r.get("status") == "fail"]
    manual = [r for r in allr if r.get("status") == "manual"]
    skipped = [r for r in allr if r.get("status") == "skip"]
    covc = {s: sum(r["state"] == s for r in cov) for s in ("pass", "fail", "manual", "skip", "not run", "uncovered")}
    h = [f"<title>Smoker Regression {e(version)}</title>",
         '<meta name="claude:viewport-fit-sides" content="cover">',
         '<link rel="preconnect" href="https://fonts.googleapis.com">',
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700'
         '&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">',
         f"<style>{CSS}</style>", '<main class="wrap">']
    h.append(f'<header style="display:flex;flex-direction:column;gap:6px"><span class="eyebrow">Full regression · controller, simulated grill, '
             f'both dashboards, integration, package, release, live</span><h1>Smoker {e(version)}</h1><span class="meta">Run {e(when)}</span>'
             + (f'<p class="lede">{e(notes["summary"])}</p>' if notes.get("summary") else "") + "</header>")
    h.append('<section aria-label="Totals"><div class="tally">'
             + "".join(f'<div class="tile {s}"><b>{c[s]}</b><span>{lab}</span></div>' for s, lab in
                       (("pass", "checks passed"), ("fail", "checks failed"), ("manual", "need a person"), ("skip", "skipped")))
             + f'<div class="tile {"fail" if sev["critical"] + sev["high"] else ""}"><b>{len(findings)}</b>'
               f'<span>review findings ({sev["critical"] + sev["high"]} high or critical)</span></div>'
             + f'<div class="tile {"fail" if covc["fail"] else "pass"}"><b>{covc["pass"]}/{len(cov)}</b><span>features fully passing</span></div>'
             + "</div>" + bar(c) + "</section>")
    h.append('<section><h2>By stage</h2><div class="stages">' + "".join(
        f'<div class="stage"><h3>{e(s)}</h3>{bar(counts(d.get("results", [])))}<span class="n">'
        + " · ".join(f"{v} {k}" for k, v in counts(d.get("results", [])).items() if v) + "</span></div>"
        for s, d in stages.items()) + "</div></section>")
    h.append(f"<section><h2>Failed checks</h2>{result_table(fails, True)}</section>")
    if findings:
        cards = []
        for f in findings:
            loc = f"{f.get('file', '')}{':' + str(f['line']) if f.get('line') else ''}"
            cards.append(
                f'<article class="finding {e(f.get("severity", "info"))}"><div class="head">{pill(f.get("severity", "info"))}'
                f'<span class="loc">{e(f.get("id", ""))}</span><h3>{e(f.get("title", ""))}</h3></div>'
                f'<span class="loc">{e(loc)} · {e(f.get("area", ""))}{"" if f.get("verified", True) else " · unverified"}</span>'
                f'<p>{e(f.get("description", ""))}</p>'
                + (f'<p><span class="k">Scenario.</span> {e(f["scenario"])}</p>' if f.get("scenario") else "")
                + (f'<p><span class="k">Fix.</span> {e(f["recommendation"])}</p>' if f.get("recommendation") else "")
                + "</article>")
        h.append('<section><h2>Bug and security review</h2><p class="meta">'
                 + " · ".join(f"{v} {k}" for k, v in sev.items() if v) + "</p>" + "".join(cards) + "</section>")
    if notes.get("observations"):
        h.append('<section><h2>Observations</h2><ul class="plain">'
                 + "".join(f"<li>{e(o)}</li>" for o in notes["observations"]) + "</ul></section>")
    claims = notes.get("_claims") or []
    if claims:
        bad = [c for c in claims if not c.get("held")]
        rows = "".join(f"<tr><td>{e(c.get('claim', ''))}</td><td>{pill('pass' if c.get('held') else 'fail')}</td>"
                       f"<td class=\"d\">{e(c.get('note', ''))}</td></tr>" for c in sorted(claims, key=lambda c: bool(c.get('held'))))
        h.append(f'<section><h2>Security claims</h2><p class="meta">Each security claim in the README and docs checked against the code: '
                 f'{len(claims) - len(bad)} hold, {len(bad)} don\'t.</p><details><summary>All {len(claims)} claims</summary>'
                 f'<div class="tbl"><table><tr><th>Claim</th><th>Holds</th><th>Note</th></tr>{rows}</table></div></details></section>')
    covrows = "".join(
        f"<tr><td>{e(r['feature'])}</td><td>{e(r['area'])}</td><td class=\"id\">{e(str(r.get('since', '')))}</td>"
        f"<td>{pill(r['state'])}</td><td class=\"id\">{e(ranges(r.get('checks')))}"
        + (f"<br>no result: {e(', '.join(r['missing']))}" if r["missing"] else "") + "</td></tr>" for r in cov)
    h.append(f'<section><h2>Feature coverage</h2><p class="meta">'
             + " · ".join(f"{v} {k}" for k, v in covc.items() if v)
             + f'</p><details><summary>All {len(cov)} features</summary><div class="tbl"><table><tr><th>Feature</th><th>Area</th>'
               f'<th>Since</th><th>State</th><th>Checks</th></tr>{covrows}</table></div>'
             + (f'<p class="meta">Checks with results but no catalogue entry: {e(", ".join(unlisted))}</p>' if unlisted else "")
             + "</details></section>")
    h.append(f'<section><h2>Manual checks</h2><p class="meta">Need a person and the real hardware; not run automatically.</p>'
             f'<details><summary>{len(manual)} checks</summary>{result_table(manual, True)}</details></section>')
    h.append(f'<section><h2>Skipped</h2><details><summary>{len(skipped)} checks</summary>{result_table(skipped, True)}</details></section>')
    h.append('<section><h2>Every result</h2>' + "".join(
        f'<details><summary>{e(s)} · {len(d.get("results", []))}</summary>{result_table(d.get("results", []))}</details>'
        for s, d in stages.items()) + "</section>")
    h.append("</main>")
    return "\n".join(h) + "\n"


def main():
    stages, findings, catalogue, notes = load()
    cov, unlisted = coverage(stages, catalogue)
    version = (ROOT / "VERSION").read_text().strip()
    tz = os.environ.get("REPORT_TZ")  # e.g. America/New_York; default: this machine's zone
    now = dt.datetime.now(ZoneInfo(tz)) if tz else dt.datetime.now().astimezone()
    when = now.strftime("%Y-%m-%d %H:%M %Z")
    (OUT / "report.md").write_text(markdown(stages, findings, cov, unlisted, notes, version, when))
    (OUT / "report.html").write_text(page(stages, findings, cov, unlisted, notes, version, when))
    c = counts([r for d in stages.values() for r in d.get("results", [])])
    print(f"report: {c}, {len(findings)} findings, {len(cov)} features -> {OUT / 'report.html'}")


if __name__ == "__main__":
    main()
