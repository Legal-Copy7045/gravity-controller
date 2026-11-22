"""Smoker integration: panel, journal, draft from scanned packages, photo identification (AI mocked)."""

import json

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smoker.journal import DATA, parse_items

DOMAIN = "smoker"


async def _setup(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def test_parse_items():
    text = """NAME | PROFILE | WEIGHT_LB | BARCODE | NOTES
Bone-in pork shoulder (Boston butt) | Pork shoulder | 8.42 lb | 2 12345 67890 | bone-in
Whole chicken | poultry | 1.9 kg? |  |
nonsense line without pipes
Mystery cut | Wagyu | | |"""
    items = parse_items(text)
    assert [i["name"] for i in items] == ["Bone-in pork shoulder (Boston butt)", "Whole chicken", "Mystery cut"]
    assert items[0]["profile"] == "Pork shoulder" and items[0]["weight_lb"] == 8.42 and items[0]["barcode"] == "21234567890"
    assert items[1]["profile"] == "Poultry"
    assert items[2]["profile"] == "Auto" and items[2]["weight_lb"] is None


async def test_journal_flow(hass: HomeAssistant, hass_client, tmp_path):
    await _setup(hass, tmp_path)
    client = await hass_client()

    # The page is served to logged-in users and contains the journal section.
    r = await client.get("/api/smoker/page")
    assert r.status == 200
    html = await r.text()
    assert "Smoker · live" in html and "id=\"journal\"" in html

    # Controller entities the draft assignment will set.
    hass.states.async_set("select.smoker_food_1_protein", "Auto", {"options": ["Auto", "Pork shoulder"]})
    hass.states.async_set("number.smoker_food_1_weight", "0", {"unit_of_measurement": "lb"})
    calls = []

    async def record(call: ServiceCall):
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("select", "select_option", record)
    hass.services.async_register("number", "set_value", record)

    # Identify: AI task mocked; photos land in the media folder and the draft.
    seen = {}

    async def fake_generate(call: ServiceCall):
        seen.update(call.data)
        return {"conversation_id": "x", "data": "Pork butt | Pork shoulder | 8.5 | | bone-in\nChicken thighs | Poultry | 2 | |"}

    hass.services.async_register("ai_task", "generate_data", fake_generate, supports_response=SupportsResponse.ONLY)
    import aiohttp

    form = aiohttp.FormData()
    form.add_field("photo", b"\xff\xd8\xff fake jpeg", filename="a.jpg", content_type="image/jpeg")
    form.add_field("photo", b"\x89PNG fake", filename="b.png", content_type="image/png")
    r = await client.post("/api/smoker/identify", data=form)
    assert r.status == 200, await r.text()
    body = await r.json()
    assert [i["name"] for i in body["items"]] == ["Pork butt", "Chicken thighs"]
    assert len(seen["attachments"]) == 2
    assert seen["attachments"][0]["media_content_id"].startswith("media-source://media_source/local/smoker/")
    assert (tmp_path / "media" / "smoker").is_dir()
    photo = body["draft"]["photos"][0]
    r = await client.get(f"/api/smoker/photo/{photo}")
    assert r.status == 200
    assert (await client.get("/api/smoker/photo/..%2Fsecrets.yaml")).status in (400, 404)  # HA filter or our check
    assert (await client.get("/api/smoker/photo/secrets.yaml")).status == 404

    # Assign the pork to food1: the probe's protein and weight are set on the controller.
    items = body["draft"]["items"]
    items[0]["probe"] = "food1"
    r = await client.post("/api/smoker/draft", json={"items": items})
    assert r.status == 200
    await hass.async_block_till_done()
    assert ("select", "select_option", {"entity_id": "select.smoker_food_1_protein", "option": "Pork shoulder"}) in calls
    assert any(c[1] == "set_value" and c[2]["value"] == 8.5 for c in calls)

    # The controller reports a finished cook on food1: a journal entry with the pork, not the chicken.
    summary = {"probe": "food1", "name": "Food 1", "profile": "Pork shoulder", "weight_kg": 3.86, "wrapped": False,
               "pit_c": 107.5, "target_c": 95, "stall_h": 3.2, "total_h": 11.5, "ambient_c": 4.0}
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(summary)})
    await hass.async_block_till_done()
    j = hass.data[DATA]
    entry = j.data["entries"][-1]
    assert entry["profile"] == "Pork shoulder" and entry["total_h"] == 11.5
    assert [i["name"] for i in entry["items"]] == ["Pork butt"]
    assert [i["name"] for i in j.data["draft"]["items"]] == ["Chicken thighs"]

    # Notes and rating from the page; the AI context sensor carries them.
    r = await client.post(f"/api/smoker/journal/{entry['id']}", json={"notes": "a bit dry", "rating": 3})
    assert r.status == 200
    st = hass.states.get("sensor.smoker_journal")
    assert st.state == "1" and st.attributes["recent"][-1]["notes"] == "a bit dry"
    r = await client.get("/api/smoker/journal")
    data = await r.json()
    assert data["entries"][0]["rating"] == 3

    # A garbled summary is ignored.
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": "not json"})
    await hass.async_block_till_done()
    assert len(j.data["entries"]) == 1


async def test_unload_and_reload(hass: HomeAssistant, tmp_path):
    entry = await _setup(hass, tmp_path)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps({"probe": "food1", "total_h": 1})})
    await hass.async_block_till_done()
    assert hass.data[DATA].data["entries"] == []  # not listening while unloaded
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps({"probe": "food1", "total_h": 1})})
    await hass.async_block_till_done()
    assert len(hass.data[DATA].data["entries"]) == 1
