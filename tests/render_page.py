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
    st("switch.smoker_boost", "off", "Smoker Boost"),
    st("sensor.smoker_boost_status", "", "Smoker Boost status"),
    st("binary_sensor.smoker_grill_connected", "on", "Smoker Grill connected"),
    st("sensor.smoker_grill_link", "wifi", "Smoker Grill link"),
    st("sensor.smoker_grill_link_status", "Connected over Wi-Fi", "Smoker Grill link status"),
    st("sensor.smoker_release", "0.2.20", "Smoker Release"),
    st("binary_sensor.smoker_grill_on_wi_fi", "on", "Smoker Grill on Wi-Fi"),
    st("binary_sensor.smoker_grill_on_bluetooth", "on", "Smoker Grill on Bluetooth"),
    st("sensor.smoker_grill_bluetooth_signal", "-67", "Smoker Grill Bluetooth signal", unit_of_measurement="dBm"),
    st("sensor.smoker_grill_wi_fi_signal", "-44", "Smoker Grill Wi-Fi signal", unit_of_measurement="dBm"),
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
    st("select.smoker_food_1_probe", "Grill probe 1", "Smoker Food 1 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant", "Wired probe 1", "Wired probe 2", "Wired probe 3", "Wired probe 4"]),
    st("select.smoker_food_2_probe", "Wired probe 1", "Smoker Food 2 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant", "Wired probe 1", "Wired probe 2", "Wired probe 3", "Wired probe 4"]),
    st("select.smoker_food_3_probe", "Home Assistant", "Smoker Food 3 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant", "Wired probe 1", "Wired probe 2", "Wired probe 3", "Wired probe 4"]),
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
    st("switch.smoker_control_over_bluetooth_experimental", "on", "Smoker Control over Bluetooth (experimental)"),
    st("button.smoker_restart", "unknown", "Smoker Restart"),
    st("button.smoker_grill_wi_fi_scan", "unknown", "Smoker Grill Wi-Fi: scan"),
    st("button.smoker_grill_wi_fi_join_saved_network", "unknown", "Smoker Grill Wi-Fi: join saved network"),
    st("sensor.smoker_grill_wi_fi_networks", "Grill-Network, Neighbour", "Smoker Grill Wi-Fi networks"),
    st("sensor.smoker_program_state", "Running", "Smoker Program state"),
    st("sensor.smoker_program_status", "Step 1/3, pit 250°F, until food1 158/165°F (held 0/30 min)", "Smoker Program status"),
    st("sensor.smoker_program_error", "", "Smoker Program error"),
    st("text.smoker_program", "name: Pork shoulder; pit 250 until food1 >= 165 for 30m; pit 275 until food1 >= 203; hold 200",
       "Smoker Program"),  # FIXTURE_PROGRAM
    st("select.smoker_program_preset", "Pork shoulder (Texas crutch)", "Smoker Program preset",
       options=["Pork shoulder (Texas crutch)", "Brisket", "Ribs", "Custom"]),
    st("sensor.smoker_cooks_learned", 3, "Smoker Cooks learned"),
    st("sensor.smoker_grill_heat_factor", 1.08, "Smoker Grill heat factor"),
    st("input_number.smoker_ai_eta_minutes", 330, "Smoker AI ETA (minutes)"),
    st("sensor.smoker_ai_finish", "2099-01-01T15:30:00+00:00", "Smoker AI finish", device_class="timestamp"),
    st("input_text.smoker_ai_summary", "Stall began 70 min ago at 157°F; typical for an 8 lb butt at 250°F.", "Smoker AI summary"),
    st("input_text.smoker_ai_suggestion", "Wrap in butcher paper now to finish by 6:30 pm.", "Smoker AI suggestion"),
    st("input_boolean.smoker_ai_advisor", "on", "Smoker AI advisor"),
    st("input_text.smoker_ai_plan", "Run the pit at 250F to 165F, wrap, then 275F to 203F: about 11 h.", "Smoker AI plan"),
    # The cook's plan for Food 1: started 2 h ago at 100°F, +10°F every 30 min, so at 159°F it's ~55 min ahead.
    st("sensor.smoker_food_1_plan", "1;%d;30;F;%s" % (int(time.time()) - 7200, ",".join(str(100 + 10 * i) for i in range(11))),
       "Smoker Food 1 plan"),
    st("input_number.smoker_charcoal_stock_kg", 12.5, "Smoker charcoal in stock", unit_of_measurement="kg"),
    st("input_number.smoker_charcoal_bag_kg", 9, "Smoker charcoal bag size", unit_of_measurement="kg"),
    st("input_number.smoker_charcoal_bag_price", 21.99, "Smoker charcoal bag price"),
    st("input_number.smoker_hours_ash", 13.2, "Smoker hours since the ash was emptied", unit_of_measurement="h"),
    st("input_number.smoker_hours_grease", 4, "Smoker hours since the grease tray was cleaned", unit_of_measurement="h"),
    st("input_number.smoker_hours_gasket", 40, "Smoker hours since the gasket and fan were checked", unit_of_measurement="h"),
    st("input_text.smoker_charcoal_last_cook", "3.1 kg of charcoal (7.57), 0.28 kg/h at 41° on Sun 22 Nov", "Smoker charcoal, last cook"),
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
const SHARE = { enabled: true, auto: false, shared: 0, privacy: 'https://example.invalid/sharing',
  community: { cooks: 42, updated: '2026-11-23' },
  entries: [{ entry: 'abc123def456', status: 'pending', record: { v: 1, id: '0123456789abcdef0123456789abcdef', grill: 'gravity980',
    release: '0.2.25', season: 'autumn', cut: 'Pork shoulder', weight_lb: 8.5, wrapped: true, pit_f: 250, target_f: 203,
    stall_h: 3.1, total_h: 11.6, outside_f: 35, rating: 4, tags: ['juicy', 'great bark'] } }] };
