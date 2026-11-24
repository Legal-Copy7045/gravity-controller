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
import re
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
    style = "<style>" + read("style.css") + "</style>\n"  # as panel.build_page (no web fonts)
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
    st("switch.smoker_turbo", "off", "Smoker Turbo"),
    st("binary_sensor.smoker_grill_on", "on", "Smoker Grill on"),
    st("button.smoker_turn_the_grill_off", "unknown", "Smoker Turn the grill off"),
    st("button.smoker_turn_the_grill_on", "unknown", "Smoker Turn the grill on"),
    st("sensor.smoker_grill_power", "", "Smoker Grill power"),
    st("number.smoker_timer", 0, "Smoker Timer", unit_of_measurement="min"),
    st("sensor.smoker_timer_remaining", 0, "Smoker Timer remaining", unit_of_measurement="s"),
    st("binary_sensor.smoker_grill_connected", "on", "Smoker Grill connected"),
    st("sensor.smoker_grill_link", "wifi", "Smoker Grill link"),
    st("sensor.smoker_grill_link_status", "Connected over Wi-Fi", "Smoker Grill link status"),
    st("sensor.smoker_release", "0.2.20", "Smoker Release"),
    st("binary_sensor.smoker_grill_on_wi_fi", "on", "Smoker Grill on Wi-Fi"),
    st("binary_sensor.smoker_grill_on_bluetooth", "on", "Smoker Grill on Bluetooth"),
    st("sensor.smoker_grill_bluetooth_signal", "-67", "Smoker Grill Bluetooth signal", unit_of_measurement="dBm"),
    st("sensor.smoker_grill_wi_fi_signal", "-44", "Smoker Grill Wi-Fi signal", unit_of_measurement="dBm"),
    st("binary_sensor.smoker_lid", "off", "Smoker Lid"),
    st("sensor.smoker_pit_stability", "Within 10°F of target 92% of the time · average 4°F off · lid opened 1 time (+12 min)", "Smoker Pit stability"),
    st("sensor.smoker_last_lid_opening", "Open 3 min; pit back after 9 min; about +12 min on the finish", "Smoker Last lid opening"),
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
    st("select.smoker_food_2_probe", "H5198 probe 1", "Smoker Food 2 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant"]),
    st("select.smoker_food_3_probe", "Home Assistant", "Smoker Food 3 probe", options=["Grill probe 1", "Grill probe 2", "H5198 probe 1", "H5198 probe 2", "H5198 probe 3", "H5198 probe 4", "Home Assistant"]),
    st("input_text.smoker_external_probe_3_entity", "sensor.example_probe", "Smoker external probe 3 entity"),
    st("sensor.example_probe", 171, "Example Probe", **F),
    st("sensor.example_probe_alarm", 203, "Example Probe alarm", **F),
    st("sensor.porch_temperature", 44, "Porch temperature", **F),
    st("binary_sensor.smoker_h5198_connected", "off", "Smoker H5198 connected"),
    st("sensor.smoker_food_3_estimate_basis", "Experimental (learning: 0 of 3 similar cooks). Poultry, 0 similar past cooks, "
       "grill factor 1.00; pull-at experimental (0 of 2 rests measured)", "Smoker Food 3 estimate basis"),
    st("sensor.smoker_food_3_pull_at", 170, "Smoker Food 3 pull at", **F),
    st("sensor.smoker_food_3_estimated_total_cook_time", 300, "Smoker Food 3 estimated total cook time", **MIN),
    st("number.smoker_food_3_weight", 3.5, "Smoker Food 3 weight", unit_of_measurement="lb"),
    # Food 4 has an estimate (it has a target) but no weight: not set up for this cook, so not in "Ready together".
    st("sensor.smoker_food_4_estimated_total_cook_time", 420, "Smoker Food 4 estimated total cook time", **MIN),
    st("input_number.smoker_rest_minutes", 45, "Smoker rest time", unit_of_measurement="min"),
    st("sensor.smoker_charcoal_estimate_basis", "Experimental: default burn rate for briquettes (learned from 0.0 of 3 kg).",
       "Smoker Charcoal estimate basis"),
    st("switch.smoker_control_over_bluetooth_experimental", "on", "Smoker Control over Bluetooth (experimental)"),
    st("button.smoker_restart", "unknown", "Smoker Restart"),
    st("switch.smoker_automatic_updates", "off", "Smoker Automatic updates"),
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
// A tiny photo (the journal's first photo goes on the cook's picture).
const PHOTO = Uint8Array.from(atob('%PHOTO%'), c => c.charCodeAt(0));
const JOURNAL = {
  entries: [{ id: 'fed987654321', started: Date.now() / 1000 - 86400 * 9 - 11 * 3600, ended: Date.now() / 1000 - 86400 * 9,
    probe: 'food1', probe_name: 'Food 1', profile: 'Pork shoulder', weight_kg: 4.1, wrapped: false, pit_c: 118, stall_h: 2.6,
    total_h: 11.0, ambient_c: 10, items: [{ name: 'Pork butt', weight_lb: 9 }], photos: ['20261113-180000-a1b2c3-0.jpg'], notes: '',
    rating: 3, tags: ['juicy', 'great bark'] },
    { id: 'abc123def456', started: Date.now() / 1000 - 86400 * 3 - 12 * 3600, ended: Date.now() / 1000 - 86400 * 3,
    probe: 'food1', probe_name: 'Food 1', profile: 'Pork shoulder', weight_kg: 3.8, wrapped: true, pit_c: 121, stall_h: 3.1,
    total_h: 11.6, ambient_c: 4, items: [{ name: 'Bone-in pork shoulder', weight_lb: 8.4 }], photos: [], notes: 'Great bark', rating: 4 }],
  draft: { items: [{ id: 'aa11bb22', name: 'Beef brisket (packer)', profile: 'Brisket', weight_lb: 14.2, barcode: '', notes: 'prime', probe: null }], photos: [] },
};
const SHARE = { enabled: true, auto: false, shared: 0, privacy: 'https://example.invalid/sharing',
  community: { cooks: 42, updated: '2026-11-23' },
  entries: [{ entry: 'abc123def456', status: 'pending', record: { v: 1, id: '0123456789abcdef0123456789abcdef', grill: 'gravity980',
    release: '0.2.25', season: 'autumn', cut: 'Pork shoulder', weight_lb: 8.5, wrapped: true, pit_f: 250, target_f: 203,
    stall_h: 3.1, total_h: 11.6, outside_f: 35, rating: 4, tags: ['juicy', 'great bark'] } }] };
