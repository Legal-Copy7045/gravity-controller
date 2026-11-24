"""Cook replay with the recorder: shortly after a cook ends, its curves and events are read from the history and kept
(a module of its own: the recorder has to be set up before Home Assistant is)."""

import json
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.smoker import replay
from custom_components.smoker.journal import DATA

from .test_replay import _setup


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    yield


async def test_snapshot_kept(hass: HomeAssistant, hass_client, tmp_path, smoker_device_id):
    """With the recorder: shortly after a cook ends, its curves and events are read from the history and kept."""
    from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

    await _setup(hass, tmp_path)
    for eid, st, name in (("sensor.smoker_pit_temperature", "251", "Smoker Pit temperature"),
                          ("sensor.smoker_food_1_temperature", "150", "Smoker Food 1 temperature"),
                          ("binary_sensor.smoker_lid", "off", "Smoker Lid")):
        hass.states.async_set(eid, st, {"friendly_name": name, "unit_of_measurement": "°F" if "temp" in eid else None})
    await async_wait_recording_done(hass)
    hass.states.async_set("binary_sensor.smoker_lid", "on", {"friendly_name": "Smoker Lid"})
    hass.states.async_set("sensor.smoker_food_1_temperature", "160", {"friendly_name": "Smoker Food 1 temperature",
                                                                      "unit_of_measurement": "°F"})
    await async_wait_recording_done(hass)
    hass.states.async_set("binary_sensor.smoker_lid", "off", {"friendly_name": "Smoker Lid"})
    await async_wait_recording_done(hass)
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps({"probe": "food1", "total_h": 1}),
                                                          "device_id": smoker_device_id})
    await hass.async_block_till_done()
    j = hass.data[DATA]
    entry = j.data["entries"][-1]
    assert len(j.replays.pending) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=replay.SNAPSHOT_DELAY_S + 1))
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    await hass.async_block_till_done()
    kept = j.replays.data.get(entry["id"])
    assert kept and kept["unit"] == "°F" and kept["pit"][-1] == 251 and kept["food"][-1] == 160
    assert [e["k"] for e in kept["events"]] == ["lid"] and kept["events"][0]["d"] >= 0
    d = await (await (await hass_client()).get(f"/api/smoker/journal/{entry['id']}/replay")).json()
    assert d["kept"] is True