window.__smHass = {
  fetchWithAuth: (path, opt) => { window.calls.push(['api', path, opt && opt.method]);
    const body = path === '/api/smoker/journal' ? JOURNAL : path === '/api/smoker/draft' ? JOURNAL.draft
      : path.startsWith('/api/smoker/sharing') ? SHARE : {};
    return Promise.resolve(new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })); },
  states: STATES,
  callService: (d, s, data) => { window.calls.push([d, s, data]); return Promise.resolve(); },
  callWS: (m) => { window.calls.push(['ws', m.type, m]); return Promise.resolve(m.type.startsWith('history') ? hist(m.entity_ids) : {}); },
};
document.getElementById('f').srcdoc = %PAGE%;
</script></body></html>"""


FIXTURE_PROGRAM = STATES["text.smoker_program"]["state"]
EDITOR_SHOTS = os.environ.get("EDITOR_SHOTS")  # optional: where to save the editor's phone screenshot


def presets():
    """The program presets from firmware/base.yaml (cook_assistant: presets:)."""
    import re
    src = open(os.path.join(ROOT, "firmware/base.yaml"), encoding="utf-8").read()
    block = src[src.index("  presets:"):src.index("  probes:", src.index("  presets:"))]
    return [json.loads(m) for m in re.findall(r'program: ("(?:[^"\\]|\\.)*")', block)]


def shared_blocks_match():
    """page.html and the device page's ui.js carry the same shared blocks (cook program editor, page sections)."""
    for name in ("cook program editor", "page sections", "cook plan"):
        b, e = f"// ==== BEGIN {name} (shared block) ====", f"// ==== END {name} (shared block) ===="
        out = []
        for f in ("custom_components/smoker/frontend/page.html", "firmware/device-ui/ui.js"):
            s = open(os.path.join(ROOT, f), encoding="utf-8").read()
            out.append(s[s.index(b):s.index(e)] if b in s and e in s else None)
        if out[0] is None or out[0] != out[1]:
            return False
    return True


def set_program(pg, fr, text, error=""):
    """The controller's Program text (and error) change, as after a preset or a load."""
    pg.evaluate("""([t, e]) => { const st = window.__smHass.states;
        st['text.smoker_program'] = Object.assign({}, st['text.smoker_program'], {state: t});
        st['sensor.smoker_program_error'] = Object.assign({}, st['sensor.smoker_program_error'], {state: e});
        window.__smHass = Object.assign({}, window.__smHass, {states: Object.assign({}, st)});
        document.getElementById('f').contentWindow.__smOnHass(); }""", [text, error])
    time.sleep(0.4)


def editor_text(fr):
    return fr.evaluate("progEd.text()")


