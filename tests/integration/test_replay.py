"""Cook replay (replay.py): curves and events from history, kept with the journal, served to the dashboard."""

import json
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smoker import replay
from custom_components.smoker.journal import DATA

T0 = 1_800_000_000.0  # the cook's start (epoch seconds)


def test_build_curves_and_events():
    h = lambda x: T0 + x * 3600  # noqa: E731
    series = {
        # the state at the start (before it) and the changes after
        "pit": [(T0 - 600, "248.0"), (h(0.5), "251.2"), (h(2), "unavailable"), (h(2.1), "249.04")],
        "target": [(T0 - 900, "250"), (h(6), "275")],
        "food": [(T0 - 60, "40"), (h(3), "158"), (h(8), "203")],
        "lid": [(T0 - 60, "off"), (h(1), "on"), (h(1) + 95, "off"), (h(5), "unknown"), (h(7), "on")],
        "wrapped": [(T0 - 60, "off"), (h(6), "on")],
        "stall": [(T0 - 60, "off"), (h(3.1), "on"), (h(6.4), "off")],
        "pulled": [(T0 - 60, "off"), (h(8), "on")],
        # already on step 1 at the start: no event for it; then step 2; a status change within a step is no event
        "program": [(T0 - 60, "Step 1/3, pit 250°F"), (h(1), "Step 1/3, pit 250°F, food1 120"), (h(6), "Step 2/3, pit 275°F")],
        "fuel": [(T0 - 60, "70"), (h(3), "40"), (h(4), "85"), (h(5), "83")],
    }
    r = replay.build(series, T0, h(8), 1, "°F")
    assert r["start"] == T0 and r["unit"] == "°F" and r["slot"] == 1
    assert r["step"] == 180 and len(r["pit"]) == 8 * 3600 // 180 + 1 <= replay.MAX_POINTS  # 8 h in at most 240 points
    assert r["pit"][0] == 248.0 and r["pit"][10] == 251.2 and r["pit"][40] is None and r["pit"][-1] == 249.0
    assert r["target"][0] == 250 and r["target"][-1] == 275
    ev = [(round((e["t"] - T0) / 3600, 2), e["k"], e.get("slot"), e.get("v"), e.get("d")) for e in r["events"]]
    assert ev == [(1.0, "lid", None, None, 95), (3.1, "stall_start", 1, None, None), (4.0, "fuel", None, 85, None),
                  (6.0, "wrap", 1, None, None), (6.0, "step", None, 2, None), (6.4, "stall_end", 1, None, None),
                  (7.0, "lid", None, None, None), (8.0, "pulled", 1, None, None)]
    # No readings at all: empty curves (the page says nothing was recorded).
    empty = replay.build({}, T0, h(2), None)
    assert empty["pit"] == [] and empty["food"] == [] and empty["events"] == []


async def _setup(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain="smoker", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_replay_view(hass: HomeAssistant, hass_client, tmp_path, smoker_device_id):
    await _setup(hass, tmp_path)
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps({"probe": "food1", "total_h": 2}),
                                                          "device_id": smoker_device_id})
    await hass.async_block_till_done()
    j = hass.data[DATA]
    entry = j.data["entries"][-1]
    client = await hass_client()
    # Without the recorder: nothing to read, an empty replay (not an error).
    r = await client.get(f"/api/smoker/journal/{entry['id']}/replay")
    d = await r.json()
    assert r.status == 200 and d["kept"] is False and d["pit"] == [] and d["events"] == []
    assert (await client.get("/api/smoker/journal/0123456789ab/replay")).status == 404
    # A kept replay is served as kept, and goes when its cook is deleted from the journal.
    kept = replay.build({"pit": [(entry["started"], "250")]}, entry["started"], entry["ended"], 1, "°F")
    j.replays.keep(entry["id"], kept, {entry["id"]})
    d = await (await client.get(f"/api/smoker/journal/{entry['id']}/replay")).json()
    assert d["kept"] is True and d["pit"][0] == 250
    assert j.delete_entry(entry["id"])
    assert entry["id"] not in j.replays.data
    assert not j.replays.pending  # no recorder: no snapshot was scheduled
