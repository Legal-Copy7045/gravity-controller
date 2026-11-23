from pathlib import Path
"""Smoker integration: panel, journal, draft from scanned packages, photo identification (AI mocked)."""

import json
import re

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


def _jpeg(color=(200, 90, 40), gps=False) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    exif = Image.Exif()
    if gps:
        exif[0x8825] = {2: (40.0, 26.0, 0.0)}  # GPSInfo: latitude
    Image.new("RGB", (40, 30), color).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


async def test_journal_flow(hass: HomeAssistant, hass_client, hass_client_no_auth, hass_admin_user, tmp_path, smoker_device_id,
                            other_device_id):
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
        form.add_field("photo", _jpeg(gps=True), filename="a.jpg", content_type="image/jpeg")
        form.add_field("photo", _png(), filename="b.png", content_type="image/png")
        return form

    # No AI task that can read photos (and no default set): a plain reason, not HA's "no preferred entity".
    r = await client.post("/api/smoker/identify", data=photos())
    assert r.status == 400 and "no AI in Home Assistant that can read photos" in (await r.json())["message"]
    hass.states.async_set("ai_task.text_only", "unknown", {"supported_features": 1})
    hass.states.async_set("ai_task.vision", "unknown", {"supported_features": 3})
    # Only an AI task Home Assistant has can be asked for by name.
    r = await client.post("/api/smoker/identify?ai_task=notify.somebody", data=photos())
    assert r.status == 400 and "no AI task called" in (await r.json())["message"]
    r = await client.post("/api/smoker/identify?ai_task=ai_task.missing", data=photos())
    assert r.status == 400 and not seen
    # Not a picture: refused before anything is saved or sent.
    junk = aiohttp.FormData()
    junk.add_field("photo", b"\xff\xd8\xff not really a jpeg", filename="j.jpg", content_type="image/jpeg")
    r = await client.post("/api/smoker/identify", data=junk)
    assert r.status == 400 and "couldn't read that photo" in (await r.json())["message"] and not seen
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
    from PIL import Image as _Image
    import io as _io

    # Saved (and sent to the AI) without the EXIF location the phone put in it.
    assert len(_Image.open(_io.BytesIO(await r.read())).getexif()) == 0
    saved = (tmp_path / "media" / "smoker_scans" / photo).read_bytes()
    assert len(_Image.open(_io.BytesIO(saved)).getexif()) == 0
    assert body["draft"]["photos"][1].endswith(".png")
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
    j = hass.data[DATA]
    # Another ESPHome device (or none) can't add a cook to the journal.
    for data in ({"summary": json.dumps(summary)}, {"summary": json.dumps(summary), "device_id": other_device_id}):
        hass.bus.async_fire("esphome.smoker_cook_complete", data)
        await hass.async_block_till_done()
    assert j.data["entries"] == []
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(summary), "device_id": smoker_device_id})
    await hass.async_block_till_done()
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
    # ...and so are photos that are too big together.
    many = aiohttp.FormData()
    for k in range(5):
        many.add_field("photo", b"\xff" * (jmod.MAX_PHOTO_BYTES - 10), filename=f"m{k}.jpg", content_type="image/jpeg")
    r = await client.post("/api/smoker/identify", data=many)
    assert r.status == 413 and "together" in (await r.json())["message"]

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

    # Uploading a grill photo from the dashboard (an admin): stored by the integration, served without a login (the
    # controller's own page loads it from another address) but only at its address with a secret part, replaced by
    # the next upload (a new address), removed by an admin.
    import io

    from PIL import Image

    def grill_form(body):
        form = aiohttp.FormData()
        form.add_field("photo", body, filename="grill.jpg", content_type="image/jpeg")
        return form

    # A real JPEG with a GPS tag in its EXIF: stored re-encoded, without it.
    gps = _jpeg(gps=True)
    assert len(Image.open(io.BytesIO(gps)).getexif()) > 0
    r = await client.post("/api/smoker/grill_photo", data=grill_form(gps))
    assert r.status == 200, await r.text()
    url = (await r.json())["url"]
    assert re.fullmatch(r"/api/smoker/grill_photo/image/[0-9a-f]{32}\?v=\d+", url), url
    assert (await (await client.get("/api/smoker/grill_photo")).json())["url"] == url
    anon = await hass_client_no_auth()  # no login, like the controller
    img = await anon.get(url)
    got = await img.read()
    assert img.status == 200 and got.startswith(b"\xff\xd8\xff") and "public" not in img.headers["Cache-Control"]
    assert len(Image.open(io.BytesIO(got)).getexif()) == 0  # no EXIF (no location) in what's served
    for wrong in ("/api/smoker/grill_photo/image", "/api/smoker/grill_photo/image/" + "0" * 32,
                  "/api/smoker/grill_photo/image/" + url.split("/")[-1].split("?")[0][:-1] + "é"):
        assert (await anon.get(wrong)).status in (401, 404), wrong
    # A new photo, a new address: the old one stops working.
    r = await client.post("/api/smoker/grill_photo", data=grill_form(_jpeg((10, 20, 30))))
    url2 = (await r.json())["url"]
    assert url2.split("?")[0] != url.split("?")[0] and (await anon.get(url)).status == 404
    assert (await anon.get(url2)).status == 200
    bad = aiohttp.FormData()
    bad.add_field("photo", b"<svg/>", filename="x.svg", content_type="image/svg+xml")
    assert (await client.post("/api/smoker/grill_photo", data=bad)).status == 400  # only JPEG/PNG/WebP
    # Something that only says it's a JPEG, and a "decompression bomb" (a huge picture in a small file): refused.
    assert (await client.post("/api/smoker/grill_photo", data=grill_form(b"\xff\xd8\xff nope"))).status == 400
    buf = io.BytesIO()
    Image.new("1", (8000, 6000)).save(buf, "PNG")  # 48 megapixels, a few kB
    form = aiohttp.FormData()
    form.add_field("photo", buf.getvalue(), filename="bomb.png", content_type="image/png")
    r = await client.post("/api/smoker/grill_photo", data=form)
    assert r.status == 400 and "pixels" in (await r.json())["message"]
    # Only an administrator can change it.
    hass_admin_user.groups = []
    assert (await client.post("/api/smoker/grill_photo", data=grill_form(_jpeg()))).status == 403
    assert (await client.delete("/api/smoker/grill_photo")).status == 403
    from homeassistant.auth.const import GROUP_ID_ADMIN

    hass_admin_user.groups = [await hass.auth.async_get_group(GROUP_ID_ADMIN)]
    assert (await client.delete("/api/smoker/grill_photo")).status == 200
    assert (await (await client.get("/api/smoker/grill_photo")).json())["url"] is None
    assert (await anon.get(url2)).status == 404

    # A garbled summary is ignored, and odd values in one are left out or cut short.
    for bad in ("not json", "[1, 2]", json.dumps({"total_h": "lots"}) + "x"):
        hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": bad, "device_id": smoker_device_id})
        await hass.async_block_till_done()
    assert len(j.data["entries"]) == 1
    odd = {"probe": "food1'><script>", "name": "N" * 500, "profile": "Wagyu<script>", "weight_kg": "heavy",
           "pit_c": float("nan"), "target_c": True, "stall_h": -3, "total_h": 1e9, "wrapped": "yes", "ambient_c": 21}
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(odd), "device_id": smoker_device_id})
    await hass.async_block_till_done()
    e = j.data["entries"][-1]
    assert e["probe"] is None and len(e["probe_name"]) == 40 and e["profile"] == "Auto" and e["ambient_c"] == 21
    assert all(e[k] is None for k in ("weight_kg", "pit_c", "target_c", "stall_h", "wrapped")) and e["total_h"] == 0


