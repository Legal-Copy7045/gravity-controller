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
    # A real edit with nothing cooking or planned doesn't (no AI credits on an idle grill)...
    hass.states.async_set("number.smoker_food_1_weight", "9.0")
    await hass.async_block_till_done()
    assert hass.states.get(eid).attributes.get("last_triggered") is None
    # ...but during a cook it does (it then waits 2 minutes for more edits before asking the AI).
    hass.states.async_set("binary_sensor.smoker_cook_active", "on")
    hass.states.async_set("number.smoker_food_1_weight", "9.5")
    import asyncio

    for _ in range(20):  # (not async_block_till_done: that would wait out the delay)
        await asyncio.sleep(0.01)
    assert hass.states.get(eid).attributes.get("last_triggered") is not None
    await hass.services.async_call("automation", "turn_off", {"entity_id": eid, "stop_actions": True}, blocking=True)


async def test_ai_advisor_only_for_a_cook(hass: HomeAssistant):
    """The AI pitmaster script asks nothing unless a cook is underway or planned (serve-by within two days)."""
    import datetime as dt

    from homeassistant.util import dt as dt_util

    pkg = yaml.load(PKG.read_text(), Loader=_Loader)
    calls = []

    async def rec(call: ServiceCall):
        calls.append((call.domain, call.service, dict(call.data)))

    for dom, svc in [("input_text", "set_value"), ("esphome", "gravity980_request_context")]:
        hass.services.async_register(dom, svc, rec)
    assert await async_setup_component(hass, "script", {"script": {"smoker_ai_advise": pkg["script"]["smoker_ai_advise"]}})
    hass.states.async_set("binary_sensor.smoker_cook_active", "off")
    hass.states.async_set("input_datetime.smoker_serve_time", "unknown")
    await hass.services.async_call("script", "smoker_ai_advise", {}, blocking=True)
    assert not [c for c in calls if c[0] == "esphome"], calls
    assert any("Nothing's cooking" in c[2].get("value", "") for c in calls), calls
    # A serve-by next week isn't "planned" yet either.
    week = dt_util.now() + dt.timedelta(days=7)
    hass.states.async_set("input_datetime.smoker_serve_time", week.strftime("%Y-%m-%d %H:%M:%S"))
    await hass.services.async_call("script", "smoker_ai_advise", {}, blocking=True)
    assert not [c for c in calls if c[0] == "esphome"], calls
    # Tomorrow's cook is.
    soon = dt_util.now() + dt.timedelta(hours=20)
    hass.states.async_set("input_datetime.smoker_serve_time", soon.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        await hass.services.async_call("script", "smoker_ai_advise", {}, blocking=False)
        for _ in range(20):
            import asyncio
            await asyncio.sleep(0.01)
    finally:
        await hass.services.async_call("script", "turn_off", {"entity_id": "script.smoker_ai_advise"}, blocking=True)
    assert [c for c in calls if c[0] == "esphome"], calls


async def _helpers(hass):
    pkg = yaml.load(PKG.read_text(), Loader=_Loader)
    for dom in ("input_number", "input_text", "input_datetime"):
        assert await async_setup_component(hass, dom, {dom: pkg[dom]})
    await hass.async_block_till_done()


async def test_charcoal_burned_stock_and_reorder(hass: HomeAssistant):
    """Drops in 'Charcoal left' count as burned and come off the stock; below a bag it goes on the to-do list."""
    calls = await _setup(hass, ["smoker_charcoal_burn", "smoker_charcoal_reorder"],
                         [("todo", "add_item"), ("script", "smoker_notify")])
    await _helpers(hass)
    for eid, v in (("input_number.smoker_charcoal_bag_kg", 9), ("input_number.smoker_charcoal_stock_kg", 9.3)):
        await hass.services.async_call("input_number", "set_value", {"entity_id": eid, "value": v}, blocking=True)
    hass.states.async_set("sensor.smoker_charcoal_left", "5.0")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.smoker_charcoal_left", "4.5")  # burned 0.5 kg
    await hass.async_block_till_done()
    hass.states.async_set("sensor.smoker_charcoal_left", "7.0")  # a top-up: not a burn
    await hass.async_block_till_done()
    assert float(hass.states.get("input_number.smoker_charcoal_burned_kg").state) == 0.5
    assert float(hass.states.get("input_number.smoker_charcoal_stock_kg").state) == 8.8
    assert [c for c in calls if c[:2] == ("todo", "add_item") and "Charcoal" in c[2]["item"]], calls


async def test_maintenance_due_adds_a_job(hass: HomeAssistant):
    calls = await _setup(hass, ["smoker_maintenance_due"], [("todo", "add_item"), ("script", "smoker_notify")])
    await _helpers(hass)
    await hass.services.async_call("input_number", "set_value",
                                   {"entity_id": "input_number.smoker_hours_ash", "value": 12.1}, blocking=True)
    await hass.async_block_till_done()
    assert [c for c in calls if c[:2] == ("todo", "add_item") and "ash" in c[2]["item"]], calls


async def test_calendar_sets_the_serve_time_unless_set_by_hand(hass: HomeAssistant):
    import datetime as dt

    from homeassistant.core import SupportsResponse
    from homeassistant.util import dt as dt_util

    when = (dt_util.now() + dt.timedelta(hours=20)).replace(second=0, microsecond=0)

    async def events(call: ServiceCall):
        return {"calendar.your_calendar": {"events": [
            {"start": (when - dt.timedelta(hours=3)).isoformat(), "end": when.isoformat(), "summary": "Dentist"},
            {"start": when.isoformat(), "end": (when + dt.timedelta(hours=2)).isoformat(), "summary": "Brisket dinner"}]}}

    hass.services.async_register("calendar", "get_events", events, supports_response=SupportsResponse.ONLY)
    calls = await _setup(hass, ["smoker_calendar_serve_time"], [("script", "smoker_notify")])
    await _helpers(hass)
    hass.states.async_set("calendar.your_calendar", "off")
    await hass.services.async_call("automation", "trigger",
                                   {"entity_id": "automation.smoker_serve_time_from_the_calendar"}, blocking=True)
    await hass.async_block_till_done()
    got = dt_util.as_local(dt_util.parse_datetime(hass.states.get("input_datetime.smoker_serve_time").state))
    assert got.replace(tzinfo=None) == when.replace(tzinfo=None), got
    assert hass.states.get("input_text.smoker_serve_source").state == "calendar"
    assert [c for c in calls if c[1] == "smoker_notify" and "Brisket dinner" in c[2]["message"]]
    # Set by hand (in the future): the calendar leaves it alone.
    await hass.services.async_call("input_text", "set_value",
                                   {"entity_id": "input_text.smoker_serve_source", "value": "manual"}, blocking=True)
    later = when + dt.timedelta(hours=1)
    await hass.services.async_call("input_datetime", "set_datetime", {"entity_id": "input_datetime.smoker_serve_time",
                                   "datetime": later.strftime("%Y-%m-%d %H:%M:%S")}, blocking=True)
    await hass.services.async_call("automation", "trigger",
                                   {"entity_id": "automation.smoker_serve_time_from_the_calendar"}, blocking=True)
    await hass.async_block_till_done()
    got = dt_util.as_local(dt_util.parse_datetime(hass.states.get("input_datetime.smoker_serve_time").state))
    assert got.replace(tzinfo=None) == later.replace(tzinfo=None)