// A cook's replay as the integration's replay.py answers: curves every few minutes, and the cook's events.
function replay(e) {
  const total = e.ended - e.started, step = 60 * Math.max(1, Math.ceil(total / 60 / 239)), n = Math.floor(total / step) + 1;
  const k = e.id === 'abc123def456' ? 0 : 1, pit = [], target = [], food = [], at = h => Math.round(e.started + h * 3600);
  for (let i = 0; i < n; i++) {
    const h = i * step / 3600; let f = 40 + 122 * (1 - Math.exp(-h / (2 + 0.6 * k)));
    if (h > 6.2) f = Math.min(203, 158 + (h - 6.2) * 9);
    pit.push(Math.round((250 - 8 * k + 5 * Math.sin(h * 1.5 + k)) * 10) / 10); target.push(h < 6 ? 250 : 275); food.push(i % 23 ? Math.round(f * 10) / 10 : null);
  }
  return { v: 1, start: Math.round(e.started), end: Math.round(e.ended), step, unit: '°F', slot: 1, pit, target, food, kept: true,
    events: [{ t: at(0.8), k: 'lid', d: 140 }, { t: at(3.1), k: 'stall_start', slot: 1 }, { t: at(4.4), k: 'fuel', v: 80 },
      { t: at(6.0), k: 'wrap', slot: 1 }, { t: at(6.0), k: 'step', v: 2 }, { t: at(6.2), k: 'stall_end', slot: 1 },
      { t: at(e.total_h - 0.1), k: 'pulled', slot: 1 }] };
}
window.__smHass = {
  fetchWithAuth: (path, opt) => { window.calls.push(['api', path, opt && opt.method]);
    if (path.startsWith('/api/smoker/photo/')) return Promise.resolve(new Response(new Blob([PHOTO], { type: 'image/png' }), { headers: { 'Content-Type': 'image/png' } }));
    const rp = new RegExp('^/api/smoker/journal/([0-9a-f]+)/replay$').exec(path), re = rp && JOURNAL.entries.find(x => x.id === rp[1]);
    if (re) return Promise.resolve(new Response(JSON.stringify(replay(re)), { headers: { 'Content-Type': 'application/json' } }));
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
    for name in ("cook program editor", "page sections", "cook plan", "serve together", "cook replay"):
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
    """The step editor in Cook → Build the cook → Build it yourself."""
    fails = []
    fr.evaluate("document.activeElement && document.activeElement.blur()")
    # A program is loaded (and running): "Build it yourself" is the tab shown.
    if fr.evaluate("document.getElementById('ctab-build').getAttribute('aria-selected')") != "true" or not fr.is_visible("#progedit"):
        fails.append("program editor: Build it yourself not shown while a program is loaded")
        fr.click("#ctab-build")
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
    # Presets: text -> steps -> text is stable, through the page (the controller's text changes as after a preset),
    # keep (hold mode) and turbo included.
    ps = presets()
    if not any(re.search(r"\bkeep food\d", t) for t in ps) or not any("turbo on" in t for t in ps):
        fails.append("editor: expected keep and turbo presets in firmware/base.yaml")
    for t in ps:
        set_program(pg, fr, t)
        if editor_text(fr) != t or fr.locator("#progedit .pe-step").count() != t.count(";"):
            fails.append(f"editor: preset not shown as steps or changed: {t!r} -> {editor_text(fr)!r}")
        fr.click("#pe-totext")
        if fr.input_value("#progtext") != t:
            fails.append(f"editor: Edit as text changed the preset: {fr.input_value('#progtext')!r}")
        fr.click("#pe-tosteps")
        if editor_text(fr) != t or fr.locator("#progedit .pe-step").count() != t.count(";"):
            fails.append(f"editor: back to steps changed the preset: {editor_text(fr)!r}")
    fails += keep_turbo_notify(pg, fr)
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


def step_fields(fr):
    return fr.evaluate("""() => [...document.querySelectorAll('#progedit .pe-step')].map(li => [li.querySelector('[data-pe=kind]').value,
        (li.querySelector('[data-pe=temp]') || {}).value || '', !!(li.querySelector('[data-pe=turbo]') || {}).checked,
        (li.querySelector('[data-pe=done]') || {}).value || '', (li.querySelector('[data-pe=kprobe]') || {}).value || ''])""")


def keep_turbo_notify(pg, fr):
    """Keep (hold mode), Turbo per step and a notification when a step ends: shown as steps, and text <-> steps exact."""
    fails = []
    kt = 'name: Sear; pit 700 turbo on until food1 >= 125 notify "Pull it"; keep food2 140'
    set_program(pg, fr, kt)
    # (Turbo stays on into the keep step: the text turns it off only where it says so)
    if step_fields(fr) != [["pit", "700", True, "Pull it", ""], ["keep", "140", True, "", "2"]] or editor_text(fr) != kt:
        fails.append(f"keep/turbo: as steps {step_fields(fr)} -> {editor_text(fr)!r}")
    if "Keep food at" not in fr.inner_text("#pe-s1-kind") or "Turbo (full fan)" not in fr.inner_text("#progedit .pe-step"):
        fails.append("keep/turbo: the step kind or the Turbo box isn't labelled")
    fr.uncheck("#pe-s0-turbo")
    fr.check("#pe-s1-turbo")
    if editor_text(fr) != 'name: Sear; pit 700 until food1 >= 125 notify "Pull it"; keep food2 140 turbo on':
        fails.append(f"keep/turbo: Turbo moved to the keep step {editor_text(fr)!r}")
    fr.check("#pe-s0-turbo")
    fr.uncheck("#pe-s1-turbo")
    fr.fill("#pe-s0-done", "Pull it now")
    fr.select_option("#pe-s1-kp", "1")
    fr.fill("#pe-s1-temp", "150")
    fr.evaluate("document.activeElement.blur()")
    want = 'name: Sear; pit 700 turbo on until food1 >= 125 notify "Pull it now"; keep food1 150 turbo off'
    if editor_text(fr) != want:
        fails.append(f"keep/turbo: edited {editor_text(fr)!r}")
    # The text it writes reads back the same (Edit as text, then back to steps).
    fr.click("#pe-totext")
    if fr.input_value("#progtext") != want:
        fails.append(f"keep/turbo: as text {fr.input_value('#progtext')!r}")
    fr.click("#pe-tosteps")
    if editor_text(fr) != want or step_fields(fr)[1] != ["keep", "150", False, "", "1"]:
        fails.append(f"keep/turbo: back to steps {step_fields(fr)}")
    # A keep step must be last; a new step goes before it.
    fr.click("#pe-addstep")
    if step_fields(fr)[2][0] != "keep" or step_fields(fr)[1][0] != "pit":
        fails.append(f"keep/turbo: a new step should go before the keep step {step_fields(fr)}")
    fr.click("#pe-s2-up")
    errs = fr.inner_text("#progedit .pe-errs") if fr.locator("#progedit .pe-errs").count() else ""
    if '"Keep food at" must be the last step' not in errs:
        fails.append(f"keep/turbo: keep not last not flagged: {errs!r}")
    fr.evaluate("progEd.state.touched = false; progEd.state.sent = null; document.activeElement && document.activeElement.blur()")
    # Text the editor can't show as steps (a repeated turbo): text, unchanged.
    set_program(pg, fr, "pit 250 turbo on until after 1h; pit 275 turbo on")
    if fr.locator("#progtext").count() != 1 or fr.input_value("#progtext") != "pit 250 turbo on until after 1h; pit 275 turbo on":
        fails.append("keep/turbo: a repeated 'turbo on' should open as text, unchanged")
    fr.evaluate("progEd.state.touched = false; progEd.state.userText = false")
    set_program(pg, fr, FIXTURE_PROGRAM)
    return fails


def hero_and_cook(pg, fr):
    """The header carries what "Pit & program" had (lid, held steady, last lid opening, the program's state and status);
    that section and Plan are gone; Cook has what's cooking, Plan with AI / Build it yourself and When."""
    fails = []
    if fr.locator("[data-sect=pit], [data-sect=plan], #pitcard, #secbar a[href='#plan']").count():
        fails.append("the old Pit & program / Plan sections are still on the page")
    hf = fr.inner_text("#herofacts")
    if "Held steady" not in hf or "Within 10°F of target 92%" not in hf or "Last lid opening" not in hf or "Open 3 min" not in hf:
        fails.append(f"header: held steady / last lid opening {hf!r}")
    if "Program running" not in fr.inner_text("#chips") or "Step " not in fr.inner_text("#gstatus"):
        fails.append(f"header: program state/status {fr.inner_text('#chips')!r} {fr.inner_text('#gstatus')!r}")
    if "Lid open" in fr.inner_text("#chips"):
        fails.append("header: lid open while it's closed")
    set_state(pg, "binary_sensor.smoker_lid", "on")
    if "Lid open" not in fr.inner_text("#chips"):
        fails.append("header: no Lid open chip")
    set_state(pg, "binary_sensor.smoker_lid", "off")
    # What's cooking: one row per food, with its probe, protein and weight.
    slots = fr.evaluate("[...document.querySelectorAll('#scancard .slot')].map(e => e.innerText.replace(/\\s+/g, ' '))")
    if len(slots) != 2 or "Food 1" not in slots[0] or "Grill probe 1" not in slots[0] or "Food 3" not in slots[1] or "Home Assistant" not in slots[1]:
        fails.append(f"what's cooking: slots {slots}")
    if fr.evaluate("document.querySelector('#scancard .slot select').value") != "Pork shoulder":
        fails.append("what's cooking: Food 1's protein not shown")
    n0 = len(pg.evaluate("window.calls"))
    fr.evaluate("""() => { const i = document.querySelector('#scancard .slot input[type=number]'); i.value = '9'; i.dispatchEvent(new Event('change', {bubbles: true})); }""")
    time.sleep(0.3)
    if not any(c[0] == "number" and c[2].get("entity_id") == "number.smoker_food_1_weight" and c[2].get("value") == 9 for c in pg.evaluate("window.calls")[n0:]):
        fails.append("what's cooking: the weight isn't set")
    # Build the cook: Plan with AI and Build it yourself are tabs over one stages list.
    fr.click("#ctab-ai")
    if not fr.is_visible("#plantext") or fr.is_visible("#progedit") or fr.evaluate("document.getElementById('ctab-ai').getAttribute('aria-selected')") != "true":
        fails.append("build the cook: the Plan with AI tab doesn't show the request box")
    fr.click("#aiplanbox button:has-text('Edit the stages')")
    time.sleep(0.2)
    if not fr.is_visible("#progedit") or fr.locator("#progedit .pe-step").count() != 3 or fr.is_visible("#plantext"):
        fails.append(f"build the cook: Edit the stages didn't open the program as steps ({fr.locator('#progedit .pe-step').count()})")
    if fr.locator("#progbtns button:has-text('Start')").count() != 1 or "Pork shoulder (Texas crutch)" not in fr.inner_text("#progpreset"):
        fails.append("build the cook: run buttons or presets missing")
    w = fr.inner_text("#plancard")
    if "Serve by" not in w or "Light the grill by" not in w or "Slice when" not in w or "Rest timer" not in w:
        fails.append(f"when: {w[:200]!r}")
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
    if fr.evaluate("document.querySelector('[data-sect=cook]').offsetParent === null"):
        fails.append("advanced mode: Cook still hidden")
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


def tiny_png(w=64, h=48, rgb=(200, 120, 80)):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def set_state(pg, eid, state):
    pg.evaluate("""([k, v]) => { const st = window.__smHass.states;
        st[k] = Object.assign({}, st[k], {state: v});
        window.__smHass = Object.assign({}, window.__smHass, {states: Object.assign({}, st)});
        document.getElementById('f').contentWindow.__smOnHass(); }""", [eid, state])
    time.sleep(0.5)


def serve_together(pg, fr, tag):
    """Plan: with a serve time, when each food goes on (and when to light the grill) so everything is ready together."""
    fails = []
    keep = STATES["input_datetime.smoker_serve_time"]["state"]
    set_state(pg, "input_datetime.smoker_serve_time", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + 14 * 3600)))
    steps = fr.evaluate("[...document.querySelectorAll('#plancard .stt li .stt-w')].map(e => e.textContent)")
    if steps != ["Light the grill", "Pork shoulder on", "Poultry on", "Serve"]:
        fails.append(f"serve together: steps {steps}")
    # Minutes before the serve time: the light-up 45 min before the first; each food its estimate plus the 45 min rest.
    mins = fr.evaluate("""(() => { const p = servePlan(val(byName('Smoker serve by', ['input_datetime'])));
        return [p.light, ...p.foods.map(f => f.on)].map(t => Math.round((p.serve - t) / 60000)); })()""")
    if mins != [760 + 45 + 45, 760 + 45, 300 + 45]:
        fails.append(f"serve together: minutes before serving {mins}")
    line = fr.evaluate("serveLine(servePlan(val(byName('Smoker serve by', ['input_datetime']))))")
    if not (" light the grill · " in line and " pork shoulder on · " in line and " poultry on · " in line and line.endswith(" serve")):
        fails.append(f"serve together: one line {line!r}")
    txt = fr.inner_text("#plancard")
    if "Ready together" not in txt or "when each food should go on" not in txt or "5 h on the grill, 45 min rest" not in txt:
        fails.append(f"serve together: card text {txt[-300:]!r}")
    wide = fr.evaluate("""() => [...document.querySelectorAll('#plancard .stt *')].filter(e => e.getBoundingClientRect().right >
        document.getElementById('plancard').getBoundingClientRect().right + 1).length""")
    if wide:
        fails.append(f"serve together: {wide} parts of the timeline stick out of the card")
    if EDITOR_SHOTS:
        fr.locator("#plancard").screenshot(path=os.path.join(EDITOR_SHOTS, f"ha-serve-{tag}.png"))
    set_state(pg, "input_datetime.smoker_serve_time", keep)
    if fr.locator("#plancard .stt").count():
        fails.append("serve together: still shown with the serve time in the past")
    return fails


