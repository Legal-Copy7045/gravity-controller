"""Package automations that react to the controller: cook summary, AI plan refresh."""

import json
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component

PKG = Path(__file__).resolve().parents[2] / "homeassistant" / "packages" / "smoker.yaml"


class _Loader(yaml.SafeLoader):
    pass


def _autos(*ids):
    pkg = yaml.load(PKG.read_text(), Loader=_Loader)
    return [a for a in pkg["automation"] if a["id"] in ids]


async def _setup(hass, ids, services):
    calls = []

    async def rec(call: ServiceCall):
        calls.append((call.domain, call.service, dict(call.data)))

    for dom, svc in services:
        hass.services.async_register(dom, svc, rec)
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "automation", {"automation": _autos(*ids)})
    await hass.async_block_till_done()
    return calls


async def test_cook_summary_without_stall_or_pit(hass: HomeAssistant):
    calls = await _setup(hass, ["smoker_cook_complete_summary"],
                         [("logbook", "log"), ("input_number", "set_value"), ("timer", "start"), ("ai_task", "generate_data")])
    hass.states.async_set("input_boolean.smoker_ai_advisor", "off")
    # Poultry doesn't stall (stall_h null) and the pit average can be unknown.
    summary = {"probe": "food3", "name": "Food 3", "profile": "Poultry", "weight_kg": None, "wrapped": False,
               "pit_c": None, "target_c": 74, "stall_h": None, "total_h": 1.6, "history_count": 4}
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(summary)})
    await hass.async_block_till_done()
    log = [c for c in calls if c[:2] == ("logbook", "log")]
    assert log and "Food 3 (Poultry) done in 1.6 h." in " ".join(log[0][2]["message"].split()), log
    assert any(c[:2] == ("timer", "start") for c in calls), calls  # the rest timer still starts


async def test_plan_refresh_ignores_reconnects(hass: HomeAssistant):
    calls = await _setup(hass, ["smoker_ai_plan_refresh"], [("script", "smoker_ai_advise")])
    hass.states.async_set("input_boolean.smoker_ai_advisor", "on")
    hass.states.async_set("number.smoker_food_1_weight", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("number.smoker_food_1_weight", "8.0")  # controller came back
    hass.states.async_set("number.smoker_food_1_weight", "8.0", {"min": 0})  # attribute-only change
    await hass.async_block_till_done()
    assert not [c for c in calls if c[1] == "smoker_ai_advise"]
    eid = "automation.smoker_refresh_the_ai_plan_when_the_cook_plan_changes"
    assert hass.states.get(eid).attributes.get("last_triggered") is None
    # A real edit does start it (it then waits 2 minutes for more edits before asking the AI).
    hass.states.async_set("number.smoker_food_1_weight", "9.5")
    import asyncio

    for _ in range(20):  # (not async_block_till_done: that would wait out the delay)
        await asyncio.sleep(0.01)
    assert hass.states.get(eid).attributes.get("last_triggered") is not None
    await hass.services.async_call("automation", "turn_off", {"entity_id": eid, "stop_actions": True}, blocking=True)
