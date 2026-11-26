#!/usr/bin/env python3
"""The walkthrough's automated crawl: both dashboards, desktop and phone, Basic and Advanced (+ the Setup page).

For each page x width x mode it records the section bar (the navigation), every section reachable from it (heading,
buttons, fields, a screenshot) and a full-page screenshot, and runs the UX checks below. Results go to
out/walkthrough/inventory.json (for the reviewers) and to the regression runner's `walkthrough` stage (WT- IDs).

Pages:
  device  the controller's own page, served by tests/webui_bridge.py over a copy of the test build with its own ports
          (so it can run next to the regression's simulated grill and device test)
  ha      the Home Assistant dashboard (page.html) with tests/render_page.py's mock states

Checks (stable keys "<page> <width> <mode> › <check>"):
  menu label matches heading (per section-bar label), no duplicate menu labels, no horizontal scroll, nothing runs off
  screen, nothing wider than its container, tap targets at least 40x40 px (phone), no dead links, no console errors.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out" / "walkthrough"
WIDTHS = {"desktop": {"width": 1280, "height": 900}, "phone": {"width": 390, "height": 844}}
MODES = ["basic", "advanced"]
# The device page's own copy of the test build (tests/host-bridge.yaml substitutions) and its ports.
DEVICE_BUILD = ("smoker-host-test-w", 6553, 13833)
DEVICE_HTTP = 18580
CHROMIUM = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")

# Everything the crawl reads from a page, in the page (one call per view).
INSPECT = r"""(phone) => {
  const vw = document.documentElement.clientWidth, vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && e.offsetParent !== null; };
  const txt = e => (e.getAttribute('aria-label') || e.innerText || e.value || e.title || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const path = e => { const p = []; for (let x = e; x && x.nodeType === 1 && p.length < 4; x = x.parentElement)
      p.unshift(x.tagName.toLowerCase() + (x.id ? '#' + x.id : x.classList.length ? '.' + [...x.classList].slice(0, 2).join('.') : ''));
    return p.join(' > '); };
  const scroller = e => { for (let x = e.parentElement; x; x = x.parentElement) { const o = getComputedStyle(x).overflowX;
    if ((o === 'auto' || o === 'scroll' || o === 'hidden') && x !== document.documentElement && x !== document.body) return true; } return false; };
  const bar = document.getElementById('secbar');
  const nav = bar ? [...bar.querySelectorAll('a')].filter(vis).map(a => ({ label: txt(a), href: a.getAttribute('href') || '' })) : [];
  const navHeads = nav.map(n => { const t = n.href.startsWith('#') ? document.getElementById(n.href.slice(1)) : null;
    const h = t && (t.querySelector('h2') || t.querySelector('h3')); return { label: n.label, href: n.href, found: !!t,
      heading: h ? h.innerText.replace(/\s+/g, ' ').trim() : '' }; });
  const screens = [...document.querySelectorAll('[data-sect]')].filter(vis).map(s => {
    const h = s.querySelector('h2'); return { id: s.id, sect: s.dataset.sect, folded: s.classList.contains('folded'),
      heading: h ? h.innerText.replace(/\s+/g, ' ').trim() : '',
      buttons: [...new Set([...s.querySelectorAll('button,[role=button],a.btn,label.btn')].filter(vis).map(txt).filter(Boolean))].slice(0, 40),
      fields: [...s.querySelectorAll('input:not([type=hidden]):not([type=file]),select,textarea')].filter(vis).map(f =>
        f.getAttribute('aria-label') || (f.labels && f.labels[0] && f.labels[0].innerText.trim()) || f.placeholder || f.name || f.id || f.type).slice(0, 40) }; });
  const all = [...document.querySelectorAll('body *')].filter(vis);
  const off = all.filter(e => { const r = e.getBoundingClientRect(); return (r.right > vw + 1 || r.left < -1) && !scroller(e); }).map(path);
  const wide = all.filter(e => { const p = e.parentElement; if (!p || !vis(p) || scroller(e)) return false;
    const o = getComputedStyle(p).overflowX; return o === 'visible' && e.getBoundingClientRect().width > p.getBoundingClientRect().width + 1
      && getComputedStyle(e).position !== 'absolute' && getComputedStyle(e).position !== 'fixed'
      && parseFloat(getComputedStyle(e).marginLeft) >= 0 && parseFloat(getComputedStyle(e).marginRight) >= 0; }).map(path);  // (negative margins: a deliberate full-width bar)
  // A control whose tap is also taken by something larger counts at that size: a switch in a settings row (the whole
  // row toggles it), a section's fold button (the whole heading folds it); a link inside running text is exempt (as
  // in WCAG's target-size rule).
  const covered = e => (e.matches('button.tg') && e.closest('.row')) || (e.matches('button.fold') && e.closest('h2.sec'))
    || (e.tagName === 'A' && getComputedStyle(e).display === 'inline' && e.parentElement && e.parentElement.matches('p,small,li,span.small,span.muted'));
  const small = phone ? all.filter(e => e.matches('a[href],button,select,input:not([type=hidden]):not([type=file]),textarea,[role=button],label.btn') && !covered(e))
    .filter(e => { const r = e.getBoundingClientRect(); return r.width < 40 || r.height < 40; })
    .map(e => { const r = e.getBoundingClientRect(); return `${txt(e) || e.tagName.toLowerCase()} (${Math.round(r.width)}x${Math.round(r.height)})`; }) : [];
  const dead = [...document.querySelectorAll('a[href^="#"]')].map(a => a.getAttribute('href')).filter(h => h.length > 1 && !document.getElementById(h.slice(1)));
  return { title: document.title, vw, scrollW: document.documentElement.scrollWidth, nav, navHeads, screens,
    off: [...new Set(off)].slice(0, 20), offN: off.length, wide: [...new Set(wide)].slice(0, 20), wideN: wide.length,
    small: [...new Set(small)].slice(0, 30), smallN: small.length, dead: [...new Set(dead)] };
}"""
UNFOLD = """() => { document.querySelectorAll('[data-sect].folded h2 .fold').forEach(b => b.click()); }"""


def norm(s):
    return " ".join((s or "").lower().split())


def checks_for(page, width, mode, d, errors):
    """(key, check, ok, detail) for one view."""
    p = f"{page} {width} {mode}"
    out = []
    labels = [n["label"] for n in d["nav"]]
    for n in d["navHeads"]:
        ok = n["found"] and norm(n["label"]) and norm(n["label"]) in norm(n["heading"])
        out.append((f"{p} › menu label matches heading: {n['label']}", f"{p}: menu label '{n['label']}' matches its section's heading",
                    bool(ok), "" if ok else f"label {n['label']!r} -> {n['href']} heading {n['heading']!r}" + ("" if n["found"] else " (no such section)")))
    dup = sorted({x for x in labels if labels.count(x) > 1})
    out.append((f"{p} › no duplicate menu labels", f"{p}: no duplicate menu labels", not dup, ", ".join(dup)))
    out.append((f"{p} › no horizontal scroll", f"{p}: no horizontal scroll", d["scrollW"] <= d["vw"] + 1,
                f"page is {d['scrollW']} px wide on a {d['vw']} px screen"))
    out.append((f"{p} › nothing runs off screen", f"{p}: nothing runs off screen", d["offN"] == 0,
                f"{d['offN']} element(s): " + "; ".join(d["off"][:8])))
    out.append((f"{p} › nothing wider than its container", f"{p}: nothing wider than its container", d["wideN"] == 0,
                f"{d['wideN']} element(s): " + "; ".join(d["wide"][:8])))
    if width == "phone":
        out.append((f"{p} › tap targets at least 40x40 px", f"{p}: tap targets at least 40x40 px", d["smallN"] == 0,
                    f"{d['smallN']} control(s) smaller: " + "; ".join(d["small"][:15])))
    out.append((f"{p} › no dead links", f"{p}: no dead links", not d["dead"], ", ".join(d["dead"])))
    out.append((f"{p} › no console errors", f"{p}: no console errors", not errors, "; ".join(errors[:5])[:400]))
    return out


def crawl_view(pg, fr, page, width, mode, shots, errors):
    """One page x width x mode: the main view, then the Setup page."""
    phone = width == "phone"
    fr.evaluate(UNFOLD)
    time.sleep(0.6)
    d = fr.evaluate(INSPECT, phone)
    tag = f"{page}-{width}-{mode}"
    pg.screenshot(path=str(shots / f"{tag}.png"), full_page=True)
    for s in d["screens"]:
        s["screenshot"] = f"shots/{tag}-{s['sect']}.png"
        try:
            fr.locator(f"#{s['id']}").screenshot(path=str(shots / f"{tag}-{s['sect']}.png"))
        except Exception:  # noqa: BLE001  (a section that can't be shot is still listed)
            s["screenshot"] = ""
    view = {"page": page, "width": width, "mode": mode, "screenshot": f"shots/{tag}.png", **d}
    results = checks_for(page, width, mode, d, list(errors))
    # The Setup page (the section bar's Setup opens it on its own).
    setup = fr.locator("#secbar a").filter(has_text="Setup")
    if setup.count():
        errors.clear()
        setup.first.click()
        time.sleep(0.8)
        fr.evaluate(UNFOLD)
        ds = fr.evaluate(INSPECT, phone)
        pg.screenshot(path=str(shots / f"{tag}-setup-page.png"), full_page=True)
        view["setup_page"] = {"screenshot": f"shots/{tag}-setup-page.png", "screens": ds["screens"]}
        results += [(k.replace(f"{page} {width} {mode} ›", f"{page} {width} {mode} setup ›"), c.replace(f"{mode}:", f"{mode} setup page:"), ok, det)
                    for k, c, ok, det in checks_for(page, width, mode, ds, list(errors)) if "menu label" not in k]
        setup.first.click()
        time.sleep(0.4)
    return view, results


def open_ha(b, width, mode, harness):
    vp = WIDTHS[width]
    ctx = b.new_context(viewport=vp, device_scale_factor=1, is_mobile=width == "phone", has_touch=width == "phone")
    ctx.add_init_script(f"try {{ localStorage.setItem('smoker-mode', '{mode}'); }} catch (e) {{}}")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto("file://" + str(harness))
    time.sleep(2.5)
    fr = next(f for f in pg.frames if f.url.startswith("about:srcdoc"))
    return ctx, pg, fr, errors


def open_device(b, width, mode):
    vp = WIDTHS[width]
    ctx = b.new_context(viewport=vp, device_scale_factor=1, is_mobile=width == "phone", has_touch=width == "phone")
    ctx.add_init_script(f"try {{ localStorage.setItem('smoker-mode', '{mode}'); }} catch (e) {{}}")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(f"http://127.0.0.1:{DEVICE_HTTP}/")
    time.sleep(3)
    return ctx, pg, pg.main_frame, errors


def ha_harness(out):
    """tests/render_page.py's harness page (mock Home Assistant states) for page.html."""
    sys.path.insert(0, str(ROOT / "tests"))
    argv, sys.argv = sys.argv, [sys.argv[0], str(out)]
    try:
        import render_page as rp
    finally:
        sys.argv = argv
    import base64
    html = rp.HARNESS.replace("%STATES%", json.dumps(rp.STATES)).replace("%PHOTO%", base64.b64encode(rp.tiny_png()).decode()) \
        .replace("%PAGE%", json.dumps(rp.build_page()).replace("</", "<\\/"))
    # (A phone lays a page out at 980 px without this: the harness is the top page, the dashboard its frame.)
    html = html.replace("<html>", '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>', 1)
    p = out / "ha-harness.html"
    p.write_text(html)
    return p


