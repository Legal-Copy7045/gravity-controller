#!/usr/bin/env python3
"""Device page test: firmware/device-ui in Chromium, against the host build and the simulated grill.

    tools/fake_grill.py  <-TCP->  host firmware (tests/host-bridge.yaml)  <-native API->  tests/webui_bridge.py
    (ESPHome web_server's /events + REST, which the host platform lacks)  <-HTTP->  the page in Chromium

Checks at 1440 and 390 px: no console errors, the pit temperature and a food card render, pressing pit + changes
the target the grill reports, a probe-source select reaches the device, no horizontal overflow; ?classic loads
ESPHome's stock page. Every request off 127.0.0.1 is blocked (the page must work offline).

    esphome compile tests/host-bridge.yaml
    python3 tests/webui_e2e.py [screenshot dir]

ESPHOME_PYTHON: the interpreter for the bridge (needs aioesphomeapi + aiohttp; default: this one).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROGRAM = os.path.join(HERE, ".esphome/build/smoker-host-test/.pioenvs/smoker-host-test/program")
HTTP = 18080
BASE = f"http://127.0.0.1:{HTTP}"
failures = []
EDITOR_SHOTS = os.environ.get("EDITOR_SHOTS")  # where the editor screenshot goes (default: the screenshot dir)
PAGE = None  # while a page is open, waits pump Playwright (its routes serve the page's requests)


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def get(path):
    with urllib.request.urlopen(BASE + urllib.parse.quote(path), timeout=5) as r:
        return json.loads(r.read())


def post(path, **params):
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(BASE + urllib.parse.quote(path) + q, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def tiny_png(w=40, h=29):
    import struct, zlib
    raw = b"".join(b"\x00" + b"\x88\x88\x88" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def value(domain, name):
    try:
        v = get(f"/{domain}/{name}")["value"]
        return float(v) if v not in (None, "NaN") else None
    except Exception:
        return None


def wait(pred, timeout, what):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        PAGE.wait_for_timeout(250) if PAGE else time.sleep(0.25)
    print(f"  (timed out waiting for {what})")
    return False


def main():
    shots = sys.argv[1] if len(sys.argv) > 1 else None
    if shots:
        os.makedirs(shots, exist_ok=True)
    logs = {n: open(os.path.join(HERE, f"webui-{n}.log"), "w") for n in ("grill", "device", "bridge")}
    procs = [subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "tools/fake_grill.py"), "--port", "13333",
                               "--bind", "127.0.0.1", "--speed", "120"], stdout=logs["grill"], stderr=subprocess.STDOUT)]
    time.sleep(1)
    env = dict(os.environ, ESPHOME_PREFDIR=tempfile.mkdtemp(prefix="smoker-webui-prefs-"))
    procs.append(subprocess.Popen([PROGRAM], stdout=logs["device"], stderr=subprocess.STDOUT, env=env))
    py = os.environ.get("ESPHOME_PYTHON", sys.executable)
    procs.append(subprocess.Popen([py, "-u", os.path.join(HERE, "webui_bridge.py"), "--http", str(HTTP)],
                                  stdout=logs["bridge"], stderr=subprocess.STDOUT))
    try:
        if not wait(lambda: value("sensor", "Pit temperature") is not None, 40, "the bridge and a pit reading"):
            check(False, "bridge up with a pit temperature")
            return
        check(wait(lambda: value("sensor", "Food 1 temperature") is not None, 20, "food 1"), "food 1 has a reading")
        with sync_playwright() as p:
            exe = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")
            b = p.chromium.launch(executable_path=exe) if os.path.exists(exe) else p.chromium.launch()
            for width, height in ((1440, 1000), (390, 844)):
                run_page(b, width, height, shots)
            classic(b)
            b.close()
    finally:
        for pr in procs:
            pr.terminate()
        for pr in procs:
            try:
                pr.wait(5)
            except subprocess.TimeoutExpired:
                pr.kill()
    print("FAILED: " + "; ".join(failures) if failures else "all device page checks passed")
    sys.exit(1 if failures else 0)


def offline(ctx):
    # LAN only: block everything else (the optional web fonts fail and the system fonts take over).
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(BASE) else r.abort())


def run_page(browser, width, height, shots):
    print(f"-- {width}px")
    ctx = browser.new_context(viewport={"width": width, "height": height})
    offline(ctx)
    global PAGE
    pg = PAGE = ctx.new_page()
    # The page's state, for the program editor check (the host build has no "Program" text: see program_editor()).
    src = open(os.path.join(ROOT, "firmware/device-ui/ui.js"), encoding="utf-8").read()
    pg.route(BASE + "/0.js", lambda r: r.fulfill(status=200, content_type="text/javascript",
                                                  body=src + "\nwindow.__gxTest = { ents, render, progEd };\n"))
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and not (m.location or {}).get("url", "").startswith(
        "https://fonts.") and errors.append(m.text))
    pg.goto(BASE + "/")
    try:
        pg.wait_for_function("document.querySelector('#hero .big') && /\\d/.test(document.querySelector('#hero .big').textContent)", timeout=15000)
    except Exception:
        check(False, f"page drew the hero at {width}px (errors: {errors[:3]}, body: {pg.inner_html('body')[:300]!r})")
        ctx.close()
        return
    # the simulation runs at 120x: the hero must catch up with the device's reading within a few seconds
    shown = lambda: float(pg.inner_text("#hero .big").replace("\n", "").split("°")[0])
    ok = wait(lambda: abs(shown() - value("sensor", "Pit temperature")) <= 1, 6, "the hero to follow the pit")
    check(ok, f"hero shows the pit temperature ({shown():.0f}; device {value('sensor', 'Pit temperature'):.0f})")
    check(pg.locator("#grillpic svg").count() == 1, "grill drawing rendered")
    top = pg.inner_text("#topbar")
    check("Grill connected" in top, f"status strip first on the page says connected ({top[:80]!r})")
    check(pg.evaluate("document.querySelector('.wrap').firstElementChild.id") == "topbar", "status strip is the first thing on the page")
    pg.wait_for_selector("#food .food[data-slot='1'] .ptemp", timeout=10000)
    check(pg.locator("#food .food").count() >= 1, "a food card renders")
    # pit +: the grill must report the new target
    before = value("sensor", "Pit target reported")
    check(before is not None, f"grill reports a pit target ({before})")
    pg.locator("#pit [data-a=pit][data-d='1']").click()
    ok = wait(lambda: (value("sensor", "Pit target reported") or 0) > (before or 0), 15, "the grill's reported target")
    check(ok, f"pit + changed the grill's target ({before} -> {value('sensor', 'Pit target reported')})")
    pg.wait_for_function(f"document.querySelector('#pitval').textContent.startsWith('{value('number', 'Pit target'):.0f}')", timeout=10000)
    check(True, "page shows the new target")
    # a select through REST: Food 1 reads the spare probe (135.5 °F), then back
    src = pg.locator("#sources select[data-n='Food 1 probe']")
    first = src.input_value()
    src.select_option("Spare")
    check(wait(lambda: get("/select/Food 1 probe")["value"] == "Spare", 10, "the select"), "probe source select reached the device")
    check(wait(lambda: abs((value("sensor", "Food 1 temperature") or 0) - 135.5) < 0.6, 15, "food 1 on the spare probe"),
          f"food 1 now reads the spare probe ({value('sensor', 'Food 1 temperature')})")
    pg.locator("body").click(position={"x": 1, "y": 1})
    pg.locator("#sources select[data-n='Food 1 probe']").select_option(first)
    wait(lambda: abs((value("sensor", "Food 1 temperature") or 0) - 135.5) > 0.6, 15, "food 1 back on its probe")
    pg.locator("body").click(position={"x": 1, "y": 1})
    pg.wait_for_timeout(3000)  # let the toast go
    # Your grill photo: with "Grill photo URL" set, the readings are pinned on the photo; cleared, the drawing returns.
    png = tiny_png()
    pg.context.route("http://photo.test/**", lambda r: r.fulfill(status=200, content_type="image/png", body=png))
    post("/text/Grill photo URL/set", value="http://photo.test/grill.png")
    try:
        pg.wait_for_selector("#grillpic .gphoto img", timeout=10000)
        pins = pg.locator("#grillpic .gphoto .pin").count()
        txt = pg.inner_text("#grillpic")
        check(pins >= 5 and "°" in txt, f"photo mode pins the readings on the photo ({pins} pins)")
    except Exception as e:
        check(False, f"photo mode didn't show ({e})")
    post("/text/Grill photo URL/set", value="")
    try:
        pg.wait_for_selector("#grillpic svg", timeout=10000)
        check(True, "photo cleared: the drawing is back")
    except Exception:
        check(False, "drawing didn't come back after clearing the photo")
    program_editor(pg, width, shots)
    over = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    check(over <= 0, f"no horizontal overflow at {width}px ({over}px)")
    check(not errors, f"no console errors at {width}px {errors[:3]}")
    if shots:
        pg.evaluate("window.scrollTo(0,0)")
        pg.screenshot(path=os.path.join(shots, f"device-{width}-light.png"), full_page=True)
        pg.emulate_media(color_scheme="dark")
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(shots, f"device-{width}-dark.png"), full_page=True)
    ctx.close()
    PAGE = None


LOAD_PROGRAM = """
import asyncio, sys
from aioesphomeapi import APIClient
async def main():
    c = APIClient("127.0.0.1", 6053, None)
    await c.connect(login=True)
    _, services = await c.list_entities_services()
    await c.execute_service({s.name: s for s in services}["load_program"], {"program": sys.argv[1]})
    await asyncio.sleep(0.5)
    await c.disconnect()
