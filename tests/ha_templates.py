#!/usr/bin/env python3
"""Render the package's trickiest templates with Home Assistant's own engine (runtime check that
check_config can't do): the probe-key mapping in notification buttons, the buttons list, recommendation parsing."""

import asyncio
import os
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!include_dir_named", lambda l, n: {})


async def main():
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.template import Template
    from homeassistant.helpers import template as tmod

    d = tempfile.mkdtemp()
    hass = HomeAssistant(d)
    await hass.async_start()
    pkg = yaml.load(open(os.path.join(ROOT, "homeassistant/packages/smoker.yaml")), Loader=Loader)
    autos = {a["id"]: a for a in pkg["automation"]}

    def render(src, **vars_):
        return Template(src, hass).async_render(vars_)

    def render_dict(d):
        return d if isinstance(d, dict) else render(d)

    # 1. probe key mapping used by the notification buttons
    seq = next(st for st in autos["smoker_notification_actions"]["actions"] if "choose" in st)["choose"]
    plus = next(c for c in seq if "FOOD_PLUS_5" in str(c["conditions"]))["sequence"][0]["variables"]["key"]
    for a, want in [("SMOKER_FOOD_PLUS_5_FOOD1", "food_1"), ("SMOKER_FOOD_PLUS_5_FOOD3", "food_3")]:
        got = render(plus, a=a)
        check(got == want, f"button key {a} -> {got!r}")
    wrap = next(c for c in seq if "WRAPPED" in str(c["conditions"]))["sequence"][0]["target"]["entity_id"]
    got = render(wrap, a="SMOKER_WRAPPED_FOOD2")
    check(got == "switch.smoker_food_2_wrapped", f"wrapped entity -> {got!r}")

    # 1b. external probe mapping: follows the named entity and converts °C sources to °F
    tsens = [x for blk in pkg["template"] if "sensor" in blk for x in blk["sensor"]]
    ext3 = next(x for x in tsens if x.get("unique_id") == "smoker_external_probe_3")["state"]
    hass.states.async_set("input_text.smoker_external_probe_3_entity", "sensor.probe_c")
    hass.states.async_set("sensor.probe_c", "60", {"unit_of_measurement": "°C"})
    got = render(ext3)
    check(float(got) == 140.0, f"external probe in °C -> {got!r} °F")
    hass.states.async_set("sensor.probe_c", "151.5", {"unit_of_measurement": "°F"})
    check(float(render(ext3)) == 151.5, "external probe in °F passes through")
    hass.states.async_set("input_text.smoker_external_probe_3_entity", "")
    check(render(ext3) is None or str(render(ext3)) in ("None", ""), f"no entity -> {render(ext3)!r}")

    # 1c. slots 3-6 default to the Govee H5198's probes 1-4; the probe's own alarm is the slot's target
    tgt3 = next(x for x in tsens if x.get("unique_id") == "smoker_external_probe_3_target")["state"]
    hass.states.async_set("input_text.smoker_external_probe_3_entity", "")
    hass.states.async_set("sensor.meat_thermometer_temperature_probe_1", "151.0", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.meat_thermometer_temperature_alarm_probe_1", "203.0", {"unit_of_measurement": "°F"})
    check(float(render(ext3)) == 151.0, f"slot 3 default -> {render(ext3)!r}")
    check(float(render(tgt3)) == 203.0, f"slot 3 target from the probe's alarm -> {render(tgt3)!r}")
    hass.states.async_set("sensor.meat_thermometer_temperature_alarm_probe_1", "32.0", {"unit_of_measurement": "°F"})
    check(str(render(tgt3)) in ("None", ""), f"alarm not set (0 C) -> no target: {render(tgt3)!r}")
    ext1 = next(x for x in tsens if x.get("unique_id") == "smoker_external_probe_1")["state"]
    hass.states.async_set("input_text.smoker_external_probe_1_entity", "")
    check(str(render(ext1)) in ("None", ""), f"slot 1 has no default -> {render(ext1)!r}")

    # 2. buttons variable renders to a real list
    fwd = autos["smoker_forward_notifications"]["actions"][0]["variables"]
    class Ev:  # minimal trigger.event
        def __init__(self, title, tag):
            self.data = {"title": title, "tag": tag}
    for title, tag, n in [("Food 1 is done", "done_food1", 2), ("Pit temperature off", "pit_band", 2),
                          ("Program paused", "program", 1), ("Controller restarted", "program", 1),
                          ("Food 6 stall", "stall_food6", 1), ("Food 1 stall over", "stall_food1", 0),
                          ("Still keeping the food warm", "program", 0)]:
        b = render(fwd["buttons"], tag=tag, trigger={"event": Ev(title, tag)})
        check(isinstance(b, list) and len(b) == n, f"buttons for {title!r}: {b!r}")

    # 2b. a tag that isn't exactly done_/pull_/stall_ + food1-6 names no probe (no JSON pasting of the tag)
    for tag in ['done_food1"}, {"action": "SMOKER_START_PROGRAM', "done_food9", "pull_FOOD1x", "stall_"]:
        b = render(fwd["buttons"], tag=tag, trigger={"event": Ev("Food 1 stall", tag)})
        check(isinstance(b, list) and not any("FOOD" in x["action"] or "START" in x["action"] for x in b),
              f"odd tag {tag!r} -> {b!r}")
    b = render(fwd["buttons"], tag="pull_food2", trigger={"event": Ev("Pull it", "pull_food2")})
    check(b[0]["action"] == "SMOKER_PULLED_FOOD2", f"pull button -> {b!r}")

    # 2c. smoker_notify: SMOKER_ buttons get the notification's one-off code, other buttons are left alone
    nv = pkg["script"]["smoker_notify"]["sequence"][0]["variables"]
    code = render(nv["code"])
    check(isinstance(code, str) and len(code) == 24 and code.isalnum() and code[0].isalpha() and code.isascii()
          and code != render(nv["code"]), f"notification code {code!r}")
    given = [{"action": "SMOKER_PIT_HOLD", "title": "Hold"}, {"action": "URI", "title": "Open", "uri": "/x"}]
    b = render(nv["buttons"], actions=given, code=code)
    check(b["ours"] and b["list"][0]["action"] == "SMOKER_PIT_HOLD__" + code and b["list"][1]["action"] == "URI",
          f"coded buttons {b!r}")
    check(b["tags"] == "PH", f"coded buttons remember their actions: {b['tags']!r}")
    b = render(nv["buttons"], code=code, actions=[{"action": "SMOKER_FOOD_PLUS_5_FOOD3"}, {"action": "SMOKER_WRAPPED_FOOD6"},
                                                   {"action": "SMOKER_START_PROGRAM"}])
    check(b["tags"] == "F3W6SP", f"food buttons remember their actions: {b['tags']!r}")
    b = render(nv["buttons"], code=code)
    check(b["list"] == [] and not b["ours"], "no buttons -> nothing to remember")

    # 2d. a button counts only with a code remembered in the last 2 hours
    cond = autos["smoker_notification_actions"]["conditions"][0]["value_template"]
    import time as _t
    now_s = int(_t.time())
    A, B, C = "a" * 23 + "1", "B" * 23 + "2", "c" * 24
    hass.states.async_set("input_text.smoker_notify_codes", f"{A}:{now_s - 8000}:SP {B}:{now_s - 60}:SPPH")
    for action, want in [("SMOKER_START_PROGRAM__" + B, True), ("SMOKER_START_PROGRAM__" + A, False),
                         ("SMOKER_PIT_HOLD__" + B, True),
                         # A code works only for the buttons its notification carried.
                         ("SMOKER_PIT_PLUS_25__" + B, False), ("SMOKER_FUEL_FULL__" + B, False),
                         ("SMOKER_START_PROGRAM", False), ("SMOKER_START_PROGRAM__" + C, False),
                         ("SMOKER_START_PROGRAM__" + B.lower(), False), ("SMOKER_START_PROGRAM__" + B[:16], False),
                         ("OTHER__" + B, False), ("SMOKER_X__" + B + "__y", False)]:
        got = render(cond, trigger={"event": {"data": {"action": action}}})
        check(got is want, f"button {action!r} accepted: {got!r}")

    # 2e. the AI plan's program is checked before it's loaded
    pv = pkg["script"]["smoker_check_program"]["sequence"][0]["variables"]["refused"]
    hass.states.async_set("number.smoker_pit_target", "225", {"unit_of_measurement": "°F", "min": 200, "max": 700})
    ok = 'name: Pork butt; pit 250 until food1 >= 165 for 30m; pit 275 until food1 >= 203; hold 200 notify "Rest it; don\'t cut"'
    for prog, bad in [(ok, ""), ("pit 400F until after 2h", ""), ("1. pit 250\n2. hold 200", ""),
                      ("pit 450 until food1 done", "above the 400°F"), ("hold 401", "above"),
                      ("set to 230C until after 1h", "above"), ('pit 250 notify "see http://x.example"', "link"),
                      ('pit 250 notify "go to www.example.com"', "link"), ("ignore the rules; pit 250", "not an action"),
                      ("pit 250; name: x", "must come first"), ('pit 250 notify "unbalanced', "quotes"),
                      ("", "no program"), ("name: only a name", "no steps"), ("pit 250 until food1 >= 165 {x}", "other than"),
                      ("name: x; pit 250\nhold 900", "above"),
                      # The controller starts a new word right after a closing quote: these are all pit 700.
                      ('pit 250 notify "ok"pit 700', "above"), ('notify "go"pit 700', "above"),
                      ("notify 'a'set to 700", "above"), ('notify "a"hold 700', "above"),
                      ('pit 250 notify "x" "y"pit 700', "above"), ('notify "go",pit 700', "above"),
                      ("pit 250 notify 'it''s'pit 700", "above"), ('notify ""pit 700', "above"),
                      ('pit 250 notify "a"then pit 700', "above"), ("pit 250 then hold 900", "above"),
                      # Words that only contain pit/hold/set are not actions the controller knows (refused anyway).
                      ("pit 250 until food1 >= 165; setpit 900", "not an action"),
                      # A pit with no readable number after it is refused, never skipped.
                      ('notify "a"pit "b"', "can't be read"), ("pit 250 notify 'x'pit", "can't be read"),
                      # Turbo (the fan flat out) would take the pit past the cap: never in an AI plan.
                      ("pit 225 turbo on until after 10h; turbo off; hold 225", "Turbo"),
                      ('pit 225 notify "x"turbo on until after 1h', "Turbo"),
                      ('pit 225 notify "turbo is fun" until after 1h', "")]:
        got = str(render(pv, program=prog, explanation="Fine.", max_pit=400.0) or "")
        check((bad in got) if bad else got == "", f"plan check {prog!r} -> {got!r}")
    # Keep steps: only through the controller's own check (keep_ok), which limits the pit they ask for.
    for prog, ok, bad in [("pit 200 keep food1 203", False, "uses keep"), ("pit 200 keep food1 203", True, ""),
                          ("name: Warm; pit 225 until food1 >= 195; keep food1 at 140", True, ""),
                          ("name: Warm; pit 225 until food1 >= 195; keep food1 at 140", False, "uses keep")]:
        got = str(render(pv, program=prog, explanation="Fine.", max_pit=225.0, keep_ok=ok) or "")
        check((bad in got) if bad else got == "", f"plan check {prog!r}, controller's check {ok} -> {got!r}")
    hass.states.async_set("number.smoker_pit_target", "107", {"unit_of_measurement": "°C", "min": 93, "max": 371})
    check("above" in str(render(pv, program="pit 250", explanation="", max_pit=400.0)), "°C controller: pit 250 is 482°F")
    check(str(render(pv, program="pit 120", explanation="", max_pit=400.0) or "") == "", "°C controller: pit 120 is fine")
    check("link" in str(render(pv, program="pit 120", explanation="More at https://x.example", max_pit=400.0)),
          "a link in the explanation")

    # 3. recommendation parsing in the advisor script
    adv = pkg["script"]["smoker_ai_advise"]["sequence"]
    items_t = next(st for st in adv if isinstance(st, dict) and "variables" in st and "items" in st["variables"])["variables"]["items"]
    text = "now | Wrap it | Bark is set\n18:30 | Top up | Wind picks up | later\nnot a rec line"
    items = render(items_t, advice={"data": {"recommendations": text}})
    check(isinstance(items, list) and len(items) == 2 and items[0]["title"] == "Wrap it"
          and items[1]["detail"] == "Wind picks up | later", f"recommendations parsed: {items!r}")
    # 4. voice: hopper level words -> percent, and which fuel action
    ft = autos["smoker_voice_fuel_tell"]["actions"][0]["variables"]
    for sentence, level, want_pct, want_kind in [
        ("the hopper is three quarters full", "three quarters", 75, "level"),
        ("I topped up the hopper to half full", "half", 50, "refilled"),
        ("I added a quarter of a hopper", "a quarter", 25, "added"),
        ("the hopper is 40 percent full", "40 percent", 40, "level"),
        ("the hopper is mostly full", "mostly", -1, "level"),
    ]:
        trig = {"slots": {"level": level}, "sentence": sentence}
        words = render_dict(ft["words"])
        raw = render(ft["raw"], trigger=trig)
        pct = render(ft["pct"], trigger=trig, words=words, raw=raw)
        kind = render(ft["kind"], trigger=trig)
        check(float(pct) == want_pct and kind == want_kind, f"voice {sentence!r} -> {pct} {kind}")

    # 5. forecast feed: minutes from now and temperatures as lists
    fv = autos["smoker_forecast_feed"]["actions"][1]["variables"]
    from homeassistant.util import dt as dt_util
    now = dt_util.now()
    fc = {"weather.forecast_home": {"forecast": [
        {"datetime": (now + __import__("datetime").timedelta(hours=h)).isoformat(), "temperature": 40 - h} for h in range(4)]}}
    f = render(fv["f"], fc=fc)
    mins = render(fv["minutes"], f=f)
    temps = render(fv["temps"], f=f)
    check(isinstance(mins, list) and len(mins) == 4 and abs(mins[1] - 60) <= 1 and temps == [40.0, 39.0, 38.0, 37.0],
          f"forecast lists {mins} {temps}")

    # 5b. Plan with AI loads through the controller's own AI check from firmware 1.4.4 (older firmware: plain load)
    seq = pkg["script"]["smoker_plan_cook"]["sequence"]
    vt = next(st["variables"]["via_controller"] for st in seq if isinstance(st, dict) and "via_controller" in st.get("variables", {}))
    for ver, want in (("1.4.4", True), ("1.10.0", True), ("1.4.3", False), (None, False)):
        hass.states.async_set("update.smoker_firmware", "off", {"installed_version": ver} if ver else {})
        got = render(vt)
        check(got is want, f"Plan with AI uses the controller's check with firmware {ver}: {got!r}")
    # ...and then trusts the controller's rewrite (one step a line, the pit capped): no text comparison, no second
    # check in Home Assistant's unit (1.4.4 compared the texts and replaced every plan with a safe hold).
    rb = next(st for st in seq if isinstance(st, dict) and "variables" in st and "same" in st["variables"])["variables"]["same"]
    replace = next(st["if"] for st in seq if isinstance(st, dict) and "if" in st and "not via_controller" in str(st["if"]))
    ctl_text, ai_text = "name: AI\npit 400 until after 5h\nhold 225\n", "name: AI; pit 600 until after 5h; hold 225"
    for via, want_same in ((True, True), (False, False)):
        got = render(rb, via_controller=via, loaded=ctl_text, cut=False, program=ai_text)
        check(got is want_same, f"read-back after loading (through the controller: {via}) counts as the same program: {got!r}")
    got = render(replace, via_controller=True, same=True, recheck={"refused": "it sets the pit to 750°F"})
    check(got is False, f"through the controller, Home Assistant's second check doesn't replace the plan: {got!r}")
    got = render(replace, via_controller=False, same=False, recheck={"refused": ""})
    check(got is True, f"older firmware: a program that changed on the way is still replaced: {got!r}")
    # 6. serve together: when each food goes on, the light-up time, and the "put it on" reminders (once per food)
    import datetime as dtm
    serve = (now + dtm.timedelta(hours=14)).replace(microsecond=0)
    # The state is a naive local string; the helper's timestamp attribute is the real moment (Home Assistant's zone).
    # The string here is deliberately 5 h off, so a template that parses it instead of the timestamp fails.
    hass.states.async_set("input_datetime.smoker_serve_time", (serve + dtm.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
                          {"timestamp": serve.timestamp(), "has_date": True, "has_time": True})
    hass.states.async_set("input_number.smoker_rest_minutes", "45")
    for n, total, weight, prot in ((1, "760", "8.2", "Pork shoulder"), (3, "300", "3.5", "Poultry"), (4, "420", "0", "Brisket"),
                                   (2, "unknown", "5", "Auto")):
        hass.states.async_set(f"sensor.smoker_food_{n}_estimated_total_cook_time", total)
        hass.states.async_set(f"number.smoker_food_{n}_weight", weight)
        hass.states.async_set(f"select.smoker_food_{n}_protein", prot)
    st = next(x for x in tsens if x.get("unique_id") == "smoker_serve_together")
    foods = render(st["attributes"]["foods"])
    s_ts = int(serve.timestamp())
    check(foods == [{"slot": 1, "name": "Pork shoulder", "total": 760, "on": s_ts - (760 + 45) * 60},
                    {"slot": 3, "name": "Poultry", "total": 300, "on": s_ts - (300 + 45) * 60}],
          f"serve together: only foods with a weight and an estimate, earliest first: {foods}")
    check(int(render(st["state"])) == 2 and int(render(st["attributes"]["serve"])) == s_ts, "serve together: count and serve time")
    by = next(x for x in tsens if x.get("unique_id") == "smoker_start_by")["state"]
    got = dt_util.parse_datetime(str(render(by)))
    check(got is not None and abs((serve - got).total_seconds() / 60 - (760 + 45 + 45)) < 1,
          f"light the grill: 45 min before the longest food goes on ({got})")
    # The reminder's trigger: due once a food's time has come, until it's marked as sent for this serve time.
    put = autos["smoker_put_on_reminder"]
    trig = put["triggers"][0]["value_template"]
    attrs = {"serve": s_ts, "rest_minutes": 45, "foods": foods}
    hass.states.async_set("sensor.smoker_serve_together", "2", attrs)
    hass.states.async_set("input_text.smoker_put_on_sent", "")
    check(render(trig) is False, "put it on: nothing due 14 h before serving")
    early = dict(attrs, foods=[dict(foods[0], on=s_ts - 20 * 3600), foods[1]])
    hass.states.async_set("sensor.smoker_serve_together", "2", early)
    check(render(trig) is True, "put it on: the pork is due")
    v = put["actions"][0]["variables"]
    done = render(v["done"], serve=s_ts)
    due = render(v["due"], done=done)
    check([d["slot"] for d in due] == [1], f"put it on: due {due}")
    sent = render(put["actions"][2]["data"]["value"], serve=s_ts, done=done, due=due)
    check(sent == f"{s_ts}:1", f"put it on: marked as sent {sent!r}")
    hass.states.async_set("input_text.smoker_put_on_sent", sent)
    check(render(trig) is False, "put it on: not again once sent")
    msg = render(put["actions"][3]["repeat"]["sequence"][0]["data"]["message"], repeat={"item": due[0]}, serve=s_ts, rest=45)
    check("Put the pork shoulder on now (Food 1)" in msg and "plus a 45 min rest" in msg, f"put it on: message {msg!r}")
    hass.states.async_set("input_text.smoker_put_on_sent", f"{s_ts - 60}:13")  # sent for an earlier serve time
    check(render(trig) is True, "put it on: a new serve time starts afresh")
    await hass.async_stop()


if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print(f"{len(failures)} template check(s) FAILED")
        sys.exit(1)
    print("template checks passed")