async def test_one_scan_at_a_time(hass: HomeAssistant, hass_client, tmp_path):
    """Each scan is an AI call: a user's second scan waits for the first."""
    import asyncio

    import aiohttp

    await _setup(hass, tmp_path)
    client = await hass_client()
    hass.states.async_set("ai_task.vision", "unknown", {"supported_features": 3})
    gate, seen = asyncio.Event(), []

    async def slow(call: ServiceCall):
        seen.append(call.context.user_id)
        await gate.wait()
        return {"data": "Ribs | Ribs | 3 | |"}

    hass.services.async_register("ai_task", "generate_data", slow, supports_response=SupportsResponse.ONLY)

    def form():
        f = aiohttp.FormData()
        f.add_field("photo", _jpeg(), filename="a.jpg", content_type="image/jpeg")
        return f

    first = asyncio.ensure_future(client.post("/api/smoker/identify", data=form()))
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen and seen[0] is not None  # asked as the user who sent it (their context)
    r = await client.post("/api/smoker/identify", data=form())
    assert r.status == 429
    gate.set()
    assert (await first).status == 200
    assert (await client.post("/api/smoker/identify", data=form())).status == 200


async def test_unload_and_reload(hass: HomeAssistant, tmp_path, smoker_device_id):
    entry = await _setup(hass, tmp_path)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps({"probe": "food1", "total_h": 1}),
                                                          "device_id": smoker_device_id})
    await hass.async_block_till_done()
    assert hass.data[DATA].data["entries"] == []  # not listening while unloaded
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps({"probe": "food1", "total_h": 1}),
                                                          "device_id": smoker_device_id})
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
    # Edited by hand after it was installed: left alone, with a notification (never overwritten automatically).
    mine = pkg.read_text().replace("Smoker AI advisor", "My advisor")
    pkg.write_text(mine)
    res = await pi.async_update_installed(hass, "9.9.9")
    assert res.get("edited") and pkg.read_text() == mine
    # The installed package is older than the bundled one: rewritten with the same phone, and reloaded.
    old_bundled = pi.BUNDLED.read_text().replace("Smoker AI advisor", "Old name")
    pkg.write_text(pi.render(old_bundled, {"notify": "notify.mobile_app_test_phone"}, "0.0.1"))
    reloaded = []
    hass.services.async_register("automation", "reload", lambda call: reloaded.append("automation"))
    res = await pi.async_update_installed(hass, "9.9.9")
    text = pkg.read_text()
    assert res["changed"] and not res["restart_needed"] and reloaded == ["automation"]
    assert "Old name" not in text and "notify.mobile_app_test_phone" in text and "9.9.9" in text.split("\n", 1)[0]
    assert len(list(pkg.parent.glob("smoker.yaml.bak-*"))) <= pi.KEEP_BACKUPS


