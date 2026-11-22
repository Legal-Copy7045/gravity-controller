from pathlib import Path
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

    def photos():
        form = aiohttp.FormData()
        form.add_field("photo", b"\xff\xd8\xff fake jpeg", filename="a.jpg", content_type="image/jpeg")
        form.add_field("photo", b"\x89PNG fake", filename="b.png", content_type="image/png")
        return form

    # No AI task that can read photos (and no default set): a plain reason, not HA's "no preferred entity".
    r = await client.post("/api/smoker/identify", data=photos())
    assert r.status == 400 and "no AI in Home Assistant that can read photos" in (await r.json())["message"]
    hass.states.async_set("ai_task.text_only", "unknown", {"supported_features": 1})
    hass.states.async_set("ai_task.vision", "unknown", {"supported_features": 3})
    r = await client.post("/api/smoker/identify", data=photos())
    assert r.status == 200, await r.text()
    assert seen["entity_id"] == "ai_task.vision"  # picked one that can read photos
    body = await r.json()
    assert [i["name"] for i in body["items"]] == ["Pork butt", "Chicken thighs"]
    assert len(seen["attachments"]) == 2
    assert seen["attachments"][0]["media_content_id"].startswith("media-source://media_source/local/smoker_scans/")
    assert (tmp_path / "media" / "smoker_scans").is_dir()
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

    r = await client.post(f"/api/smoker/journal/{entry['id']}", json={"rating": "abc"})
    assert r.status == 400

    # Draft ids end up in the page's markup: anything but short hex is replaced.
    r = await client.post("/api/smoker/draft", json={"items": [{"id": "'+alert()+'", "name": "x", "probe": "food1'"}]})
    assert r.status == 200
    d = await r.json()
    assert d["items"][0]["id"] != "'+alert()+'" and all(c in "0123456789abcdef" for c in d["items"][0]["id"])
    assert d["items"][0]["probe"] is None

    # A photo over the limit is refused without reading all of it.
    from custom_components.smoker import journal as jmod
    big = aiohttp.FormData()
    big.add_field("photo", b"\xff" * (jmod.MAX_PHOTO_BYTES + 1), filename="c.jpg", content_type="image/jpeg")
    assert (await client.post("/api/smoker/identify", data=big)).status == 413

    # The user's own grill photo (www/smoker/grill.*): reported only when it's there.
    # (the test config folder is shared between runs: remove the photo again whatever happens)
    pic = Path(hass.config.path("www", "smoker", "grill.jpg"))
    pic.unlink(missing_ok=True)
    try:
        assert (await (await client.get("/api/smoker/grill_photo")).json()) == {"url": None}
        pic.parent.mkdir(parents=True, exist_ok=True)
        pic.write_bytes(b"\xff\xd8\xff fake jpeg")
        url = (await (await client.get("/api/smoker/grill_photo")).json())["url"]
        assert url.startswith("/local/smoker/grill.jpg?v="), url
    finally:
        pic.unlink(missing_ok=True)

    # Uploading a grill photo from the dashboard: stored by the integration, served without a login (the controller's
    # own page loads it from another address), replaced by the next upload, removed by an admin.
    form = aiohttp.FormData()
    form.add_field("photo", b"\xff\xd8\xff fake grill jpeg", filename="grill.jpg", content_type="image/jpeg")
    r = await client.post("/api/smoker/grill_photo", data=form)
    assert r.status == 200, await r.text()
    url = (await r.json())["url"]
    assert url.startswith("/api/smoker/grill_photo/image?v="), url
    assert (await (await client.get("/api/smoker/grill_photo")).json())["url"] == url
    img = await client.get("/api/smoker/grill_photo/image")
    assert img.status == 200 and (await img.read()).startswith(b"\xff\xd8\xff")
    bad = aiohttp.FormData()
    bad.add_field("photo", b"<svg/>", filename="x.svg", content_type="image/svg+xml")
    assert (await client.post("/api/smoker/grill_photo", data=bad)).status == 400  # only JPEG/PNG/WebP
    assert (await client.delete("/api/smoker/grill_photo")).status == 200
    assert (await (await client.get("/api/smoker/grill_photo")).json())["url"] is None
    assert (await client.get("/api/smoker/grill_photo/image")).status == 404

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