def program_editor(pg, fr):
    """The step editor in the Cook program card."""
    fails = []
    fr.evaluate("document.activeElement && document.activeElement.blur()")
    # The fixture's program is running, so the editor starts folded away: open it.
    if fr.evaluate("!!document.getElementById('progfold') && !document.getElementById('progfold').open"):
        fr.click("#progfold > summary")
    else:
        fails.append("program editor: expected it folded while the program runs")
    fails += simple_form(pg, fr)
    fr.click("#pe-advanced")
    # The fixture's program as steps.
    steps = fr.evaluate("""() => [...document.querySelectorAll('#progedit .pe-step')].map(li => ({
        kind: li.querySelector('[data-pe=kind]').value, temp: (li.querySelector('[data-pe=temp]') || {}).value,
        conds: [...li.querySelectorAll('.pe-cond')].map(c => [c.querySelector('[data-pe=ctype]').value,
            (c.querySelector('[data-pe=cprobe]') || {}).value, (c.querySelector('[data-pe=cval]') || {}).value,
            (c.querySelector('[data-pe=cheld]') || {}).value])}))""")
    want = [{"kind": "pit", "temp": "250", "conds": [["gte", "1", "165", "30"]]},
            {"kind": "pit", "temp": "275", "conds": [["gte", "1", "203", ""]]},
            {"kind": "hold", "temp": "200", "conds": []}]
    if steps != want:
        fails.append(f"editor: fixture program as steps {steps}")
    if fr.input_value("#pe-name") != "Pork shoulder":
        fails.append("editor: program name not shown")
    if "°F" not in fr.inner_text("#progedit .pe-step"):
        fails.append("editor: unit missing")
    # Presets: text -> steps -> text is stable, through the page (the controller's text changes as after a preset).
    for t in presets():
        set_program(pg, fr, t)
        if editor_text(fr) != t or fr.locator("#progedit .pe-step").count() != t.count(";"):
            fails.append(f"editor: preset not shown as steps or changed: {t!r} -> {editor_text(fr)!r}")
        fr.click("#pe-totext")
        if fr.input_value("#progtext") != t:
            fails.append(f"editor: Edit as text changed the preset: {fr.input_value('#progtext')!r}")
        fr.click("#pe-tosteps")
        if editor_text(fr) != t or fr.locator("#progedit .pe-step").count() != t.count(";"):
            fails.append(f"editor: back to steps changed the preset: {editor_text(fr)!r}")
    # Add a step (it goes before the final hold) and fill it in.
    set_program(pg, fr, FIXTURE_PROGRAM)
    fr.click("#pe-addstep")
    if fr.evaluate("document.activeElement.id") != "pe-s2-temp":
        fails.append(f"editor: new step's temperature not focused ({fr.evaluate('document.activeElement.id')})")
    fr.fill("#pe-s2-temp", "300")
    fr.select_option("#pe-s2-c0-type", "after")
    fr.fill("#pe-s2-c0-v", "2")
    fr.click("#pe-s2-addc")
    fr.select_option("#pe-s2-c1-type", "lte")
    fr.select_option("#pe-s2-c1-p", "3")
    fr.fill("#pe-s2-c1-v", "140")
    fr.fill("#pe-s2-note", "Spritz the ribs")
    fr.fill("#pe-name", "Test cook")
    fr.evaluate("document.activeElement.blur()")
    expect = ('name: Test cook; pit 250 until food1 >= 165 for 30m; pit 275 until food1 >= 203; '
              'pit 300 notify "Spritz the ribs" until after 2h or food3 <= 140; hold 200')
    if editor_text(fr) != expect:
        fails.append(f"editor: built program {editor_text(fr)!r}")
    if expect not in fr.evaluate("document.querySelector('#progedit .pe-pre').textContent"):
        fails.append("editor: preview doesn't show the program")
    # Move it up and back down.
    fr.click("#pe-s2-up")
    if " pit 300 " not in editor_text(fr).split(";")[2]:
        fails.append(f"editor: move up {editor_text(fr)!r}")
    fr.click("#pe-s1-dn")
    if editor_text(fr) != expect:
        fails.append(f"editor: move down {editor_text(fr)!r}")
    # A live update doesn't lose the edits.
    pg.evaluate("""() => { const st = window.__smHass.states; const k = 'sensor.smoker_pit_temperature';
        st[k] = Object.assign({}, st[k], {state: '253'}); window.__smHass = Object.assign({}, window.__smHass, {states: Object.assign({}, st)});
        document.getElementById('f').contentWindow.__smOnHass(); }""")
    time.sleep(0.4)
    if editor_text(fr) != expect or fr.input_value("#pe-s2-temp") != "300":
        fails.append("editor: edits lost on a live update")
    # Load sends exactly that text to the controller's load_program action.
    n0 = len(pg.evaluate("window.calls"))
    fr.click("#pe-load")
    time.sleep(0.3)
    sent = [c for c in pg.evaluate("window.calls")[n0:] if c[0] == "ws" and c[2].get("service") == "gravity980_load_program"]
    if not sent or sent[0][2].get("service_data", {}).get("program") != expect or sent[0][2].get("domain") != "esphome":
        fails.append(f"editor: load_program not called with the program: {pg.evaluate('window.calls')[n0:]}")
    if "Sent" not in fr.inner_text("#progedit .pe-load"):
        fails.append("editor: no 'sent' state after Load")
    # The controller takes it: the editor follows it; the controller's own error is shown.
    set_program(pg, fr, expect, "step 3: unknown probe 'food3'")
    if "unknown probe 'food3'" not in fr.inner_text("#progstat"):
        fails.append("editor: the controller's Program error isn't shown")
    if "controller's program" not in fr.inner_text("#progedit .pe-load"):
        fails.append(f"editor: not marked as the controller's program after it took it: {fr.inner_text('#progedit .pe-load')!r}")
    set_program(pg, fr, FIXTURE_PROGRAM)
    # Invalid input: a missing temperature, a hold that isn't last, a pit out of range.
    fr.fill("#pe-s1-temp", "")
    errs = fr.inner_text("#progedit .pe-errs") if fr.locator("#progedit .pe-errs").count() else ""
    if "Step 2: set the pit temperature" not in errs or not fr.is_disabled("#pe-load"):
        fails.append(f"editor: missing temperature not flagged: {errs!r}")
    fr.fill("#pe-s1-temp", "275")
    fr.select_option("#pe-s0-kind", "hold")
    errs = fr.inner_text("#progedit .pe-errs") if fr.locator("#progedit .pe-errs").count() else ""
    if "Step 1: \"Hold at\" must be the last step" not in errs or not fr.is_disabled("#pe-load"):
        fails.append(f"editor: hold not last not flagged: {errs!r}")
    fr.select_option("#pe-s0-kind", "pit")
    fr.fill("#pe-s0-temp", "900")
    fr.press("#pe-s0-temp", "Tab")
    if fr.input_value("#pe-s0-temp") != "700":
        fails.append(f"editor: pit not clamped to 700 ({fr.input_value('#pe-s0-temp')})")
    if fr.locator("#progedit .pe-errs").count():
        fails.append(f"editor: errors left after fixing: {fr.inner_text('#progedit .pe-errs')!r}")
    # Text the step editor can't show: text mode with a note, nothing lost.
    fr.evaluate("progEd.state.touched = false; document.activeElement.blur()")
    set_program(pg, fr, "pit 250 until pit <= 200")
    if fr.locator("#progtext").count() != 1 or fr.input_value("#progtext") != "pit 250 until pit <= 200" or "can't show" not in fr.inner_text("#progedit"):
        fails.append(f"editor: unknown syntax didn't fall back to text: {fr.inner_text('#progedit')[:160]!r}")
    fr.fill("#progtext", "pit 250 until food1 >= 190")
    fr.click("#pe-tosteps")
    if fr.locator("#progedit .pe-step").count() != 1 or editor_text(fr) != "pit 250 until food1 >= 190":
        fails.append(f"editor: text back to steps: {editor_text(fr)!r}")
    fr.evaluate("progEd.state.touched = false")
    return fails


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


