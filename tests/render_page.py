#!/usr/bin/env python3
"""Render test for the Smoker dashboard page with synthetic Home Assistant states.

Builds the page exactly as the integration serves it, loads it in a frame whose
parent provides a mock `hass` object (as panel.js does), checks for JS errors,
checks that key sections rendered, that an allowed call goes through and a
disallowed one is refused, and saves screenshots (light/dark, phone/desktop).

    python3 tests/render_page.py [outdir]
"""

import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "screens"))


def build_page():
    fe = os.path.join(ROOT, "custom_components/smoker/frontend")
    read = lambda n: open(os.path.join(fe, n), encoding="utf-8").read()  # noqa: E731
    html = read("page.html").replace("/*COMMON*/", read("common.js"))
    html = html.replace("<head>", "<head><script>" + read("shim.js") + "</script>\n", 1)
    i = html.find("</head>")
    style = "<style>" + read("style.css") + "</style>\n"  # fonts.html skipped: no network in tests
    return html[:i] + style + html[i:]


def st(eid, state, name, **attrs):
    a = {"friendly_name": name}
    a.update(attrs)
    return eid, {"entity_id": eid, "state": str(state), "attributes": a, "last_changed": "2026-11-22T10:00:00Z"}


F = {"unit_of_measurement": "°F", "device_class": "temperature"}
MIN = {"unit_of_measurement": "min"}
STATES = dict([
    st("sensor.smoker_pit_temperature", 251, "Smoker Pit temperature", **F),
    st("number.smoker_pit_target", 250, "Smoker Pit target", **F),
    st("binary_sensor.smoker_grill_connected", "on", "Smoker Grill connected"),
    st("sensor.smoker_grill_link", "wifi", "Smoker Grill link"),
    st("binary_sensor.smoker_lid", "off", "Smoker Lid"),
    st("binary_sensor.smoker_fan", "on", "Smoker Fan"),
    st("binary_sensor.smoker_grill_alarm", "off", "Smoker Grill alarm"),
    st("binary_sensor.smoker_cook_active", "on", "Smoker Cook active"),
    st("sensor.smoker_cook_elapsed", 412, "Smoker Cook elapsed", **MIN),
    st("sensor.smoker_food_1_temperature", 158, "Smoker Food 1 temperature", **F),
    st("number.smoker_food_1_target", 203, "Smoker Food 1 target", **F),
    st("sensor.smoker_food_1_phase", "Stall", "Smoker Food 1 phase"),
    st("binary_sensor.smoker_food_1_stall", "on", "Smoker Food 1 stall"),
    st("sensor.smoker_food_1_time_remaining", 312, "Smoker Food 1 time remaining", **MIN),
    st("sensor.smoker_food_1_time_remaining_early", 255, "Smoker Food 1 time remaining (early)", **MIN),
    st("sensor.smoker_food_1_time_remaining_late", 390, "Smoker Food 1 time remaining (late)", **MIN),
    st("sensor.smoker_food_1_estimated_total_cook_time", 760, "Smoker Food 1 estimated total cook time", **MIN),
    st("sensor.smoker_food_1_stall_remaining", 95, "Smoker Food 1 stall remaining", **MIN),
    st("sensor.smoker_food_1_rate", 0.8, "Smoker Food 1 rate", unit_of_measurement="°F/h"),
    st("select.smoker_food_1_protein", "Pork shoulder", "Smoker Food 1 protein",
       options=["Auto", "Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish"]),
    st("number.smoker_food_1_weight", 8.2, "Smoker Food 1 weight", unit_of_measurement="lb"),
    st("switch.smoker_food_1_wrapped", "off", "Smoker Food 1 wrapped"),
    st("sensor.smoker_food_1_estimate_basis", "Pork shoulder, 3 similar past cooks, grill factor 1.08, weather-adjusted",
       "Smoker Food 1 estimate basis"),
    st("binary_sensor.smoker_food_1_probe_warning", "off", "Smoker Food 1 probe warning"),
    st("sensor.smoker_food_2_temperature", "unknown", "Smoker Food 2 temperature", **F),
    st("sensor.smoker_food_3_temperature", 171, "Smoker Food 3 temperature", **F),
    st("number.smoker_food_3_target", 175, "Smoker Food 3 target", **F),
    st("sensor.smoker_food_3_phase", "Finishing", "Smoker Food 3 phase"),
    st("sensor.smoker_food_3_time_remaining", 22, "Smoker Food 3 time remaining", **MIN),
    st("sensor.smoker_food_3_time_remaining_early", 15, "Smoker Food 3 time remaining (early)", **MIN),
    st("sensor.smoker_food_3_time_remaining_late", 30, "Smoker Food 3 time remaining (late)", **MIN),
    st("select.smoker_food_3_protein", "Poultry", "Smoker Food 3 protein", options=["Auto", "Poultry"]),
    st("select.smoker_food_1_probe", "Grill probe 1", "Smoker Food 1 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant"]),
    st("select.smoker_food_2_probe", "Grill probe 2", "Smoker Food 2 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant"]),
    st("select.smoker_food_3_probe", "Home Assistant", "Smoker Food 3 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant"]),
    st("input_text.smoker_external_probe_3_entity", "sensor.example_probe", "Smoker external probe 3 entity"),
    st("sensor.example_probe", 171, "Example Probe", **F),
    st("sensor.example_probe_alarm", 203, "Example Probe alarm", **F),
    st("sensor.porch_temperature", 44, "Porch temperature", **F),
    st("binary_sensor.smoker_h5198_connected", "off", "Smoker H5198 connected"),
    st("sensor.smoker_food_3_estimate_basis", "Experimental (learning: 0 of 3 similar cooks). Poultry, 0 similar past cooks, "
       "grill factor 1.00; pull-at experimental (0 of 2 rests measured)", "Smoker Food 3 estimate basis"),
    st("sensor.smoker_food_3_pull_at", 170, "Smoker Food 3 pull at", **F),
    st("sensor.smoker_charcoal_estimate_basis", "Experimental: default burn rate for briquettes (learned from 0.0 of 3 kg).",
       "Smoker Charcoal estimate basis"),
    st("sensor.smoker_program_state", "Running", "Smoker Program state"),
    st("sensor.smoker_program_status", "Step 1/3, pit 250°F, until food1 158/165°F (held 0/30 min)", "Smoker Program status"),
    st("sensor.smoker_program_error", "", "Smoker Program error"),
    st("text.smoker_program", "name: Pork shoulder; pit 250 until food1 >= 165 for 30m; pit 275 until food1 >= 203; hold 160",
       "Smoker Program"),
    st("select.smoker_program_preset", "Pork shoulder (Texas crutch)", "Smoker Program preset",
       options=["Pork shoulder (Texas crutch)", "Brisket", "Ribs", "Custom"]),
    st("sensor.smoker_cooks_learned", 3, "Smoker Cooks learned"),
    st("sensor.smoker_grill_heat_factor", 1.08, "Smoker Grill heat factor"),
    st("input_number.smoker_ai_eta_minutes", 330, "Smoker AI ETA (minutes)"),
    st("sensor.smoker_ai_finish", "2099-01-01T15:30:00+00:00", "Smoker AI finish", device_class="timestamp"),
    st("input_text.smoker_ai_summary", "Stall began 70 min ago at 157°F; typical for an 8 lb butt at 250°F.", "Smoker AI summary"),
    st("input_text.smoker_ai_suggestion", "Wrap in butcher paper now to finish by 6:30 pm.", "Smoker AI suggestion"),
    st("input_boolean.smoker_ai_advisor", "on", "Smoker AI advisor"),
    st("input_datetime.smoker_serve_time", "2026-11-22 18:30:00", "Smoker serve by"),
    st("sensor.smoker_start_cooking_by", "2026-11-22T04:15:00+00:00", "Smoker start cooking by"),
    st("timer.smoker_rest", "idle", "Smoker rest timer"),
    st("sensor.smoker_wi_fi_signal", -61, "Smoker Wi-Fi signal", unit_of_measurement="dBm"),
    st("sensor.smoker_firmware_version", "0.1.0", "Smoker Firmware version"),
    st("switch.smoker_bridge_enabled", "on", "Smoker Bridge enabled"),
    st("update.smoker_firmware", "off", "Smoker Firmware", latest_version="0.1.0"),
    st("sensor.smoker_recommendations", "2026-11-22T09:40:00+00:00", "Smoker recommendations", mode="live",
       summary="Stall at 158°F after 6 h; on track for about 11:40 if you wrap now.",
       items=[{"when": "now", "title": "Wrap in butcher paper", "detail": "Bark is set; wrapping cuts the stall by ~1 h."},
              {"when": "at 195°F", "title": "Start probing for tenderness", "detail": "Probe should slide in like butter."},
              {"when": "18:00", "title": "Top up the hopper", "detail": "Wind picks up after 5 pm; expect higher fuel use."}]),
    st("sensor.smoker_charcoal_level", 62, "Smoker Charcoal level", unit_of_measurement="%"),
    st("sensor.smoker_charcoal_left", 9.9, "Smoker Charcoal left", unit_of_measurement="lb"),
    st("sensor.smoker_charcoal_hours_left", 6.4, "Smoker Charcoal hours left", unit_of_measurement="h"),
    st("sensor.smoker_charcoal_burn_rate", 1.55, "Smoker Charcoal burn rate", unit_of_measurement="lb/h"),
    st("sensor.smoker_charcoal_empty_at", "17:10", "Smoker Charcoal empty at"),
    st("select.smoker_charcoal_type", "Briquettes", "Smoker Charcoal type", options=["Briquettes", "Lump"]),
    st("number.smoker_slice_at", 150, "Smoker Slice at", **F),
    st("sensor.smoker_food_1_pull_at", 199, "Smoker Food 1 pull at", **F),
    st("switch.smoker_food_1_pulled", "off", "Smoker Food 1 pulled"),
    st("weather.forecast_example", "partlycloudy", "Example", temperature=44, humidity=74, wind_speed=6, temperature_unit="°F"),
])

