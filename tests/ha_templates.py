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
    seq = autos["smoker_notification_actions"]["actions"][1]["choose"]
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
                          ("Food 6 stall", "stall_food6", 1), ("Food 1 stall over", "stall_food1", 0)]:
        b = render(fwd["buttons"], tag=tag, trigger={"event": Ev(title, tag)})
        check(isinstance(b, list) and len(b) == n, f"buttons for {title!r}: {b!r}")

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
    await hass.async_stop()


if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print(f"{len(failures)} template check(s) FAILED")
        sys.exit(1)
    print("template checks passed")