def test_photos_only_in_phone_formats():
    """Only JPEG/PNG/WebP (and MPO) photos are opened; anything else Pillow could read is refused unread."""
    import io

    import pytest
    from PIL import Image

    from custom_components.smoker.journal import MAX_PIXELS, strip_metadata

    def make(fmt, size=(8, 8)):
        b = io.BytesIO()
        Image.new("RGB", size, (200, 80, 40)).save(b, fmt)
        return b.getvalue()

    for fmt in ("JPEG", "PNG", "WEBP"):
        assert strip_metadata(make(fmt), "jpg")[0]
    for fmt in ("GIF", "BMP", "TIFF", "PPM"):
        with pytest.raises(ValueError):
            strip_metadata(make(fmt), "jpg")
    assert MAX_PIXELS == 24_000_000
    with pytest.raises(ValueError, match="too many pixels"):
        strip_metadata(make("PNG", (6000, 4001)), "png")


async def test_controller_events_checked_and_signed(hass: HomeAssistant, tmp_path, smoker_device_id, other_device_id):
    """esphome.smoker_* events are passed on (as smoker_controller_*) only from the smoker controller, fired inside
    Home Assistant; once the controller has sent the event secret, only events carrying it."""
    from homeassistant.core import Context, EventOrigin

    from custom_components.smoker import controller_events as ce

    pushed = []

    async def set_secret(call: ServiceCall):
        pushed.append(call.data["secret"])

    hass.services.async_register("esphome", "gravity980_set_event_secret", set_secret)
    await _setup(hass, tmp_path)
    await hass.async_block_till_done()
    c = hass.data[ce.DATA]
    assert len(c.secret) == 32 and pushed == [c.secret]  # handed to the controller (it has the action)
    got = []
    hass.bus.async_listen("smoker_controller_notify", lambda e: got.append(dict(e.data)))

    async def fire(data, origin=EventOrigin.local, context=None):
        hass.bus.async_fire("esphome.smoker_notify", {"title": "t", "message": "m", **data}, origin, context)
        await hass.async_block_till_done()

    # Older firmware (no secret yet): taken from the smoker controller only, and only when fired inside HA.
    await fire({"device_id": other_device_id})
    await fire({"device_id": smoker_device_id}, EventOrigin.remote)
    await fire({"device_id": smoker_device_id}, context=Context(user_id="0123456789abcdef0123456789abcdef"))
    assert got == []
    await fire({"device_id": smoker_device_id})
    assert len(got) == 1 and got[0]["device_id"] == smoker_device_id
    # A wrong secret is never taken.
    await fire({"device_id": smoker_device_id, "secret": "0" * 32})
    assert len(got) == 1
    # The controller sends the secret: passed on without it, and from now on it's required.
    await fire({"device_id": smoker_device_id, "secret": c.secret})
    assert len(got) == 2 and "secret" not in got[1] and c.confirmed
    await fire({"device_id": smoker_device_id})
    assert len(got) == 2
    # The journal takes finished cooks from the checked event only.
    j = hass.data[DATA]
    n = len(j.data["entries"])
    summary = json.dumps({"probe": "food1", "total_h": 1})
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": summary, "device_id": smoker_device_id})
    hass.bus.async_fire("smoker_controller_cook_complete", {"summary": summary, "device_id": smoker_device_id},
                        EventOrigin.remote)
    await hass.async_block_till_done()
    assert len(j.data["entries"]) == n
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": summary, "device_id": smoker_device_id,
                                                         "secret": c.secret})
    await hass.async_block_till_done()
    assert len(j.data["entries"]) == n + 1
    # The secret is pushed again whenever the controller (re)connects and registers its actions.
    hass.services.async_remove("esphome", "gravity980_set_event_secret")
    hass.services.async_register("esphome", "gravity980_set_event_secret", set_secret)
    await hass.async_block_till_done()
    assert pushed == [c.secret, c.secret]