HARNESS = """<!doctype html><html><body style="margin:0">
<iframe id="f" style="border:0;width:100vw;height:100vh"></iframe>
<script>
const STATES = %STATES%;
window.calls = [];
function hist(ids, start) {
  const out = {}; const now = Date.now();
  ids.forEach((id, k) => { const L = []; const base = parseFloat(STATES[id] && STATES[id].state) || 150;
    for (let i = 72; i >= 0; i--) L.push({ s: String(base - (k ? i * 0.5 : Math.sin(i / 4) * 6)), lu: (now - i * 5 * 60000) / 1000 });
    out[id] = L; });
  return out;
}
const JOURNAL = {
  entries: [{ id: 'abc123def456', started: Date.now() / 1000 - 86400 * 3 - 12 * 3600, ended: Date.now() / 1000 - 86400 * 3,
    probe: 'food1', probe_name: 'Food 1', profile: 'Pork shoulder', weight_kg: 3.8, wrapped: true, pit_c: 121, stall_h: 3.1,
    total_h: 11.6, ambient_c: 4, items: [{ name: 'Bone-in pork shoulder', weight_lb: 8.4 }], photos: [], notes: 'Great bark', rating: 4 }],
  draft: { items: [{ id: 'aa11bb22', name: 'Beef brisket (packer)', profile: 'Brisket', weight_lb: 14.2, barcode: '', notes: 'prime', probe: null }], photos: [] },
};
window.__smHass = {
  fetchWithAuth: (path, opt) => { window.calls.push(['api', path, opt && opt.method]);
    const body = path === '/api/smoker/journal' ? JOURNAL : path === '/api/smoker/draft' ? JOURNAL.draft : {};
    return Promise.resolve(new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })); },
  states: STATES,
  callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); },
  callWS: (m) => { window.calls.push(['ws', m.type, m]); return Promise.resolve(m.type.startsWith('history') ? hist(m.entity_ids) : {}); },
};
document.getElementById('f').srcdoc = %PAGE%;
</script></body></html>"""


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(OUT, exist_ok=True)
    page_html = build_page()
    harness = HARNESS.replace("%STATES%", json.dumps(STATES)).replace("%PAGE%", json.dumps(page_html).replace("</", "<\\/"))
    hp = os.path.join(OUT, "harness.html")
    open(hp, "w").write(harness)
    failures = []
    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")
        b = p.chromium.launch(executable_path=exe) if os.path.exists(exe) else p.chromium.launch()
        for scheme in ["light", "dark"]:
            for name, vp in [("desktop", {"width": 1280, "height": 1900}), ("phone", {"width": 390, "height": 2600})]:
                ctx = b.new_context(viewport=vp, color_scheme=scheme, device_scale_factor=1)
                pg = ctx.new_page()
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.goto("file://" + hp)
                time.sleep(2.5)
                fr = next(f for f in pg.frames if f.url.startswith("about:srcdoc"))
                checks = {
                    "pit": fr.inner_text("#pitbig"),
                    "kpis": fr.inner_text("#kpis"),
                    "probes": fr.inner_text("#probes"),
                    "program": fr.inner_text("#progcard"),
                    "chart": fr.inner_html("#chart")[:40],
                    "recs": fr.inner_text("#recs"),
                    "fuel": fr.inner_text("#fuelcard"),
                    "scan": fr.inner_text("#scancard"),
                    "journal": fr.inner_text("#journal"),
                    "sources": fr.inner_html("#sources"),
                }
                if errors:
                    failures.append(f"{scheme}/{name}: JS errors {errors}")
                if "251" not in checks["pit"]:
                    failures.append(f"{scheme}/{name}: pit temp missing: {checks['pit']!r}")
                if "Food 1" not in checks["probes"] or "Food 3" not in checks["probes"]:
                    failures.append(f"{scheme}/{name}: probe cards missing")
                if "Food 2" in checks["probes"]:
                    failures.append(f"{scheme}/{name}: unplugged Food 2 should be hidden")
                if "62%" not in checks["fuel"] or "Topped up to" not in checks["fuel"]:
                    failures.append(f"{scheme}/{name}: charcoal card: {checks['fuel'][:120]!r}")
                if "Beef brisket" not in checks["scan"]:
                    failures.append(f"{scheme}/{name}: scanned item missing")
                if "Pork shoulder" not in checks["journal"] or "11.6 h" not in checks["journal"]:
                    failures.append(f"{scheme}/{name}: journal entry missing: {checks['journal'][:120]!r}")
                # Experimental labels: on Food 3 (no history yet: ETA + pull-at), not on Food 1 (3 similar cooks).
                cards = fr.evaluate("""() => [...document.querySelectorAll('#probes .probe')].map(c =>
                    [c.querySelector('h3').innerText, c.querySelectorAll('.chip.exp').length])""")
                exp = {t.split()[0] + " " + t.split()[1]: n for t, n in cards}
                if exp.get("Food 1") != 0 or exp.get("Food 3") != 2:
                    failures.append(f"{scheme}/{name}: experimental chips per card {exp}")
                if "Experimental" not in checks["fuel"] or "Experimental" not in checks["recs"]:
                    failures.append(f"{scheme}/{name}: experimental label missing: fuel {checks['fuel'][:200]!r} recs {checks['recs'][:120]!r}")
                src = checks["sources"]
                if (src.count("<select") != 4 or 'value="sensor.example_probe" selected' not in src or "H5198 probe 4" not in src
                        or "Porch temperature" not in src or "example_probe_alarm" in src):
                    failures.append(f"{scheme}/{name}: probe sources: {src[:160]!r}")
                if "Home Assistant" not in checks["probes"]:
                    failures.append(f"{scheme}/{name}: Food 3's source not shown on its card")
                if "Pull at" not in checks["probes"]:
                    failures.append(f"{scheme}/{name}: pull-at row missing")
                if "Wrap in butcher paper" not in checks["recs"]:
                    failures.append(f"{scheme}/{name}: recommendations missing")
                if "<svg" not in checks["chart"]:
                    failures.append(f"{scheme}/{name}: chart not drawn")
                # horizontal overflow on phones
                ow = fr.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if ow > 1:
                    failures.append(f"{scheme}/{name}: horizontal overflow {ow}px")
                pg.screenshot(path=os.path.join(OUT, f"smoker-{name}-{scheme}.png"), full_page=True)
                if scheme == "light" and name == "desktop":
                    fr.click("#pitcard .step .btn:last-child")
                    time.sleep(0.3)
                    calls = pg.evaluate("window.calls")
                    if not any(c[0] == "number" and c[1] == "set_value" and c[2]["value"] == 255 for c in calls):
                        failures.append(f"pit + did not call number.set_value 255: {calls}")
                    # Typed text survives a live re-render of its section.
                    fr.fill("#progtext", "pit 300 until food1 >= 190")
                    fr.evaluate("document.activeElement.blur()")  # keyboard dismissed
                    pg.evaluate("""() => { const st = window.__smHass.states;
                        st['sensor.smoker_program_status'] = Object.assign({}, st['sensor.smoker_program_status'], {state: 'Step 2/3 (changed)'});
                        window.__smHass = Object.assign({}, window.__smHass, {states: Object.assign({}, st)});
                        document.getElementById('f').contentWindow.__smOnHass(); }""")
                    time.sleep(0.6)
                    if "changed" not in fr.inner_text("#progcard"):
                        failures.append("program card did not re-render on state change")
                    if fr.input_value("#progtext") != "pit 300 until food1 >= 190":
                        failures.append("typed program text was lost on re-render")
                    # Fuel: 'Topped up to' then '1/2' calls the refill action with 50 %.
                    fr.click("#fuelcard .seg button:nth-child(3)")
                    time.sleep(0.3)
                    fr.click("#fuelcard .fracs button:nth-child(2)")
                    time.sleep(0.3)
                    calls = pg.evaluate("window.calls")
                    if not any(c[0] == "ws" and c[2].get("service") == "gravity980_fuel_refilled"
                               and c[2].get("service_data", {}).get("percent") == 50 for c in calls):
                        failures.append(f"fuel refill action not called: {[c for c in calls if c[0]=='ws'][-3:]}")
                    # The shim's journal API refuses other paths.
                    r = fr.evaluate("window.hdHA.api('GET','/api/config').then(()=>'ok',e=>e.message)")
                    if "not allowed" not in r:
                        failures.append("shim api allowed /api/config")
                    r = fr.evaluate("window.hdHA.call('lock','unlock','lock.front_door').then(()=>'ok',e=>e.message)")
                    if "not allowed" not in r:
                        failures.append("shim allowed lock.unlock")
                    r = fr.evaluate("window.hdHA.call('switch','turn_on','switch.kitchen_lights').then(()=>'ok',e=>e.message)")
                    if "not a smoker entity" not in r:
                        failures.append("shim allowed a non-smoker switch")
                ctx.close()
        b.close()
    for f in failures:
        print("FAIL", f)
    print(f"screenshots in {OUT}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
