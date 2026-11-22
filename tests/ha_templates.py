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

    # 1. probe key mapping used by the notification buttons
    seq = autos["smoker_notification_actions"]["actions"][1]["choose"]
    plus = next(c for c in seq if "FOOD_PLUS_5" in str(c["conditions"]))["sequence"][0]["variables"]["key"]
    for a, want in [("SMOKER_FOOD_PLUS_5_FOOD1", "food_1"), ("SMOKER_FOOD_PLUS_5_GOVEE3", "govee_3")]:
        got = render(plus, a=a)
        check(got == want, f"button key {a} -> {got!r}")
    wrap = next(c for c in seq if "WRAPPED" in str(c["conditions"]))["sequence"][0]["target"]["entity_id"]
    got = render(wrap, a="SMOKER_WRAPPED_GOVEE2")
    check(got == "switch.smoker_govee_2_wrapped", f"wrapped entity -> {got!r}")

    # 2. buttons variable renders to a real list
    fwd = autos["smoker_forward_notifications"]["actions"][0]["variables"]
    class Ev:  # minimal trigger.event
        def __init__(self, title, tag):
            self.data = {"title": title, "tag": tag}
    for title, tag, n in [("Food 1 is done", "done_food1", 2), ("Pit temperature off", "pit_band", 2),
                          ("Program paused", "program", 1), ("Controller restarted", "program", 1),
                          ("Govee 2 stall", "stall_govee2", 1), ("Food 1 stall over", "stall_food1", 0)]:
        b = render(fwd["buttons"], tag=tag, trigger={"event": Ev(title, tag)})
        check(isinstance(b, list) and len(b) == n, f"buttons for {title!r}: {b!r}")

    # 3. recommendation parsing in the advisor script
    adv = pkg["script"]["smoker_ai_advise"]["sequence"]
    items_t = next(st for st in adv if isinstance(st, dict) and "variables" in st and "items" in st["variables"])["variables"]["items"]
    text = "now | Wrap it | Bark is set\n18:30 | Top up | Wind picks up | later\nnot a rec line"
    items = render(items_t, advice={"data": {"recommendations": text}})
    check(isinstance(items, list) and len(items) == 2 and items[0]["title"] == "Wrap it"
          and items[1]["detail"] == "Wind picks up | later", f"recommendations parsed: {items!r}")
    await hass.async_stop()


if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print(f"{len(failures)} template check(s) FAILED")
        sys.exit(1)
    print("template checks passed")