def simple_form(pg, fr):
    """The simple form (the editor's default): a cut fills in a typical cook and writes an ordinary program."""
    fails = []
    if fr.locator("#ps-cut").count() != 1:
        return ["simple form: not shown first"]
    want = {
        "pork": 'name: Pork shoulder / butt; pit 250 until food1 >= 165; pit 275 notify "Wrap it in butcher paper now" until food1 >= 203; hold 200 notify "Pork shoulder / butt is done: rest it"',
        "chicken": 'name: Whole chicken; pit 325 until food1 >= 165; notify "Whole chicken is done" shutdown',
        "steak": 'name: Steak, reverse sear; pit 225 until food1 >= 115; pit 700 notify "Time to sear: the pit is heading up to 700°F" until food1 >= 130; notify "Steak, reverse sear is done" shutdown',
        "ribs321": 'name: Ribs, 3-2-1; pit 225 until after 3h; pit 225 notify "Wrap the ribs in foil now" until after 2h; pit 225 notify "Unwrap the ribs (and sauce them)" until after 1h; hold 200 notify "Ribs, 3-2-1 is done: rest it"',
    }
    for cut, prog in want.items():
        fr.select_option("#ps-cut", cut)
        if editor_text(fr) != prog:
            fails.append(f"simple form {cut}: {editor_text(fr)!r}")
    # brisket, no wrap at the same temperature: one smoke step to the end
    fr.select_option("#ps-cut", "brisket")
    fr.select_option("#ps-wrap", "none")
    fr.fill("#ps-t2", "250")
    fr.select_option("#ps-probe", "2")
    fr.select_option("#ps-after", "off")
    if editor_text(fr) != 'name: Brisket; pit 250 until food2 >= 203; notify "Brisket is done" shutdown':
        fails.append(f"simple form, no wrap: {editor_text(fr)!r}")
    fr.fill("#ps-t1", "900")
    if not fr.is_disabled("#pe-load"):
        fails.append("simple form: a pit outside the range should block Load")
    fr.fill("#ps-t1", "250")
    n0 = len(pg.evaluate("window.calls"))
    fr.click("#pe-load")
    time.sleep(0.4)
    sent = [c for c in pg.evaluate("window.calls")[n0:] if c[0] == "ws" and c[2].get("service") == "gravity980_load_program"]
    if not sent or "food2 >= 203" not in sent[0][2].get("service_data", {}).get("program", ""):
        fails.append(f"simple form: Load didn't send the program: {pg.evaluate('window.calls')[n0:]}")
    # Advanced starts from what the form built
    fr.click("#pe-advanced")
    if fr.locator("#progedit .pe-step").count() != 2 or fr.input_value("#pe-name") != "Brisket":
        fails.append(f"simple form: Advanced didn't show the form's steps: {editor_text(fr)!r}")
    fr.click("#pe-simple")
    fr.evaluate("progEd.state.touched = false; progEd.state.sent = null; document.activeElement.blur()")
    set_program(pg, fr, "")
    set_program(pg, fr, FIXTURE_PROGRAM)
    return fails