asyncio.run(main())
"""


def program_editor(pg, width, shots):
    """Build a 2-step program in the step editor, load it, and the controller takes it.

    core.yaml loads programs through its "Program" text (POST /text/Program/set). The host build
    (tests/host-bridge.yaml) has no such text, so the page gets a stand-in entity, the request is caught here and
    the text goes to the device's load_program action; the device's own Program status/error are then checked.
    """
    real = True
    try:
        get("/text/Program")
    except Exception:
        real = False
    sent = []
    if not real:
        pg.evaluate("""() => { __gxTest.ents['text/Program'] = { domain: 'text', name: 'Program', value: '', state: '', max_length: 255 };
            __gxTest.render(); }""")

        def catch(r):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(r.request.url).query)
            sent.append(q.get("value", [""])[0])
            r.fulfill(status=200, body="")
        pg.route(BASE + "/text/Program/set*", catch)
    pg.wait_for_selector("#progedit #pe-addstep", timeout=10000)
    while pg.locator("#progedit .pe-step").count():  # start from an empty program
        pg.locator("#progedit [data-pe-act=del-step]").first.click()
    pg.fill("#pe-name", "Web cook")
    pg.click("#pe-addstep")
    pg.fill("#pe-s0-temp", "260")
    pg.fill("#pe-s0-c0-v", "110")
    pg.click("#pe-addstep")
    pg.select_option("#pe-s1-kind", "hold")
    pg.fill("#pe-s1-temp", "200")
    pg.fill("#pe-s1-note", "Done - rest it")
    pg.evaluate("document.activeElement.blur()")
    want = 'name: Web cook; pit 260 until food1 >= 110; hold 200 notify "Done - rest it"'
    got = pg.evaluate("__gxTest.progEd.text()")
    check(got == want, f"step editor builds the program ({got!r})")
    check(pg.locator("#progedit .pe-errs").count() == 0 and not pg.is_disabled("#pe-load"), "the program is valid and can be loaded")
    if shots and width < 600:
        pg.evaluate("document.querySelector('#progedit details.pe-prev').open = true")
        os.makedirs(EDITOR_SHOTS or shots, exist_ok=True)
        pg.evaluate("document.getElementById('secbar').style.position = 'static'")  # the sticky bar would cover the card
        pg.locator("#prog").screenshot(path=os.path.join(EDITOR_SHOTS or shots, "device-editor-phone-light.png"))
        pg.evaluate("document.getElementById('secbar').style.position = ''")
    pg.click("#pe-load")
    if real:
        ok = wait(lambda: get("/text/Program")["value"] == want, 10, "the Program text")
        check(ok, "Load set the Program text on the device")
    else:
        wait(lambda: sent, 5, "the Program text request")
        check(sent == [want], f"Load sends the program as the Program text ({sent})")
        if sent:
            subprocess.run([os.environ.get("ESPHOME_PYTHON", sys.executable), "-c", LOAD_PROGRAM, sent[0]], timeout=30, check=False)
            pg.evaluate("t => { const e = __gxTest.ents['text/Program']; e.value = e.state = t; __gxTest.render(); }", sent[0])
    status = lambda: get("/text_sensor/Program status").get("value") or ""
    err = lambda: get("/text_sensor/Program error").get("value")
    ok = wait(lambda: "Ready: Web cook (2 steps)" in status() and not err(), 10, "the device's program status")
    check(ok, f"the device took the program (status {status()!r}, error {err()!r})")
    ok = wait(lambda: "Ready: Web cook (2 steps)" in pg.inner_text("#progstat"), 10, "the page's program status")
    check(ok, f"the page shows the device's program status ({pg.inner_text('#progstat')[:80]!r})")
    check("controller's program" in pg.inner_text("#progedit .pe-load"), "the editor shows it as the controller's program")
    # The controller's own error is shown (a program it refuses).
    if not real:
        subprocess.run([os.environ.get("ESPHOME_PYTHON", sys.executable), "-c", LOAD_PROGRAM, "pit 250 until food9 >= 160"], timeout=30, check=False)
        ok = wait(lambda: "food9" in pg.inner_text("#progstat"), 10, "the device's program error on the page")
        check(ok, "the device's Program error shows in the program card")


def classic(browser):
    print("-- ?classic")
    ctx = browser.new_context()
    asked = []

    def route(r):
        if r.request.url.startswith("https://oi.esphome.io/"):
            asked.append(r.request.url)
            r.fulfill(body="document.body.setAttribute('data-stock','1')", content_type="text/javascript")
        elif r.request.url.startswith(BASE):
            r.continue_()
        else:
            r.abort()

    ctx.route("**/*", route)
    pg = ctx.new_page()
    pg.goto(BASE + "/?classic")
    pg.wait_for_function("document.body.dataset.stock === '1'", timeout=10000)
    check(asked == ["https://oi.esphome.io/v3/www.js"], "?classic loads ESPHome's stock page")
    check(pg.locator(".wrap").count() == 0 and pg.locator("esp-app").count() == 1, "?classic leaves the custom page out")
    ctx.close()


if __name__ == "__main__":
    main()
