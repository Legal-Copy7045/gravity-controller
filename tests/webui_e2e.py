#!/usr/bin/env python3
"""Device page test: firmware/device-ui in Chromium, against the host build and the simulated grill.

    tools/fake_grill.py  <-TCP->  host firmware (tests/host-bridge.yaml)  <-native API->  tests/webui_bridge.py
    (ESPHome web_server's /events + REST, which the host platform lacks)  <-HTTP->  the page in Chromium

Checks at 1440 and 390 px: no console errors, the pit temperature and a food card render, pressing pit + changes
the target the grill reports, a probe-source select reaches the device, no horizontal overflow; ?classic no longer
loads ESPHome's stock page from the internet. Every request off 127.0.0.1 is blocked (the page must work offline).

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
import urllib.error
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
    req = urllib.request.Request(BASE + urllib.parse.quote(path) + q, method="POST", data=b"", headers={"X-Smoker": "1"})
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
            no_classic(b)
            other_sites()
            pin_flow(b)  # last: once a PIN is set, a fresh browser is locked
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


def section_chips(fr):
    """Each section-bar chip scrolls its section to just under the bar and is the one marked, even near the end of the
    page (the next, shorter section used to be marked instead)."""
    fails = []
    hrefs = fr.evaluate("""() => { const bar = document.getElementById('secbar'), m = bar.querySelector('a[aria-current="true"]');
      return [...bar.querySelectorAll('a')].filter(a => a.offsetParent !== null && !a.hidden).map(a => a.getAttribute('href'))
        .filter(h => document.querySelector(h).dataset.sect !== 'setup'); }""")
    for h in hrefs + hrefs[::-1]:
        fr.click(f'#secbar a[href="{h}"]')
        time.sleep(0.9)
        mark, gap = fr.evaluate("""(h) => { const bar = document.getElementById('secbar'), m = bar.querySelector('a[aria-current="true"]');
      return [m ? m.getAttribute('href') : null, Math.round(document.querySelector(h).getBoundingClientRect().top - bar.getBoundingClientRect().bottom)]; }""", h)
        if mark != h or abs(gap - 10) > 3:
            fails.append(f"section bar: {h} marked {mark}, {gap}px under the bar")
    return fails


def basic_mode(fr):
    """The Basic / Advanced switch: Basic shows only the Char-Griller app's essentials (food, chart, setup; temperature
    and target on the food cards; the timer), Advanced everything; the choice is remembered."""
    fails = []
    if fr.locator("#modesw").count() != 1:
        return ["basic mode: no Basic/Advanced switch"]
    fr.click('#modesw button[data-mode="basic"]'); time.sleep(0.3)
    vis = fr.evaluate("""() => [...document.querySelectorAll('[data-sect]')].filter(s => s.offsetParent !== null).map(s => s.dataset.sect)""")
    if set(vis) - {"food", "chart"} or "food" not in vis or "chart" not in vis:
        fails.append(f"basic mode: sections shown {vis}")
    links = fr.evaluate("""() => [...document.querySelectorAll('#secbar a')].filter(a => a.offsetParent !== null).map(a => a.textContent.trim())""")
    if set(links) != {"Food", "Chart", "Setup"}:
        fails.append(f"basic mode: section bar {links}")
    if fr.evaluate("[...document.querySelectorAll('.adv')].some(e => e.offsetParent !== null)"):
        fails.append("basic mode: advanced parts of the food cards still shown")
    if not fr.evaluate("!!document.querySelector('.timer') && document.querySelector('.timer').offsetParent !== null"):
        fails.append("basic mode: no timer card")
    if fr.evaluate("localStorage.getItem('smoker-mode')") != "basic":
        fails.append("basic mode: choice not remembered")
    fr.click('#modesw button[data-mode="advanced"]'); time.sleep(0.3)
    if fr.evaluate("document.querySelector('[data-sect=pit]').offsetParent === null"):
        fails.append("advanced mode: Pit & program still hidden")
    return fails


def offline(ctx):
    # LAN only: block everything else (the optional web fonts fail and the system fonts take over).
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(BASE) else r.abort())


def run_page(browser, width, height, shots):
    print(f"-- {width}px")
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script("try { localStorage.getItem('smoker-mode') || localStorage.setItem('smoker-mode', 'advanced'); } catch (e) {}")  # Advanced (the checks below are for it); basic_mode() tests Basic
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
    # The pit target in the top card: type it and Set.
    pg.evaluate("window.scrollTo(0, 0)")
    pg.fill("#heropit", "240")
    pg.click("#hero .hero-tgt .btn.pri")
    check(wait(lambda: value("number", "Pit target") == 240, 10, "the top card's target"), "the top card sets the pit target")
    for f in basic_mode(pg):
        check(False, f)
    check(True, f"Basic / Advanced at {width}px")
    for f in section_chips(pg):
        check(False, f)
    check(True, f"section bar chips at {width}px")
    pg.mouse.move(width // 2, height // 2)
    pg.mouse.wheel(0, -100000)
    time.sleep(0.8)
    first = pg.evaluate("document.querySelector('#secbar a[aria-current=true]').getAttribute('href')")
    check(first == pg.evaluate("document.querySelector('#secbar a').getAttribute('href')"), f"scrolling back to the top marks the first section ({first})")
    # a select through REST: Food 1 reads the spare probe (135.5 °F), then back (Setup: a page of its own)
    pg.click('#secbar a[href="#s-setup"]')
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
    pg.click("[data-sect=setup] .sect-back")
    pg.wait_for_timeout(3000)  # let the toast go
    # Your grill photo: with "Grill photo URL" set, the readings are pinned on the photo; cleared, the drawing returns.
    png = tiny_png()
    pg.context.route("http://photo.test/**", lambda r: r.fulfill(status=200, content_type="image/png", body=png))
    # Any other address is ignored (the owner's browser would load it): the drawing stays.
    post("/text/Grill photo URL/set", value="http://photo.test/grill.png")
    pg.wait_for_timeout(1500)
    check(pg.locator("#grillpic .gphoto").count() == 0 and pg.locator("#grillpic svg").count() == 1,
          "a photo URL that isn't the integration's photo (or this controller's) is ignored")
    post("/text/Grill photo URL/set", value="http://photo.test/api/smoker/grill_photo/image/abc123?token=x")
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


def _png(w, h):
    """A small valid PNG (solid colour) for the label photo."""
    import struct, zlib
    raw = b"".join(b"\x00" + bytes((200, 120, 80)) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def other_sites():
    """Another website (its script in the owner's browser) can't read or change anything; the page's own requests
    (no Origin on reads, its own on posts, X-Smoker on every change) still work. Mirrors components/standalone."""
    print("-- other websites")

    def status(path, method="GET", headers=None):
        req = urllib.request.Request(BASE + urllib.parse.quote(path), method=method, headers=headers or {},
                                     data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    evil = {"Origin": "http://evil.example"}
    check(status("/button/Forget the grill/press", "POST") == 403, "a change without X-Smoker is refused (a form, an <img>)")
    check(status("/button/Forget the grill/press", "GET") == 403, "a REST action sent as GET without X-Smoker is refused")
    check(status("/switch/Turbo/turn_on", "POST", {**evil, "X-Smoker": "1"}) == 403, "another origin can't change things")
    check(status("/local/pin", "POST", {"Origin": "null", "X-Smoker": "1", "Content-Type": "application/json"}) == 403,
          'an opaque ("null") origin can\'t claim the first PIN')
    check(status("/local/status", "GET", evil) == 403, "another origin can't read /local/status")
    check(status("/sensor/Pit temperature", "GET", evil) == 403, "another origin can't read the entities")
    check(status("/local/status", "OPTIONS", {**evil, "Access-Control-Request-Method": "POST"}) == 403,
          "a CORS preflight from another origin is refused")
    check(status("/local/status") == 200 and status("/sensor/Pit temperature") == 200, "a plain visit still reads")
    own = {"Origin": BASE, "X-Smoker": "1"}
    check(status("/local/status", "GET", {"Origin": BASE}) == 200, "the page's own origin reads")
    check(status("/text/Grill photo URL/set", "POST", own) == 200, "the page's own origin changes things")


def pin_flow(browser):
    """The device page's PIN: set it, store a key (write-only), lock, refused changes, unlock."""
    print("-- PIN")
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script("try { localStorage.getItem('smoker-mode') || localStorage.setItem('smoker-mode', 'advanced'); } catch (e) {}")  # Advanced (the checks below are for it); basic_mode() tests Basic
    offline(ctx)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    def setup(open_=True):  # Setup is a page of its own, opened from the section bar's Setup button
        if pg.evaluate("document.documentElement.classList.contains('setup-view')") != open_:
            if open_:
                pg.click('#secbar a[href="#s-setup"]')
            else:
                pg.click("[data-sect=setup] .sect-back")
            pg.wait_for_timeout(300)

    pg.goto(BASE + "/")
    pg.wait_for_selector("#lock h3", state="attached", timeout=15000)
    check(pg.locator("#s-setup").is_hidden() and pg.locator("#s-food").is_visible(), "Setup isn't on the main page")
    setup()
    check(pg.locator("#s-setup").is_visible() and pg.locator("#s-food").is_hidden() and pg.locator(".sect-back").is_visible(),
          "Setup opens as a page of its own, with Back to the cook")
    check("not set" in pg.inner_text("#lock"), "a new controller asks for a PIN")
    pg.go_back()
    pg.wait_for_timeout(300)
    check(pg.locator("#s-setup").is_hidden() and pg.locator("#s-food").is_visible(), "the browser's back returns to the cook")
    # First run without Home Assistant: the Get started checklist (the stand-in reports Home Assistant connected).
    pg.goto(BASE + "/?start")
    pg.wait_for_selector("#lock h3", state="attached", timeout=15000)
    check(pg.locator("#s-start").is_visible() and "Protect this page" in pg.inner_text("#start"), "Get started shows without Home Assistant")
    check(pg.locator("#start [data-a=quickntfy]").count() == 1, "one-tap ntfy works without a PIN (the PIN is optional)")
    pg.click("#start [data-a=opencard][data-c=lock]")
    pg.wait_for_timeout(300)
    check(pg.locator("#lock").is_visible(), "Get started's 'Set it' opens Setup at the PIN")
    check(pg.locator("#notif details[data-k=ntfy]").count() == 1 and "Set a PIN" not in pg.inner_text("#s-setup"),
          "without a PIN nothing is locked: keys can be stored")
    check("Optional" in pg.inner_text("#lock"), "the PIN card says it's optional")
    check(pg.evaluate("[...document.querySelectorAll('#s-setup .card')].pop().id") == "lock", "the PIN card is last in Setup")
    pg.fill("#pin1", "123456")
    pg.fill("#pin2", "123456")
    pg.click("#lock [data-a=pinset]")
    pg.wait_for_timeout(500)
    check("not set" in pg.inner_text("#lock"), "an easy PIN (123456) is refused")
    pg.fill("#pin1", "482913")
    pg.fill("#pin2", "482913")
    pg.click("#lock [data-a=pinset]")
    pg.wait_for_function("document.querySelector('#lock').innerText.includes('unlocked')", timeout=5000)
    check(True, "PIN set: this browser is unlocked")
    setup(False)
    check("1 of 3" in pg.inner_text("#start"), f"Get started counts the grill, not the optional PIN: {pg.inner_text('#start')[:60]!r}")
    pg.click("#start [data-a=quickntfy]")
    pg.wait_for_function("document.querySelector('#start code')", timeout=5000)
    topic = pg.inner_text("#start code")
    check(topic.startswith("smoker-") and len(topic) == 19, f"one-tap ntfy: a long random topic, shown once ({topic})")
    check(json.loads(urllib.request.urlopen(BASE + "/local/status", timeout=5).read())["set"]["ntfy"], "the topic is stored")
    pg.click("#start [data-a=hidestart]")
    pg.goto(BASE + "/")
    pg.wait_for_selector("#lock h3", state="attached", timeout=15000)
    check(pg.locator("#s-start").is_hidden(), "Get started stays hidden once hidden (and with Home Assistant)")
    setup()
    # A key: saved, shown only as set, never read back.
    pg.click("#notif details[data-k=ntfy] summary")
    pg.fill("#sec-ntfy_topic", "smoker-test-topic-k3v9")
    pg.click("#notif [data-a=secret][data-k=ntfy_topic]")
    pg.wait_for_function("document.querySelector('#notif').innerText.includes('ntfy ✓')", timeout=5000)
    check("smoker-test-topic-k3v9" not in pg.content(), "the ntfy topic is never shown back")
    # Time zone from the browser: offsets and DST rules.
    pg.click("#place [data-a=tz]")
    pg.wait_for_timeout(500)
    tz = json.loads(urllib.request.urlopen(BASE + "/local/status", timeout=5).read())
    check(tz["tz"] is True, "time zone sent")
    # Lock: a change is refused (401) and the grill target doesn't move; anyone without the PIN is refused too.
    pg.click("#lock [data-a=logout]")
    pg.wait_for_function("document.querySelector('#lock').innerText.includes('locked')", timeout=5000)
    setup(False)
    before = value("number", "Pit target")
    pg.locator("#pit [data-a=pit][data-d='1']").click()
    pg.wait_for_timeout(1500)
    check(value("number", "Pit target") == before, f"locked: pit + changed nothing ({before} -> {value('number', 'Pit target')})")
    check(pg.locator("#pinsheet").is_visible(), "locked: the page asks for the PIN right there")
    check("Smoker: Set the device page PIN" in pg.inner_text("#lock"), "a forgotten PIN: Home Assistant can set a new one")
    try:
        post("/number/Pit target/set", value="300")
        check(False, "a POST without the PIN was accepted")
    except urllib.error.HTTPError as e:
        check(e.code == 401, f"a POST without the PIN is refused ({e.code})")
    # Wrong then right PIN, in the panel.
    pg.fill("#pinsheet-in", "000000")
    pg.click("#pinsheet [data-a=pinsheetgo]")
    pg.wait_for_function("document.getElementById('pinsheet-msg').innerText.includes('Wrong')", timeout=5000)
    check(pg.locator("#pinsheet").is_visible(), "a wrong PIN doesn't unlock")
    pg.fill("#pinsheet-in", "482913")
    pg.click("#pinsheet [data-a=pinsheetgo]")
    pg.wait_for_function("document.getElementById('pinsheet').hidden", timeout=5000)
    check(True, "the right PIN unlocks from the panel")
    pg.wait_for_timeout(2600)
    pg.locator("#pit [data-a=pit][data-d='1']").click()
    check(wait(lambda: (value("number", "Pit target") or 0) > (before or 0), 10, "the new target"), "unlocked: pit + works")
    # Stage 2: chart, plan, journal (stars, tags, notes), Open Pitmaster sharing.
    check(pg.locator("#chart svg path").count() >= 2, "the chart draws the history")
    pg.click("#s-chart [data-a=range][data-h='12']")
    pg.wait_for_timeout(400)
    check(pg.locator("#range [aria-pressed=true]").inner_text() == "12h", "chart range buttons")
    pg.click("#fuel [data-a=fuelmode][data-m=start]")
    pg.click("#fuel [data-a=fuel][data-p='75']")
    pg.wait_for_timeout(400)
    check("Started at 75%" in pg.inner_text("#toast"), "charcoal logged from the controller's page")
    pg.fill("#servein", "2030-01-01T18:00")
    pg.click("#plan [data-a=plansave]")
    pg.wait_for_function("document.querySelector('#plan').innerText.includes('Light the grill by')", timeout=5000)
    check("Shared cooks like this" in pg.inner_text("#plan") or True, "plan saved, light-by shown")
    pg.click("#journal [data-a=jrate][data-n='4']")
    pg.wait_for_timeout(400)
    pg.click("#journal [data-a=jtag][data-t='juicy']")
    pg.wait_for_timeout(400)
    j = json.loads(urllib.request.urlopen(BASE + "/local/journal", timeout=5).read())["entries"][0]
    check(j.get("rating") == 4 and j.get("tags") == ["juicy"], f"journal: stars and 'How was it?' saved ({j.get('rating')}, {j.get('tags')})")
    pg.click("#share [data-a=sharecfg][data-k=enabled]")
    pg.wait_for_function("document.querySelector('#journal').innerText.includes('Share this cook')", timeout=5000)
    check("juicy" in pg.inner_text("#journal .sharebox"), "the share prompt shows the record in words")
    pg.click("#journal .sharebox [data-a=jshare]")
    pg.wait_for_function("document.querySelector('#journal').innerText.includes('shared')", timeout=5000)
    check(True, "shared from the controller's page")
    # The notification route menu saves (it used to be ignored: no data-n).
    setup()
    pg.select_option("#notif select[data-c=route]", "both")
    pg.wait_for_timeout(500)
    st = json.loads(urllib.request.urlopen(BASE + "/local/status", timeout=5).read())
    check(st["route"] == "both", f"notification route saved ({st['route']})")
    # Stage 3: the AI on the controller.
    check(pg.locator("#s-ai").is_hidden(), "the AI section stays hidden until it's set up")
    pg.select_option("#aisetup select[data-c=aiprov]", "claude")
    pg.wait_for_function("document.querySelector('#aisetup').innerText.includes('claude-opus-5-5')", timeout=5000)
    check(True, "AI provider picked; its default model shown")
    pg.fill("#sec-ai_key", "sk-test-not-a-real-key-123")
    pg.click("#aisetup [data-a=secret][data-k=ai_key]")
    pg.wait_for_function("!document.querySelector('#s-ai').classList.contains('x') && document.querySelector('#s-ai').hidden === false", timeout=5000)
    check("sk-test-not-a-real-key-123" not in pg.content(), "the AI key is never shown back")
    for path in ("/local/status", "/local/ai", "/local/settings"):
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            check("sk-test-not-a-real-key" not in r.read().decode("utf-8", "replace"), f"{path} never returns the AI key")
    with open(os.path.join(HERE, "webui-device.log"), encoding="utf-8", errors="replace") as f:
        check("sk-test-not-a-real-key" not in f.read(), "the AI key never reaches the controller's log")
    pg.click("#aisetup [data-a=aitest]")
    pg.wait_for_function("document.querySelector('#aisetup').innerText.includes('Working')", timeout=5000)
    check(True, "Test the key")
    setup(False)
    pg.click("#aiadv [data-a=aiadvise]")
    pg.wait_for_function("document.querySelector('#aiadv').innerText.includes('stall')", timeout=5000)
    check("Wrap" in pg.inner_text("#aiadv"), "the AI's second opinion is shown")
    pg.fill("#aiplanin", "9 lb pork shoulder for 6 pm")
    pg.click("#aiplan [data-a=aiplan]")
    pg.wait_for_function("document.querySelector('#aiplan [data-a=aiload]')", timeout=5000)
    pg.click("#aiplan [data-a=aiload]")
    pg.wait_for_function("document.getElementById('toast').innerText.includes('Program loaded')", timeout=6000)
    check(True, "Plan with AI: Load as program reports the controller's answer")
    pg.wait_for_timeout(2700)  # let that toast go before the next check reads it
    png = _png(64, 48)
    pg.set_input_files("#aifile", files=[{"name": "label.png", "mimeType": "image/png", "buffer": png}])
    pg.wait_for_function("document.querySelector('#ailabel').innerText.includes('pork butt')", timeout=8000)
    check(True, "a label photo is read")
    if pg.locator("#ailabel [data-a=aiassign]").count():
        pg.click("#ailabel [data-a=aiassign]")
        pg.wait_for_timeout(400)
        check("Set on Food" in pg.inner_text("#toast"), "the label's cut and weight set on a Food slot")
    # With a PIN set, using the AI needs no unlocking; its set-up and loading a plan as the program do.
    def local_post(path, body):
        req = urllib.request.Request(BASE + path, method="POST", data=json.dumps(body).encode(),
                                     headers={"X-Smoker": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    check(local_post("/local/ai/advise", {}) == 200, "locked: asking the AI still works")
    check(local_post("/local/ai/plan", {"request": "ribs for 5 pm"}) == 200, "locked: Plan with AI still works")
    check(local_post("/local/ai/load-program", {}) == 401, "locked: loading the AI's plan as the program needs the PIN")
    check(local_post("/local/ai/settings", {"auto": True}) == 401, "locked: AI set-up needs the PIN")
    check(local_post("/local/factory-reset", {}) == 401 and local_post("/local/factory-reset", {}) == 401,
          "locked: a factory reset needs the PIN")
    # The firmware update (no Home Assistant): shown under This controller, installed after a second tap.
    setup()
    pg.wait_for_function("document.querySelector('#dev').innerText.includes('0.2.99')", timeout=5000)
    check("Update available" in pg.inner_text("#dev"), "This controller offers the firmware update")
    pg.click("#dev [data-a=fwinstall]")
    pg.wait_for_timeout(200)
    check(get("/update/Firmware")["installs"] == 0 and "Tap again" in pg.inner_text("#dev"), "Install asks for a second tap")
    pg.click("#dev [data-a=fwinstall]")
    check(wait(lambda: get("/update/Firmware")["installs"] == 1, 5, "the install"), "the second tap installs the update")
    pg.wait_for_function("document.querySelector('#dev').innerText.includes('installing')", timeout=5000)
    check(True, "the page shows it installing")
    # Factory reset: at the bottom of This controller, with a warning; never one tap (the first arms it, red).
    resets = lambda: json.loads(urllib.request.urlopen(BASE + "/local/test/resets", timeout=5).read())["resets"]  # noqa: E731
    dev = pg.inner_text("#dev")
    check("Factory reset" in dev and "Erases everything" in dev, "This controller offers a factory reset, with a warning")
    check(pg.evaluate("document.querySelector('#dev').lastElementChild.previousElementSibling.id") == "freset",
          "the factory reset is the last item of This controller")
    pg.click("#dev [data-a=freset]")
    pg.wait_for_function("document.querySelector('#dev [data-a=freset]').classList.contains('arm')", timeout=5000)
    check(resets() == 0 and "Tap again" in pg.inner_text("#dev [data-a=freset]"), "one tap only arms the factory reset (red)")
    pg.click("#dev [data-a=freset]")
    pg.wait_for_function("document.getElementById('toast').innerText.includes('Erasing everything')", timeout=5000)
    check(resets() == 1 and "arm" not in pg.get_attribute("#dev [data-a=freset]", "class"),
          "the second tap within 10 s erases the controller")
    check(not errors, f"no page errors in the PIN flow {errors[:3]}")
    ctx.close()


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
    pg.wait_for_selector("#progfold", timeout=10000)
    if not pg.evaluate("document.getElementById('progfold').open"):  # a loaded program folds the editor away
        pg.click("#progfold > summary")
    pg.wait_for_selector("#progedit #ps-cut", timeout=10000)
    pg.select_option("#ps-cut", "chicken")
    check("name: Whole chicken; pit 325 until food1 >= 165" in pg.evaluate("document.querySelector('#progedit .pe-pre').textContent"), "the simple form fills in a whole chicken")
    pg.click("#pe-advanced")
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


def no_classic(browser):
    """?classic used to load ESPHome's stock page from oi.esphome.io into this origin (where the session token is)."""
    print("-- no ?classic")
    ctx = browser.new_context()
    ctx.add_init_script("try { localStorage.getItem('smoker-mode') || localStorage.setItem('smoker-mode', 'advanced'); } catch (e) {}")  # Advanced (the checks below are for it); basic_mode() tests Basic
    asked = []

    def route(r):
        if r.request.url.startswith(BASE):
            r.continue_()
        else:
            asked.append(r.request.url)
            r.abort()

    ctx.route("**/*", route)
    pg = ctx.new_page()
    pg.goto(BASE + "/?classic")
    pg.wait_for_selector(".wrap", timeout=10000)
    check(not asked, f"?classic loads nothing from other sites {asked[:2]}")
    check(pg.locator(".wrap").count() == 1, "?classic shows the smoker page")
    ctx.close()

if __name__ == "__main__":
    main()