def editor_on_phone(pg, fr):
    """At 390 px: the editor with a few conditions fits the screen."""
    fails = []
    fr.evaluate("document.getElementById('progfold') && (document.getElementById('progfold').open = true)")
    if fr.locator("#pe-advanced").count():
        fr.click("#pe-advanced")
    fr.click("#pe-addstep")
    fr.select_option("#pe-s2-c0-type", "after")
    fr.fill("#pe-s2-c0-v", "90")
    fr.select_option("#pe-s2-c0-u", "m")
    fr.click("#pe-s2-addc")
    fr.select_option("#pe-s2-c1-type", "at")
    fr.fill("#pe-s2-c1-v", "17:30")
    fr.click("#pe-s2-addc")
    fr.select_option("#pe-s2-c2-type", "stall_end")
    fr.fill("#pe-s2-note", "Wrap it now")
    fr.evaluate("document.activeElement.blur()")
    if "until after 90m or at 17:30 or stall_end food1" not in editor_text(fr):
        fails.append(f"phone editor: {editor_text(fr)!r}")
    ow = fr.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    wide = fr.evaluate("""() => [...document.querySelectorAll('#progcard *')].filter(e => e.getBoundingClientRect().right >
        document.getElementById('progcard').getBoundingClientRect().right + 1).map(e => e.tagName + '#' + e.id).slice(0, 5)""")
    if ow > 1 or wide:
        fails.append(f"phone editor: overflow {ow}px {wide}")
    if EDITOR_SHOTS:
        os.makedirs(EDITOR_SHOTS, exist_ok=True)
        fr.evaluate("document.querySelector('#progedit details.pe-prev').open = true")
        fr.evaluate("document.getElementById('secbar').style.position = 'static'")  # the sticky bar would cover the card
        fr.locator("#progcard").screenshot(path=os.path.join(EDITOR_SHOTS, "ha-editor-phone-light.png"))
        fr.evaluate("document.getElementById('secbar').style.position = ''")
    return fails


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(OUT, exist_ok=True)
    page_html = build_page()
    harness = HARNESS.replace("%STATES%", json.dumps(STATES)).replace("%PAGE%", json.dumps(page_html).replace("</", "<\\/"))
    hp = os.path.join(OUT, "harness.html")
    open(hp, "w").write(harness)
    failures = []
    if not shared_blocks_match():
        failures.append("the shared blocks (program editor, page sections) in page.html and ui.js differ")
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
                    "pitcard": fr.inner_text("#pitcard"),
                    "controlcard": fr.inner_text("#controlcard"),
                    "heronext": fr.inner_text("#heronext"),
                    "grill": fr.inner_html("#grillpic"),
                    "topbar": fr.inner_text("#topbar"),
                    "secbar": fr.eval_on_selector_all("#secbar a", "as => as.map(a => a.textContent)"),
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
                if "Controlling the grill over Wi-Fi" not in checks["pitcard"]:
                    failures.append(f"{scheme}/{name}: control row: {checks['pitcard'][:200]!r}")
                if "Control over Bluetooth" not in checks["controlcard"] or "Bridge enabled" not in checks["controlcard"]:
                    failures.append(f"{scheme}/{name}: connection card: {checks['controlcard'][:200]!r}")
                g = checks["grill"]
                if "<svg" not in g or "251°" not in g or "62%" not in g or "F1 " not in g or "F3 171°" not in g:
                    failures.append(f"{scheme}/{name}: grill drawing missing live values: {[k for k in ('<svg', '251°', '62%', 'F1 ', 'F3 171°') if k not in g]}")
                if "Grill connected" not in checks["topbar"] or "Wi-Fi" not in checks["topbar"]:
                    failures.append(f"{scheme}/{name}: status strip: {checks['topbar'][:160]!r}")
                # Uploading shrinks the photo to 960 px across first (a 3000 x 2000 test image here).
                up = fr.evaluate("""async () => {
                    const c = document.createElement('canvas'); c.width = 3000; c.height = 2000;
                    const x = c.getContext('2d'); for (let i = 0; i < 400; i++) { x.fillStyle = `hsl(${i*7},70%,50%)`; x.fillRect((i*37)%3000, (i*53)%2000, 120, 90); }
                    const big = await new Promise(r => c.toBlob(r, 'image/png'));
                    let sent = null; const keep = window.hdHA.api;
                    window.hdHA.api = (m, p, body) => { if (p === '/api/smoker/grill_photo' && m === 'POST') sent = body.get('photo'); return Promise.resolve({ url: '/api/smoker/grill_photo/image?v=1' }); };
                    const inp = { files: [new File([big], 'big.png', { type: 'image/png' })], value: 'x' };
                    await act.grillPhoto(inp); await new Promise(r => setTimeout(r, 300));
                    window.hdHA.api = keep; window.setGrillPhoto(null);
                    if (!sent) return 'nothing sent';
                    const bmp = await createImageBitmap(sent);
                    return [big.size, sent.size, sent.type, bmp.width, bmp.height]; }""")
                if not isinstance(up, list) or up[3] != 960 or up[1] >= up[0]:
                    failures.append(f"{scheme}/{name}: photo upload resize: {up}")
                pc = fr.inner_text("#photocard")
                if "Grill photo" not in pc or "Upload a photo" not in pc:
                    failures.append(f"{scheme}/{name}: grill photo card: {pc[:120]!r}")
                # Not connected: no "All good" beside "Grill not connected".
                nc = fr.evaluate("""async () => {
                    const st = window.parent.__smHass.states, k = 'binary_sensor.smoker_grill_connected', keep = st[k];
                    const ks = 'sensor.smoker_grill_link_status', keepS = st[ks];
                    st[k] = Object.assign({}, keep, {state: 'off'});
                    st[ks] = Object.assign({}, keepS, {state: 'Grill in range: reconnecting over Bluetooth'});
                    window.__smOnHass(); await new Promise(r => setTimeout(r, 400));
                    const t = document.getElementById('topbar').innerText; st[k] = keep; st[ks] = keepS; window.__smOnHass(); return t; }""")
                if "Grill not connected" not in nc or "All good" in nc or "reconnecting over Bluetooth" not in nc:
                    failures.append(f"{scheme}/{name}: not-connected strip: {nc!r}")
                cc = fr.inner_text("#controlcard")
                if "Bluetooth signal" not in cc or "-67 dBm · good" not in cc or "-44 dBm · strong" not in cc:
                    failures.append(f"{scheme}/{name}: signal rows: {cc[:300]!r}")
                # What's cooking: separate camera and library buttons (only the camera one opens the camera).
                sc = fr.evaluate("""() => [...document.querySelectorAll('#scancard input[type=file]')].map(i => [i.hasAttribute('capture'), i.multiple, i.closest('label') && i.closest('label').innerText.trim()])""")
                if sorted(sc) != sorted([[True, False, "Take a photo"], [False, True, "Choose photos"]]):
                    failures.append(f"{scheme}/{name}: scan inputs: {sc!r}")
                tb = fr.evaluate("async () => { window.__smOnHass(); await new Promise(r => setTimeout(r, 400)); return document.getElementById('topbar').innerText; }")
                if "Wi-Fi + Bluetooth" not in tb or fr.evaluate("document.querySelectorAll('#topbar .ic.via').length") != 2:
                    failures.append(f"{scheme}/{name}: both links at the top: {tb!r}")
                order = fr.evaluate("[...document.querySelectorAll('.sect')].map(e => e.id).join(',')")
                if order != "now,food,pit,charcoal,temps,ai,plan,journal-sec,setup":
                    failures.append(f"{scheme}/{name}: section order while cooking: {order}")
                idle = fr.evaluate("""async () => {
                    const hs = window.parent.__smHass, keep = hs.states, st = Object.assign({}, keep);
                    for (const k of Object.keys(st)) { const n = (st[k].attributes || {}).friendly_name || '';
                      if (n === 'Smoker Cook active') st[k] = Object.assign({}, st[k], {state: 'off'});
                      if (n === 'Smoker Program state') st[k] = Object.assign({}, st[k], {state: 'Idle'}); }
                    hs.states = st; window.__smOnHass(); await new Promise(r => setTimeout(r, 400));
                    const o = [...document.querySelectorAll('.sect')].map(e => e.id).join(',');
                    const bar = [...document.querySelectorAll('#secbar a')].map(a => a.getAttribute('href')).join(',');
                    hs.states = keep; window.__smOnHass(); await new Promise(r => setTimeout(r, 400)); return [o, bar]; }""")
                if not idle[0].startswith("plan,now,food") or not idle[1].startswith("#plan,#now"):
                    failures.append(f"{scheme}/{name}: idle order: {idle}")
                if "FOOD 1" in fr.inner_text("#kpis").upper():
                    failures.append(f"{scheme}/{name}: food repeated in Right now")
                sh = fr.evaluate("async () => { await loadJournal(true); renderShare(); return [document.getElementById('sharecard').innerText, document.getElementById('jshare').innerText]; }")
                if "Share my cooks" not in sh[0] or "42 shared cooks" not in sh[0] or "Share this cook?" not in sh[1] \
                        or "Pork shoulder · 8.5 lb · pit 250°F" not in sh[1] or "juicy, great bark" not in sh[1]:
                    failures.append(f"{scheme}/{name}: sharing: {sh!r}")
                taste = fr.evaluate("[...document.querySelectorAll('#jlist .taste button')].map(b => b.textContent)")
                if "juicy" not in taste or "overcooked" not in taste:
                    failures.append(f"{scheme}/{name}: how was it? tags: {taste!r}")
                okshare = fr.evaluate("window.hdHA.api('POST','/api/smoker/sharing/share/abc123def456').then(()=>'ok',e=>e.message)")
                if okshare != "ok":
                    failures.append(f"{scheme}/{name}: shim refused the share call: {okshare}")
                dg = fr.inner_text("#diag")
                if "controller 0.2.20" not in dg or "Controller Wi-Fi" not in dg or "not the grill" not in dg:
                    failures.append(f"{scheme}/{name}: diagnostics: {dg[:200]!r}")
                # Without the HA package: the AI, plan and recommendation cards say so instead of offering dead controls.
                np = fr.evaluate("""async () => {
                    const hs = window.parent.__smHass, keep = hs.states, st = Object.assign({}, keep);
                    hs.states = st;  // HA hands the page a new states object on every change
                    for (const k of Object.keys(st)) if (/^(input_|script\\.|timer\\.|automation\\.)/.test(k) || /Smoker (AI|recommendations|start cooking)/.test((st[k].attributes || {}).friendly_name || '')) delete st[k];
                    window.__smOnHass(); await new Promise(r => setTimeout(r, 400));
                    const out = { ai: document.getElementById('aicard').innerText, plan: document.getElementById('plancard').innerText,
                                  recs: document.getElementById('recs').innerText, toggles: document.querySelectorAll('#aicard .tg').length };
                    hs.states = keep; window.__smOnHass(); return out; }""")
                if (np["toggles"] or "isn't installed" not in np["ai"] or "isn't installed" not in np["plan"]
                        or "isn't installed" not in np["recs"]):
                    failures.append(f"{scheme}/{name}: no-package cards: {np!r}")
                # Photo mode: the readings are pinned on the user's own photo (a tiny synthetic image here).
                photo = fr.evaluate("""async () => {
                    const c = document.createElement('canvas'); c.width = 400; c.height = 292;
                    const x = c.getContext('2d'); x.fillStyle = '#888'; x.fillRect(0, 0, 400, 292);
                    window.setGrillPhoto(c.toDataURL('image/png'));
                    await new Promise(r => setTimeout(r, 300));
                    const g = document.getElementById('grillpic');
                    const r = { img: !!g.querySelector('.gphoto img'), pins: g.querySelectorAll('.pin').length, text: g.innerText };
                    window.setGrillPhoto(null); await new Promise(r => setTimeout(r, 300));
                    r.back = !!document.querySelector('#grillpic svg');
                    return r; }""")
                if not photo["img"] or photo["pins"] < 6 or "251" not in photo["text"] or "62%" not in photo["text"] or not photo["back"]:
                    failures.append(f"{scheme}/{name}: photo mode {photo}")
                if checks["secbar"] != ["Now", "Food", "Pit & program", "Charcoal", "Chart", "AI", "Plan", "Journal", "Setup"]:
                    failures.append(f"{scheme}/{name}: section bar {checks['secbar']}")
                if "Pork shoulder" not in checks["heronext"] or "Poultry" not in checks["heronext"]:
                    failures.append(f"{scheme}/{name}: coming up: {checks['heronext'][:160]!r}")
                # A food card's folded details stay open across a live redraw.
                opened = fr.evaluate("""async () => {
                    const d = document.querySelector('#probes details[data-k="more-food1"]'); if (!d) return 'missing';
                    if (d.open) return 'open by default'; d.open = true;
                    const st = window.parent.__smHass.states; const k = 'sensor.smoker_food_1_temperature';
                    st[k] = Object.assign({}, st[k], {state: String(parseFloat(st[k].state) + 1)});
                    window.parent.__smHass = Object.assign({}, window.parent.__smHass, {states: Object.assign({}, st)});
                    window.__smOnHass();
                    await new Promise(r => setTimeout(r, 600));
                    const d2 = document.querySelector('#probes details[data-k="more-food1"]');
                    return d2 && d2.open ? 'kept' : 'closed';
                }""")
                if opened != "kept":
                    failures.append(f"{scheme}/{name}: food card fold after redraw: {opened}")
                src = checks["sources"]
                if (src.count("<select") != 4 or 'value="sensor.example_probe" selected' not in src or "H5198 probe 4" not in src
                        or "Porch temperature" not in src or "example_probe_alarm" in src):
                    failures.append(f"{scheme}/{name}: probe sources: {src[:160]!r}")
                if src.count("chip exp") != 2:  # the H5198 note + Food 2 on a wired probe
                    failures.append(f"{scheme}/{name}: experimental chips in probe sources: {src.count('chip exp')}")
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
                if scheme == "light" and name == "phone":
                    failures += editor_on_phone(pg, fr)
                if scheme == "light" and name == "desktop":
                    fr.click("#pitcard .step .btn:last-child")
                    time.sleep(0.3)
                    calls = pg.evaluate("window.calls")
                    if not any(c[0] == "number" and c[1] == "set_value" and c[2]["value"] == 255 for c in calls):
                        failures.append(f"pit + did not call number.set_value 255: {calls}")
                    failures += program_editor(pg, fr)
                    # Typed text survives a live re-render of its section ("Edit as text").
                    set_program(pg, fr, FIXTURE_PROGRAM)
                    fr.click("#pe-totext")
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
                    # Setup is a page of its own: the section bar's Setup button shows it alone, Back returns.
                    fr.click('#secbar a[href="#setup"]'); time.sleep(0.3)
                    sv = fr.evaluate("[document.getElementById('setup').offsetParent !== null, document.getElementById('food').offsetParent === null]")
                    if sv != [True, True]:
                        failures.append(f"setup page: setup shown {sv[0]}, the cook hidden {sv[1]}")
                    if fr.evaluate("document.querySelectorAll('#setup h2.sec .grid, #setup h2.sec .tc').length"):
                        failures.append("setup page: the cards are inside the Setup heading (unclosed <h2>)")
                    fr.click("#setup h2.sec"); time.sleep(0.2)
                    if fr.evaluate("document.getElementById('setup').classList.contains('folded')"):
                        failures.append("setup page: tapping its title folded it away")
                    if fr.evaluate("document.activeElement && document.activeElement.closest('#setup') === null"):
                        failures.append("setup page: focus didn't move to it")
                    # Grill Wi-Fi setup (Setup → Connection): join saved network / scan press the controller's buttons.
                    fr.evaluate("document.querySelector('#controlcard details[data-k=wifi]').open = true")
                    if "Grill-Network" not in fr.inner_text("#controlcard"):
                        failures.append("grill wi-fi: networks the grill sees not shown")
                    fr.click("#controlcard details[data-k=wifi] button:has-text('Join saved network')"); time.sleep(0.3)
                    if not any(c[0] == "button" and c[2].get("entity_id") == "button.smoker_grill_wi_fi_join_saved_network"
                               for c in pg.evaluate("window.calls")):
                        failures.append("grill wi-fi: join saved network not pressed")
                    # Without the Smoker integration's API (e.g. inside home-dashboards before its shim allows it): no errors,
                    # the journal and scans explain what they need.
                    noapi = fr.evaluate("""async () => {
                        const keep = window.hdHA.api; delete window.hdHA.api;
                        try { journal.loaded = 0; await loadJournal(true); renderScan(true); render(); } catch (e) { return 'error: ' + e; }
                        const r = document.getElementById('jlist').innerText + ' | ' + document.getElementById('scancard').innerText;
                        window.hdHA.api = keep; return r; }""")
                    if "needs the Smoker integration" not in noapi:
                        failures.append(f"without the integration API: {noapi[:160]!r}")
                    # Restart needs a second tap.
                    btn = "#diag button"
                    fr.click(btn); time.sleep(0.2)
                    if any(c[0] == "button" and c[2].get("entity_id") == "button.smoker_restart" for c in pg.evaluate("window.calls")):
                        failures.append("restart pressed on the first tap")
                    if "Tap again" not in fr.inner_text("#diag"):
                        failures.append("restart did not ask for a second tap")
                    fr.click(btn); time.sleep(0.3)
                    if not any(c[0] == "button" and c[1] == "press" and c[2].get("entity_id") == "button.smoker_restart"
                               for c in pg.evaluate("window.calls")):
                        failures.append(f"restart not pressed after the second tap: {pg.evaluate('window.calls')[-2:]}")
                    fr.click("#setup .sect-back"); time.sleep(0.3)
                    failures += [f"{scheme}/{name}: {f}" for f in section_chips(fr)]
                    # The pit target sits in the top card: type it and Set, or + / −.
                    n0 = len(pg.evaluate("window.calls"))
                    fr.fill("#heropit", "260"); fr.click("#herotgt .btn.pri"); time.sleep(0.3)
                    fr.click('#herotgt [aria-label="Raise pit target"]'); time.sleep(0.3)
                    vals = [c[2].get("value") for c in pg.evaluate("window.calls")[n0:] if c[0] == "number" and c[2].get("entity_id") == "number.smoker_pit_target"]
                    if len(vals) != 2 or vals[0] != 260:
                        failures.append(f"{scheme}/{name}: top card pit target: {pg.evaluate('window.calls')[n0:]}")
                    n0 = len(pg.evaluate("window.calls"))
                    fr.click("#herotgt .btn.boost"); time.sleep(0.3)
                    if not any(c[0] == "switch" and c[1] == "turn_on" and c[2].get("entity_id") == "switch.smoker_boost" for c in pg.evaluate("window.calls")[n0:]):
                        failures.append(f"{scheme}/{name}: Boost didn't turn the boost switch on: {pg.evaluate('window.calls')[n0:]}")
                    fr.evaluate("window.scrollTo(0, 0)"); time.sleep(0.4)
                    lit = fr.evaluate("[...document.querySelectorAll('#secbar a[aria-current=true]')].map(a => a.innerText.trim())")
                    if "Setup" in lit:
                        failures.append(f"section bar marks Setup on the main page: {lit}")
                    if fr.evaluate("document.getElementById('setup').offsetParent !== null"):
                        failures.append("setup page: Back to the cook didn't leave it")
                    # The latest AI plan sits in the Plan card with the loaded program; Plan with AI says "Planning…".
                    ap = fr.evaluate("(document.getElementById('aiplanbox') || {}).textContent || ''")
                    if "about 11 h" not in ap or "Cook program" not in ap:
                        failures.append(f"AI plan box: {ap[:160]!r}")
                    fr.fill("#plantext", "8 lb pork butt for 6 pm")
                    if "Planning" not in fr.evaluate("document.activeElement.blur(), act.plan(), document.getElementById('plancard').textContent"):
                        failures.append("Plan with AI: no 'Planning…' while it works")
                    # The cook plan: dotted on the chart, in the legend, and "ahead of plan" on Food 1's card.
                    pl = fr.evaluate("[document.querySelectorAll('#chart path[stroke-dasharray=\"2 4\"]').length, document.getElementById('legend').textContent, document.getElementById('probes').textContent]")
                    if pl[0] < 1 or "Food 1 plan" not in pl[1] or "ahead of plan" not in pl[2]:
                        failures.append(f"cook plan: lines {pl[0]}, legend {pl[1][-80:]!r}, card has 'ahead of plan': {'ahead of plan' in pl[2]}")
                    # This cook vs your best: the 4-star pork shoulder in the journal, during this pork shoulder cook.
                    time.sleep(1.0)
                    bl = fr.evaluate("[getComputedStyle(document.getElementById('bestcard')).display, document.getElementById('bestline').textContent, document.querySelectorAll('#bestchart path').length]")
                    if bl[0] == "none" or "★★★★" not in bl[1] or bl[2] < 1:
                        failures.append(f"this cook vs your best: {bl}")
                    # One-page cook summary: opens with the facts and a chart; Close hides it.
                    fr.evaluate("act.summary('abc123def456')"); time.sleep(0.8)
                    sm = fr.evaluate("[!document.getElementById('summary').hidden, document.getElementById('summary').textContent]")
                    if not sm[0] or "Total" not in sm[1] or "Great bark" not in sm[1] or "Print or save as PDF" not in sm[1]:
                        failures.append(f"cook summary: {sm[1][:160]!r}")
                    fr.click("#summary .sum-tools button:has-text('Close')"); time.sleep(0.2)
                    if not fr.evaluate("document.getElementById('summary').hidden"):
                        failures.append("cook summary: Close didn't close it")
                    # Supplies: the Charcoal card shows the stock and the last cook; Bought a bag adds one bag.
                    if "Bought a bag" not in fr.inner_text("#fuelcard") or "3.1 kg" not in fr.inner_text("#fuelcard"):
                        failures.append(f"charcoal stock rows: {fr.inner_text('#fuelcard')[-200:]!r}")
                    fr.click("#fuelcard button:has-text('Bought a bag')"); time.sleep(0.3)
                    if not any(c[0] == "input_number" and c[2].get("entity_id") == "input_number.smoker_charcoal_stock_kg"
                               and abs(c[2].get("value", 0) - 21.5) < 0.01 for c in pg.evaluate("window.calls")):
                        failures.append(f"bought a bag: {[c for c in pg.evaluate('window.calls') if c[0] == 'input_number'][-2:]}")
                    sc = fr.evaluate("document.getElementById('supplycard').textContent")
                    if "due" not in sc or "Door gasket" not in sc:
                        failures.append(f"maintenance card: {sc[:200]!r}")
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
