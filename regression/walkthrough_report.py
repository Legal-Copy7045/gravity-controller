#!/usr/bin/env python3
"""Build the walkthrough report: the reviewers' findings, the automated UX checks and the crawl's inventory.

Usage: python3 regression/walkthrough_report.py   (or: python3 regression/run.py report --walkthrough)
Writes regression/out/walkthrough/report.html (and the same page as regression/out/walkthrough.html): a self-contained page (no <html>/<body> wrapper, screenshots embedded
as small JPEGs) to publish as a private artifact, republished to the same URL each run.

Inputs (regression/out/):
  walkthrough-checks.json        the walkthrough stage's checks (WT- IDs, regression/run.py --stage walkthrough)
  walkthrough/inventory.json     the crawl: views (page x width x mode), their navigation and sections
  findings/walkthrough-{desktop,phone}.json   the two reviewers in the standard's schema (mapped to the groups
                                 below), and/or
  walkthrough/findings.json      the two reviewers in this report's own schema: {"summary": "...", "findings": [{id: UX-001.., group, title, now,
                                 proposal, affects, effort S|M|L, risk, evidence: [screenshot paths], page, width}]}
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
WT = OUT / "walkthrough"
GROUPS = [("merge", "Merge"), ("rename", "Rename"), ("move", "Move"), ("remove", "Remove"), ("flow", "Flow"),
          ("mobile", "Mobile"), ("keep-separate", "Keep separate")]
e = html.escape


# The standard's reviewer groups (regression/standard.py schema walkthrough) -> this report's groups.
STD_GROUP = {"duplicate": "merge", "naming": "rename", "placement": "move", "dead-end": "flow", "long-flow": "flow",
             "keep-separate": "keep-separate", "layout": "mobile", "other": "flow"}


def from_standard(f, width):
    """A finding in the standard's walkthrough schema, in this report's fields."""
    return {"id": f.get("id", ""), "group": STD_GROUP.get(f.get("group"), f.get("group", "flow")), "title": f.get("title", ""),
            "now": f.get("detail", ""), "proposal": f.get("proposal", ""), "affects": ", ".join(f.get("roles", [])),
            "effort": f.get("effort", "?"), "risk": f.get("value", "?") and f"value {f.get('value')}",
            "evidence": [x.removeprefix("walkthrough/") for x in f.get("screenshots", [])],
            "page": ", ".join(f.get("pages", [])) or "both", "width": width}


def load(out=OUT):
    wt = out / "walkthrough"
    p = out / "walkthrough-checks.json"
    if not p.is_file():  # (before the standard: the checks were in out/walkthrough.json)
        p = out / "walkthrough.json"
    stage = json.loads(p.read_text()) if p.is_file() else {}
    if not isinstance(stage.get("results"), list):
        stage = {"results": []}
    inv = json.loads((wt / "inventory.json").read_text()) if (wt / "inventory.json").is_file() else {"views": []}
    fnd = json.loads((wt / "findings.json").read_text()) if (wt / "findings.json").is_file() else {}
    if isinstance(fnd, list):
        fnd = {"findings": fnd}
    # The standard's reviewer files (the global /walkthrough): out/findings/walkthrough-desktop.json and -phone.json.
    for width in ("desktop", "phone"):
        q = out / "findings" / f"walkthrough-{width}.json"
        if q.is_file():
            data = json.loads(q.read_text())
            fnd.setdefault("findings", [])
            fnd["findings"] += [from_standard(f, width) for f in data.get("findings", [])]
            if data.get("status") == "failed":
                fnd["summary"] = (fnd.get("summary", "") + f" The {width} reviewer failed: {data.get('scope', '')}").strip()
    return stage, inv, fnd


def thumb(path, width=360, base=WT):
    """A screenshot as a small embedded JPEG (or "" when it's missing or Pillow isn't there)."""
    p = base / path if path else None
    if not p or not p.is_file():
        return ""
    try:
        from PIL import Image
        im = Image.open(p).convert("RGB")
        if im.width > width:
            im = im.resize((width, max(1, round(im.height * width / im.width))))
        if im.height > 2400:
            im = im.crop((0, 0, im.width, 2400))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=62)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return ""


def grouped(findings):
    by = {k: [] for k, _ in GROUPS}
    for f in findings:
        by.setdefault(f.get("group", "flow"), []).append(f)
    return by


CSS = """<title>Smoker walkthrough</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* One reading column: summary tiles, findings grouped by kind, then the checks and the crawl. */
:root{--bg:#f6f4f1;--card:#fffdfa;--ink:#1f2226;--mute:#62666d;--line:#e3ddd5;--bad:#b4411a;--ok:#2f7d4a;--acc:#c8571f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15181c;--card:#1d2127;--ink:#e9e6e2;--mute:#9aa1a9;--line:#2d333a;--bad:#f08a5d;--ok:#6cc58a;--acc:#f0884f;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#15181c;--card:#1d2127;--ink:#e9e6e2;--mute:#9aa1a9;--line:#2d333a;--bad:#f08a5d;--ok:#6cc58a;--acc:#f0884f;color-scheme:dark}
body{background:var(--bg);color:var(--ink)}
.wt{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1100px;margin:0 auto;padding-block:20px;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.wt h1{font-size:24px;margin:0 0 4px;text-wrap:balance}.wt h2{font-size:19px;margin:28px 0 10px}.wt h3{font-size:16px;margin:0 0 6px}
.wt .mute{color:var(--mute)}.wt .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0;min-width:0}
.wt .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.wt .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.wt .kpi b{font-size:22px;display:block;font-variant-numeric:tabular-nums;color:var(--acc)}
.wt .tag{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 8px;font-size:12px;margin:0 4px 4px 0;color:var(--mute)}
.wt dl{display:grid;grid-template-columns:110px minmax(0,1fr);gap:4px 10px;margin:8px 0}.wt dt{color:var(--mute)}.wt dd{margin:0}
.wt img{max-width:100%;border:1px solid var(--line);border-radius:8px}.wt .shots{display:flex;gap:8px;flex-wrap:wrap}.wt .shots img{max-width:240px}
.wt table{border-collapse:collapse;width:100%;font-size:13px}.wt td,.wt th{border-top:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}
.wt .fail{color:var(--bad);font-weight:600}.wt .pass{color:var(--ok)}.wt details summary{cursor:pointer;font-weight:600}
.wt .scroll{overflow-x:auto}
@media (max-width:560px){.wt dl{grid-template-columns:1fr}.wt .shots img{max-width:100%}}
</style>"""


def page(stage, inv, fnd, when=None, base=WT):
    when = when or dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    res = stage.get("results", [])
    fails = [r for r in res if r["status"] == "fail"]
    findings = fnd.get("findings", [])
    by = grouped(findings)
    views = inv.get("views", [])
    h = [CSS, '<div class="wt">', '<h1>Smoker walkthrough</h1>',
         f'<p class="mute">Both dashboards (the controller\'s own page and Home Assistant\'s), desktop 1280 px and phone 390 px, '
         f'Basic and Advanced, and the Setup page. {e(when)}.</p>']
    if fnd.get("summary"):
        h.append(f'<div class="card">{e(fnd["summary"])}</div>')
    h.append('<div class="kpis">' + "".join(f'<div class="kpi"><b>{v}</b><span class="mute">{e(k)}</span></div>' for k, v in [
        ("views crawled", len(views)), ("UX checks", len(res)), ("checks failing", len(fails)), ("review findings", len(findings))]
        + [(t.lower(), len(by.get(g, []))) for g, t in GROUPS if by.get(g)]) + "</div>")
    h.append("<h2>Review findings</h2>")
    if not findings:
        h.append('<p class="mute">No reviewer findings in out/walkthrough/findings.json.</p>')
    for g, title in GROUPS:
        items = by.get(g, [])
        if not items:
            continue
        h.append(f"<h3 style='margin-top:18px'>{e(title)} ({len(items)})</h3>")
        for f in items:
            shots = "".join(f'<img alt="{e(s)}" src="{src}">' for s in (f.get("evidence") or [])[:3] if (src := thumb(s, 480, base)))
            h.append(f'<div class="card"><h3>{e(f.get("id", ""))} · {e(f.get("title", ""))}</h3>'
                     f'<span class="tag">{e(f.get("page", ""))}</span><span class="tag">{e(f.get("width", ""))}</span>'
                     f'<span class="tag">effort {e(str(f.get("effort", "?")))}</span><span class="tag">risk {e(str(f.get("risk", "?")))}</span>'
                     f'<dl><dt>Now</dt><dd>{e(f.get("now", ""))}</dd><dt>Proposal</dt><dd>{e(f.get("proposal", ""))}</dd>'
                     f'<dt>Affects</dt><dd>{e(f.get("affects", ""))}</dd></dl>{f"<div class=shots>{shots}</div>" if shots else ""}</div>')
    h.append("<h2>Automated UX checks</h2>")
    h.append('<div class="card scroll"><table><tr><th>ID</th><th>Check</th><th>Result</th><th>Detail</th></tr>' + "".join(
        f'<tr><td>{e(r["id"])}</td><td>{e(r["check"])}</td><td class="{r["status"]}">{e(r["status"])}</td><td>{e(r.get("detail", ""))}</td></tr>'
        for r in sorted(res, key=lambda r: (r["status"] != "fail", r["id"]))) + "</table></div>")
    h.append("<h2>What the crawl found</h2>")
    for v in views:
        nav = " · ".join(n["label"] for n in v.get("nav", []))
        rows = "".join(f'<tr><td>{e(s.get("heading") or s.get("sect", ""))}</td><td>{len(s.get("buttons", []))}</td><td>{len(s.get("fields", []))}</td>'
                       f'<td>{e(", ".join(s.get("buttons", [])[:12]))}</td></tr>' for s in v.get("screens", []))
        src = thumb(v.get("screenshot"), 300, base)
        h.append(f'<details class="card"><summary>{e(v["page"])} · {e(v["width"])} · {e(v["mode"])} — {len(v.get("screens", []))} sections</summary>'
                 f'<p class="mute">Section bar: {e(nav) or "none"}</p><div class="scroll"><table><tr><th>Section</th><th>Buttons</th><th>Fields</th>'
                 f'<th>Some of its buttons</th></tr>{rows}</table></div>{f"<p><img alt=page src={src}></p>" if src else ""}</details>')
    h.append("</div>")
    return "\n".join(h)


def main():
    stage, inv, fnd = load()
    WT.mkdir(parents=True, exist_ok=True)
    (WT / "report.html").write_text(page(stage, inv, fnd))
    shutil.copyfile(WT / "report.html", OUT / "walkthrough.html")  # (the standard's path: what /walkthrough publishes)
    n = len(fnd.get("findings", []))
    print(f"walkthrough report: {len(inv.get('views', []))} views, {sum(r['status'] == 'fail' for r in stage.get('results', []))} failing checks, "
          f"{n} findings -> {WT / 'report.html'} ({os.path.getsize(WT / 'report.html') // 1024} KB)")


if __name__ == "__main__":
    main()