async def test_install_package_checks(hass: HomeAssistant, tmp_path):
    """The phone placeholder is never installed; an install without a fingerprint counts as edited; a missing package
    shows in Repairs until it's installed."""
    import pytest
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import issue_registry as ir

    from custom_components.smoker import package_install as pi

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  packages: !include_dir_named packages\n")
    await _setup(hass, tmp_path)
    await pi.async_check_installed(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, pi.ISSUE)
    with pytest.raises(HomeAssistantError, match="Developer tools"):
        await hass.services.async_call(DOMAIN, "install_package", {"notify": "notify.mobile_app_your_phone"},
                                       blocking=True, return_response=True)
    await hass.services.async_call(DOMAIN, "install_package", {"notify": "notify.mobile_app_test_phone"},
                                   blocking=True, return_response=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, pi.ISSUE) is None
    # An older install recorded the placeholder as its phone: it's asked for again.
    assert "notify" not in pi._previous_choices(pi.MARK + " 0.1: notify=notify.mobile_app_your_phone, ai_task=ai_task.x")
    # Installed before fingerprints were recorded: can't tell if it was edited, so it's left alone.
    old = pi.MARK + " 0.2.10: notify=notify.mobile_app_test_phone\n# Re-run...\ninput_boolean: {}\n"
    assert pi.edited(old)
    pkg = tmp_path / "packages/smoker.yaml"
    pkg.write_text(old)
    res = await pi.async_update_installed(hass, "9.9.9")
    assert res.get("edited") and pkg.read_text() == old


async def test_set_device_pin(hass: HomeAssistant, tmp_path, hass_admin_user, hass_read_only_user, caplog):
    """smoker.set_device_pin hands the PIN to the controller's set_device_pin action (admin only): checked first with
    the controller's own rules, empty clears it, and the PIN never shows in the log or an error."""
    import logging

    import pytest
    from homeassistant.core import Context
    from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized

    from custom_components.smoker.device_pin import pin_problem

    caplog.set_level(logging.DEBUG)
    await _setup(hass, tmp_path)
    assert hass.services.has_service(DOMAIN, "set_device_pin")
    admin = Context(user_id=hass_admin_user.id)
    # The controller isn't connected (or its firmware is older): said so, nothing sent.
    with pytest.raises(HomeAssistantError, match="firmware"):
        await hass.services.async_call(DOMAIN, "set_device_pin", {"pin": "482913"}, blocking=True, context=admin)
    sent = []

    async def set_pin(call: ServiceCall):
        sent.append(call.data["pin"])

    hass.services.async_register("esphome", "gravity980_set_device_pin", set_pin)
    await hass.services.async_call(DOMAIN, "set_device_pin", {"pin": "k3v9-x2q7"}, blocking=True, context=admin)
    await hass.services.async_call(DOMAIN, "set_device_pin", {"pin": 482913}, blocking=True, context=admin)  # a YAML number
    await hass.services.async_call(DOMAIN, "set_device_pin", {"pin": ""}, blocking=True, context=admin)    # clears it
    await hass.services.async_call(DOMAIN, "set_device_pin", {}, blocking=True, context=admin)
    assert sent == ["k3v9-x2q7", "482913", "", ""]
    # The controller's rules: 6 to 32 characters, not repeated or in sequence. Refused here, never sent.
    for bad in ("12345", "123456", "654321", "aaaaaaa", "abcdefg", "x" * 33, "s3cr3t-but-far-too-long-for-the-pin"):
        assert pin_problem(bad)
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(DOMAIN, "set_device_pin", {"pin": bad}, blocking=True, context=admin)
        assert bad not in str(err.value)
    assert pin_problem("482913") == "" and pin_problem("x" * 31 + "1") == "" and pin_problem("") == ""
    assert len(sent) == 4
    # Admin only.
    with pytest.raises(Unauthorized):
        await hass.services.async_call(DOMAIN, "set_device_pin", {"pin": "739215"}, blocking=True,
                                       context=Context(user_id=hass_read_only_user.id))
    assert len(sent) == 4
    for pin in ("k3v9-x2q7", "482913", "739215", "s3cr3t-but-far-too-long"):
        assert pin not in caplog.text
    # Removed with the integration.
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "set_device_pin")
