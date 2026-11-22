"""Voice: the package's Assist sentence triggers answer and act (HA's own conversation agent)."""

from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component

PKG = Path(__file__).resolve().parents[2] / "homeassistant" / "packages" / "smoker.yaml"


class _Loader(yaml.SafeLoader):
    pass


async def _ask(hass, text):
    r = await hass.services.async_call("conversation", "process", {"text": text, "language": "en"},
                                       blocking=True, return_response=True)
    return r["response"]["speech"]["plain"]["speech"]


async def test_voice(hass: HomeAssistant):
    pkg = yaml.load(PKG.read_text(), Loader=_Loader)
    voice = [a for a in pkg["automation"] if a["id"].startswith("smoker_voice_")]
    assert len(voice) >= 7
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    assert await async_setup_component(hass, "automation", {"automation": voice})
    await hass.async_block_till_done()

    hass.states.async_set("sensor.smoker_pit_temperature", "251")
    hass.states.async_set("number.smoker_pit_target", "250")
    hass.states.async_set("sensor.smoker_food_1_temperature", "158")
    hass.states.async_set("sensor.smoker_food_1_time_remaining", "120")
    hass.states.async_set("select.smoker_food_1_protein", "Brisket")
    hass.states.async_set("sensor.smoker_charcoal_level", "62")
    hass.states.async_set("sensor.smoker_charcoal_hours_left", "6.4")
    hass.states.async_set("sensor.smoker_charcoal_empty_at", "17:10")
    hass.states.async_set("binary_sensor.smoker_food_1_stall", "on")
    hass.states.async_set("sensor.smoker_food_1_stall_remaining", "90")
    calls = []

    async def rec(call: ServiceCall):
        d = dict(call.data)
        if isinstance(d.get("entity_id"), list) and len(d["entity_id"]) == 1:
            d["entity_id"] = d["entity_id"][0]
        calls.append((call.domain, call.service, d))

    for dom, svc in [("number", "set_value"), ("switch", "turn_on"), ("esphome", "gravity980_fuel_level"),
                     ("esphome", "gravity980_fuel_refilled"), ("esphome", "gravity980_fuel_added")]:
        hass.services.async_register(dom, svc, rec)

    assert "251 degrees" in await _ask(hass, "how hot is the smoker")
    a = await _ask(hass, "when will the brisket be done")
    assert "158 degrees" in a and "done around" in a and "experimental" not in a, a
    hass.states.async_set("sensor.smoker_food_1_estimate_basis", "Experimental (learning: 1 of 3 similar cooks). Brisket")
    a = await _ask(hass, "when will the brisket be done")
    assert "experimental estimate" in a, a
    a = await _ask(hass, "how much charcoal is left")
    assert "62 percent" in a and "6.4 hours" in a, a
    a = await _ask(hass, "set the smoker to 275 degrees")
    assert "275" in a and calls[-1] == ("number", "set_value", {"entity_id": "number.smoker_pit_target", "value": 275.0})
    a = await _ask(hass, "set the smoker to 900")
    assert "between 200 and 700" in a
    a = await _ask(hass, "the hopper is three quarters full")
    assert calls[-1] == ("esphome", "gravity980_fuel_level", {"percent": 75.0}), calls[-1]
    await _ask(hass, "I topped up the hopper to half full")
    assert calls[-1] == ("esphome", "gravity980_fuel_refilled", {"percent": 50.0}), calls[-1]
    a = await _ask(hass, "is the stall over")
    assert "still in the stall" in a and "1.5 more hours" in a, a
    a = await _ask(hass, "I pulled the brisket")
    assert calls[-1] == ("switch", "turn_on", {"entity_id": "switch.smoker_food_1_pulled"}), calls[-1]

    # A second probe on chicken (Food 3, e.g. an H5198 probe): answers and actions follow the named food.
    hass.states.async_set("sensor.smoker_food_3_temperature", "150")
    hass.states.async_set("select.smoker_food_3_protein", "Poultry")
    hass.states.async_set("binary_sensor.smoker_food_3_stall", "off")
    hass.states.async_set("sensor.smoker_food_3_phase", "Finishing")
    a = await _ask(hass, "is the poultry stalled")
    assert "food 3 is not stalled" in a and "food 1" not in a, a
    a = await _ask(hass, "I pulled the poultry")
    assert calls[-1] == ("switch", "turn_on", {"entity_id": "switch.smoker_food_3_pulled"}), calls[-1]
    # Two foods cooking and "the meat" is ambiguous: ask, don't guess.
    n = len(calls)
    a = await _ask(hass, "I pulled the meat")
    assert "Which probe" in a and len(calls) == n, a
    # "the grill is off" is not a smoker sentence any more (it used to flip Food 1 to resting).
    await _ask(hass, "the grill is off")
    assert len(calls) == n, calls[-1]
    # The range comes from the pit target number (°C controllers too).
    hass.states.async_set("number.smoker_pit_target", "120", {"min": 93, "max": 371})
    a = await _ask(hass, "set the smoker to 150 degrees")
    assert calls[-1] == ("number", "set_value", {"entity_id": "number.smoker_pit_target", "value": 150.0}), a
    a = await _ask(hass, "set the smoker to 400")
    assert "between 93 and 371" in a, a
    await _ask(hass, "I added half a hopper")
    assert calls[-1] == ("esphome", "gravity980_fuel_added", {"percent": 50.0}), calls[-1]