def test_bundled_package_matches_repo():
    root = Path(__file__).resolve().parents[2]
    assert (root / "custom_components/smoker/package/smoker.yaml").read_text() == \
        (root / "homeassistant/packages/smoker.yaml").read_text(), \
        "copy homeassistant/packages/smoker.yaml to custom_components/smoker/package/smoker.yaml"


async def test_install_package(hass: HomeAssistant, tmp_path):
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  packages: !include_dir_named packages\n")
    await _setup(hass, tmp_path)
    with pytest.raises(HomeAssistantError):  # the phone is required the first time
        await hass.services.async_call(DOMAIN, "install_package", {}, blocking=True, return_response=True)
    res = await hass.services.async_call(DOMAIN, "install_package", {"notify": "notify.mobile_app_test_phone"},
                                         blocking=True, return_response=True)
    pkg = tmp_path / "packages/smoker.yaml"
    text = pkg.read_text()
    assert res["changed"] and res["packages_loaded"] and res["backup"] is None
    assert "notify.mobile_app_test_phone" in text and "notify.mobile_app_your_phone" not in text
    assert "ai_task.google_ai_task" in text and text.startswith("# Installed by the Smoker integration")
    # Again with no fields: same choices, nothing to do.
    res = await hass.services.async_call(DOMAIN, "install_package", {}, blocking=True, return_response=True)
    assert not res["changed"]
    # A new weather entity: the old file is kept as a backup, the phone stays.
    res = await hass.services.async_call(DOMAIN, "install_package", {"weather": "weather.other"},
                                         blocking=True, return_response=True)
    text = pkg.read_text()
    assert res["changed"] and res["backup"] and Path(res["backup"]).exists()
    assert "weather.other" in text and "weather.forecast_home" not in text and "notify.mobile_app_test_phone" in text
    with pytest.raises(Exception):
        await hass.services.async_call(DOMAIN, "install_package", {"notify": "light.kitchen"}, blocking=True,
                                       return_response=True)


async def test_package_kept_up_to_date(hass: HomeAssistant, tmp_path):
    """An integration update rewrites a package it installed (same choices) and reloads it; hand copies are left."""
    from custom_components.smoker import package_install as pi

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  packages: !include_dir_named packages\n")
    pkg = tmp_path / "packages/smoker.yaml"
    pkg.parent.mkdir()
    pkg.write_text("# my own copy\ninput_boolean: {}\n")
    await _setup(hass, tmp_path)
    res = await pi.async_update_installed(hass, "9.9.9")
    assert res.get("skipped") and pkg.read_text().startswith("# my own copy")

    await hass.services.async_call(DOMAIN, "install_package", {"notify": "notify.mobile_app_test_phone"},
                                   blocking=True, return_response=True)
    # Same content, newer version: nothing to do.
    assert not (await pi.async_update_installed(hass, "9.9.9"))["changed"]
    # The installed package is older than the bundled one: rewritten with the same phone, and reloaded.
    pkg.write_text(pkg.read_text().replace("Smoker AI advisor", "Old name"))
    reloaded = []
    hass.services.async_register("automation", "reload", lambda call: reloaded.append("automation"))
    res = await pi.async_update_installed(hass, "9.9.9")
    text = pkg.read_text()
    assert res["changed"] and not res["restart_needed"] and reloaded == ["automation"]
    assert "Old name" not in text and "notify.mobile_app_test_phone" in text and "9.9.9" in text.split("\n", 1)[0]
    assert len(list(pkg.parent.glob("smoker.yaml.bak-*"))) <= pi.KEEP_BACKUPS