def replay_and_picture(pg, fr, tag, dark):
    """Journal: replay a cook (curves, scrubber, play, events, compare) and its picture (PNG) to share."""
    fails = []
    fr.evaluate("document.querySelector('[data-act=replay][data-a=abc123def456]').click()")
    try:
        fr.wait_for_selector("#rp:not([hidden]) #rp-chart svg", timeout=6000)
    except Exception:
        return [f"replay didn't open ({fr.inner_text('#toast')!r})"]
    if fr.locator("#rp-chart svg path").count() < 3:
        fails.append("replay: pit, pit target and food curves not drawn")
    evs = fr.inner_text("#rp-evs")
    for w in ("Lid open 2 min", "Stall began (Food 1)", "Charcoal topped up to 80%", "Wrapped (Food 1)", "Program step 2",
              "Stall ended (Food 1)", "Off the grill (Food 1)"):
        if w not in evs:
            fails.append(f"replay: event {w!r} missing from {evs!r}")
    if fr.locator("#rp-chart .rp-mk").count() != 7 or fr.locator("#rp-chart svg rect").count() < 1:
        fails.append("replay: a marker for each event and the stall shaded")
    cy = fr.evaluate("[...document.querySelectorAll('#rp-chart .rp-mk circle')].map(c => c.getAttribute('cy') + ':' + Math.round(c.getAttribute('cx')))")
    if len(set(cy)) != len(cy):
        fails.append(f"replay: event markers drawn on top of each other {cy}")
    # (the fixture's cook ran 12 h from start to end)
    fr.evaluate("() => { const r = document.getElementById('rp-pos'); r.value = 250; r.dispatchEvent(new Event('input', { bubbles: true })); }")
    rd = fr.inner_text("#rp-read")
    if not (rd.startswith("3 h 00 min in") and "Latest: Lid open 2 min, 2 h 12 min before" in rd and "Pit 2" in rd and "Pit target 250°F" in rd and "Food 1 1" in rd):
        fails.append(f"replay: the scrubber's readout {rd!r}")
    fr.click("#rp-evs button:has-text('Stall began')")
    if not fr.inner_text("#rp-read").startswith("3 h 06 min in") or "Latest: Stall began (Food 1)" not in fr.inner_text("#rp-read"):
        fails.append(f"replay: an event jumps there ({fr.inner_text('#rp-read')[:80]!r})")
    fr.click("#rp-play")
    time.sleep(0.8)
    st = fr.evaluate("RP.state().pos")
    if not 0.26 < st < 0.5 or fr.inner_text("#rp-play") != "Pause":
        fails.append(f"replay: Play from 3 h 06 min ({st:.3f}, {fr.inner_text('#rp-play')!r})")
    fr.click("#rp-play")
    fr.select_option("#rp-cmp", "fed987654321")
    try:
        fr.wait_for_function("RP.state().cmp === 'fed987654321'", timeout=4000)
    except Exception:
        fails.append("replay: compare didn't load the other cook")
    if fr.locator("#rp-chart svg path[stroke-dasharray='6 5']").count() < 2 or "Other food 1" not in fr.inner_text("#rp-read"):
        fails.append("replay: the other cook isn't overlaid (dashed), or its temperature not shown")
    if fr.evaluate("(() => { const d = document.getElementById('rp'); return d.scrollWidth - d.clientWidth; })()") > 1:
        fails.append("replay: wider than the screen")
    pg.screenshot(path=os.path.join(OUT, f"replay-{tag}.png"))
    # Share image from the replay: no Web Share in this browser, so a download.
    with pg.expect_download(timeout=15000) as dl:
        fr.click("#rp [data-rp=png]")
    data = open(dl.value.path(), "rb").read()
    import struct
    if data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != (1080, 1350):
        fails.append("Share image: not a 1080 x 1350 PNG")
    fr.press("#rp-play", "Escape")
    if not fr.evaluate("document.getElementById('rp').hidden"):
        fails.append("replay: Escape didn't close it")
    # The picture of the earlier cook (it has a photo): the page's colours, the photo on it, the stars.
    info = fr.evaluate("""async () => { const c = await replayCook('fed987654321'), b = await RP.png(c), i = await createImageBitmap(b);
        const cv = document.createElement('canvas'); cv.width = i.width; cv.height = i.height; const x = cv.getContext('2d'); x.drawImage(i, 0, 0);
        const px = (a, y) => [...x.getImageData(a, y, 1, 1).data].slice(0, 3);
        return { w: i.width, h: i.height, type: b.type, photo: !!c.photo && c.photo.startsWith('blob:'), bg: px(20, 1000), mid: px(540, 480) }; }""")
    bg = [19, 27, 36] if dark else [255, 255, 255]
    if info["w"] != 1080 or info["h"] != 1350 or info["type"] != "image/png" or not info["photo"] or info["bg"] != bg \
            or max(abs(a - b) for a, b in zip(info["mid"], (200, 120, 80))) > 6:
        fails.append(f"the cook's picture: {info}")
    with pg.expect_download(timeout=15000) as dl:
        fr.evaluate("document.querySelector('[data-act=shareImg][data-a=fed987654321]').click()")
    open(os.path.join(OUT, f"cook-card-{tag}.png"), "wb").write(open(dl.value.path(), "rb").read())
    return fails


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(OUT, exist_ok=True)
    page_html = build_page()
    import base64
    harness = HARNESS.replace("%STATES%", json.dumps(STATES)).replace("%PHOTO%", base64.b64encode(tiny_png()).decode()) \
        .replace("%PAGE%", json.dumps(page_html).replace("</", "<\\/"))
    hp = os.path.join(OUT, "harness.html")
    open(hp, "w").write(harness)
    failures = []
    if not shared_blocks_match():
        failures.append("the shared blocks (program editor, page sections, cook plan, serve together, cook replay) in page.html and ui.js differ")
    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome")
        b = p.chromium.launch(executable_path=exe) if os.path.exists(exe) else p.chromium.launch()
        for scheme in ["light", "dark"]:
            for name, vp in [("desktop", {"width": 1280, "height": 1900}), ("phone", {"width": 390, "height": 2600})]:
                ctx = b.new_context(viewport=vp, color_scheme=scheme, device_scale_factor=1)
                ctx.add_init_script("try { localStorage.getItem('smoker-mode') || localStorage.setItem('smoker-mode', 'advanced'); } catch (e) {}")  # Advanced (the checks below are for it); basic_mode() tests Basic
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
                    "controlcard": fr.inner_text("#controlcard"),
                    "diag": fr.inner_html("#diag"),
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
                if "the app controls it" not in checks["topbar"] or "Controlling the grill over Wi-Fi" not in checks["controlcard"]:
                    failures.append(f"{scheme}/{name}: control row: {checks['topbar'][:200]!r}")
                if "Automatic updates" not in checks["diag"] or 'data-a="switch.smoker_automatic_updates"' not in checks["diag"]:
                    failures.append(f"{scheme}/{name}: no Automatic updates toggle in the controller card")
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
                    window.hdHA.api = (m, p, body) => { if (p === '/api/smoker/grill_photo' && m === 'POST') sent = body.get('photo'); return Promise.resolve({ url: '/api/smoker/grill_photo/image/0123456789abcdef0123456789abcdef?v=1' }); };
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
                if order != "now,food,cook,charcoal,temps,ai,journal-sec,setup":
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
                if not idle[0].startswith("cook,now,food,charcoal") or not idle[1].startswith("#cook,#now,#food,#charcoal"):
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
                if checks["secbar"] != ["Now", "Food", "Cook", "Charcoal", "Chart", "AI", "Journal", "Setup"]:
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
                if src.count("chip exp") != 1:  # the H5198 note
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
                    fr.click('#herotgt [aria-label="Raise pit target"]')
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
                    failures += [f"{scheme}/{name}: {f}" for f in basic_mode(fr)]
                    # The timer: minutes and Start set the controller's Timer.
                    n0 = len(pg.evaluate("window.calls"))
                    fr.fill("#timerin", "45"); fr.click(".timer .btn.pri"); time.sleep(0.3)
                    if not any(c[0] == "number" and c[2].get("entity_id") == "number.smoker_timer" and c[2].get("value") == 45 for c in pg.evaluate("window.calls")[n0:]):
                        failures.append(f"{scheme}/{name}: timer start: {pg.evaluate('window.calls')[n0:]}")
                    # The pit target sits in the top card: type it and Set, or + / −.
                    n0 = len(pg.evaluate("window.calls"))
                    fr.fill("#heropit", "260"); fr.click("#herotgt .btn.pri"); time.sleep(0.3)
                    fr.click('#herotgt [aria-label="Raise pit target"]'); time.sleep(0.3)
                    vals = [c[2].get("value") for c in pg.evaluate("window.calls")[n0:] if c[0] == "number" and c[2].get("entity_id") == "number.smoker_pit_target"]
                    if len(vals) != 2 or vals[0] != 260:
                        failures.append(f"{scheme}/{name}: top card pit target: {pg.evaluate('window.calls')[n0:]}")
                    # Turbo, and power never on one tap: the first tap arms (one press), the second does it (another).
                    n0 = len(pg.evaluate("window.calls"))
                    fr.click('#herotgt button[onclick="act.turbo()"]'); time.sleep(0.3)
                    if not any(c[0] == "switch" and c[1] == "turn_on" and c[2].get("entity_id") == "switch.smoker_turbo" for c in pg.evaluate("window.calls")[n0:]):
                        failures.append(f"{scheme}/{name}: Turbo didn't turn the turbo switch on")
                    n0 = len(pg.evaluate("window.calls"))
                    fr.click("#herotgt .btn.power"); time.sleep(0.3)
                    presses = lambda: [c for c in pg.evaluate("window.calls")[n0:] if c[0] == "button" and c[2].get("entity_id") == "button.smoker_turn_the_grill_off"]
                    if len(presses()) != 1 or "Tap again" not in fr.inner_text("#herotgt .btn.power"):
                        failures.append(f"{scheme}/{name}: power off's first tap should arm it: {presses()} {fr.inner_text('#herotgt .btn.power')!r}")
                    fr.click("#herotgt .btn.power"); time.sleep(0.3)
                    if len(presses()) != 2:
                        failures.append(f"{scheme}/{name}: power off's second tap should press again: {presses()}")
                    fr.evaluate("window.scrollTo(0, 0)"); time.sleep(0.4)
                    lit = fr.evaluate("[...document.querySelectorAll('#secbar a[aria-current=true]')].map(a => a.innerText.trim())")
                    if "Setup" in lit:
                        failures.append(f"section bar marks Setup on the main page: {lit}")
                    if fr.evaluate("document.getElementById('setup').offsetParent !== null"):
                        failures.append("setup page: Back to the cook didn't leave it")
                    # The latest AI plan sits in the Plan card with the loaded program; Plan with AI says "Planning…".
                    ap = fr.evaluate("(document.getElementById('aiplanbox') || {}).textContent || ''")
                    if "about 11 h" not in ap or "Edit the stages" not in ap:
                        failures.append(f"AI plan box: {ap[:160]!r}")
                    fr.click("#ctab-ai")
                    fr.fill("#plantext", "8 lb pork butt for 6 pm")
                    if "Planning" not in fr.evaluate("document.activeElement.blur(), act.plan(), document.getElementById('cookai').textContent"):
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
                    # (through the page's delegated handler: buttons carry the cook's id in data-a, not in an onclick)
                    if not fr.evaluate("""(() => { const b = document.querySelector('[data-act="summary"][data-a="abc123def456"]');
                            if (!b) return false; b.click(); return true; })()"""):
                        failures.append("cook summary: no Summary button with the cook's id in data-a")
                    time.sleep(0.8)
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
                n_err = len(errors)
                failures += [f"{scheme}/{name}: {f}" for f in hero_and_cook(pg, fr)]
                failures += [f"{scheme}/{name}: {f}" for f in serve_together(pg, fr, f"{name}-{scheme}")]
                failures += [f"{scheme}/{name}: {f}" for f in replay_and_picture(pg, fr, f"{name}-{scheme}", scheme == "dark")]
                if errors[n_err:]:
                    failures.append(f"{scheme}/{name}: JS errors in the header/Cook checks, serve together or replay {errors[n_err:]}")
                ctx.close()
        b.close()
    for f in failures:
        print("FAIL", f)
    print(f"screenshots in {OUT}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