def start_device(esphome_python):
    """The fake grill, the walkthrough's copy of the test build and the page bridge, on the walkthrough's own ports."""
    name, api, grill = DEVICE_BUILD
    prog = ROOT / f"tests/.esphome/build/{name}/.pioenvs/{name}/program"
    if not prog.exists():
        return None, f"the walkthrough's test build isn't compiled ({prog.relative_to(ROOT)})"
    py = esphome_python or sys.executable
    logs = OUT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    procs = [subprocess.Popen([py, "-u", str(ROOT / "tools/fake_grill.py"), "--port", str(grill), "--bind", "127.0.0.1", "--speed", "120"],
                              stdout=open(logs / "grill.log", "w"), stderr=subprocess.STDOUT)]
    time.sleep(1)
    procs.append(subprocess.Popen([str(prog)], stdout=open(logs / "device.log", "w"), stderr=subprocess.STDOUT,
                                  env=dict(os.environ, ESPHOME_PREFDIR=tempfile.mkdtemp(prefix="smoker-walk-prefs-"))))
    procs.append(subprocess.Popen([py, "-u", str(ROOT / "tests/webui_bridge.py"), "--http", str(DEVICE_HTTP), "--api", f"127.0.0.1:{api}"],
                                  stdout=open(logs / "bridge.log", "w"), stderr=subprocess.STDOUT))
    import urllib.request
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{DEVICE_HTTP}/sensor/Pit temperature".replace(" ", "%20"), timeout=2) as r:
                v = json.loads(r.read()).get("value")
                if v not in (None, "NaN"):
                    return procs, ""
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return procs, "the controller's page didn't come up (out/walkthrough/logs)"


def crawl(esphome_python=None, pages=("device", "ha")):
    """Run the crawl; returns (inventory, results, problems)."""
    from playwright.sync_api import sync_playwright
    shots = OUT / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    inventory, results, problems = {"widths": WIDTHS, "modes": MODES, "views": []}, [], []
    procs = []
    try:
        if "device" in pages:
            procs, why = start_device(esphome_python)
            if why:
                problems.append(f"device page: {why}")
                pages = [p for p in pages if p != "device"]
        harness = ha_harness(OUT) if "ha" in pages else None
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=CHROMIUM) if os.path.exists(CHROMIUM) else p.chromium.launch()
            for page in pages:
                for width in WIDTHS:
                    for mode in MODES:
                        ctx, pg, fr, errors = open_ha(b, width, mode, harness) if page == "ha" else open_device(b, width, mode)
                        try:
                            view, res = crawl_view(pg, fr, page, width, mode, shots, errors)
                            inventory["views"].append(view)
                            results += res
                        except Exception as ex:  # noqa: BLE001
                            problems.append(f"{page} {width} {mode}: {type(ex).__name__}: {ex}")
                        ctx.close()
            b.close()
    finally:
        for q in procs or []:
            q.terminate()
    (OUT / "inventory.json").write_text(json.dumps(inventory, indent=1))
    return inventory, results, problems


if __name__ == "__main__":
    inv, res, probs = crawl(os.environ.get("ESPHOME_PYTHON"))
    for k, c, ok, det in res:
        print(("  ok   " if ok else "  FAIL ") + c + ("" if ok else f"  ({det[:160]})"))
    for pr in probs:
        print("  PROBLEM " + pr)
    print(f"{len(inv['views'])} views, {sum(not r[2] for r in res)} failing checks")
