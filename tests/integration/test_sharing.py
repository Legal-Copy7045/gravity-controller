"""Opt-in anonymous sharing: off by default, exactly the anonymised record goes out, deletion with the local key."""

import json
import time
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smoker import sharing
from custom_components.smoker.sharing import AGGREGATES_URL, SHARE_URL, anonymise, ready

from .open_pitmaster_format import validate

ROOT = Path(__file__).resolve().parents[2]
SUMMARY = {"probe": "food1", "name": "Food 1", "profile": "Pork shoulder", "weight_kg": 3.82, "wrapped": True,
           "pit_c": 121.3, "target_c": 95.0, "stall_h": 3.14, "total_h": 11.63, "ambient_c": 2.4}
ENTRY = {"id": "abc", "ended": 1795378582.0, "notes": "Great bark, at my brother Dave's", "rating": 4, **SUMMARY,
         "tags": ["great bark", "juicy", "not-a-tag"],
         "photos": ["x.jpg"], "items": [{"name": "Butt from Smith's"}]}


def test_anonymise_keeps_only_coarse_values():
    r = anonymise(ENTRY, "0.2.25", 40.8)
    assert set(r) == {"v", "id", "grill", "release", "season", "cut", "weight_lb", "wrapped", "pit_f", "target_f",
                      "stall_h", "total_h", "outside_f", "rating", "tags"}
    assert r["tags"] == ["juicy", "great bark"]  # known tags only, in the list's order
    assert r["weight_lb"] == 8.5 and r["pit_f"] == 250 and r["target_f"] == 203 and r["stall_h"] == 3.1
    assert r["total_h"] == 11.6 and r["outside_f"] == 35 and r["season"] == "autumn" and r["rating"] == 4
    text = json.dumps(r)
    for leak in ("Dave", "Smith", "x.jpg", "abc", "1795378582", "Food 1", "food1"):
        assert leak not in text
    # Southern hemisphere flips the season; a fresh id every time unless one is given.
    assert anonymise(ENTRY, "0.2.25", -33.9)["season"] == "spring"
    assert anonymise(ENTRY, "0.2.25", 40.8)["id"] != r["id"]
    # Extremes are clamped (rare cooks generalised), nonsense left out.
    odd = anonymise({**ENTRY, "weight_kg": 20, "ambient_c": -40, "pit_c": 20, "stall_h": 30, "profile": "Wagyu"}, "0.2.25", 40)
    assert odd["weight_lb"] == 25 and odd["outside_f"] == -10 and odd["pit_f"] is None and odd["stall_h"] == odd["total_h"]
    assert odd["cut"] == "Auto"
    assert anonymise({**ENTRY, "total_h": 0}, "0.2.25", 40) is None


def test_records_follow_the_open_pitmaster_format():
    """The service refuses anything else; the examples are a copy of open-pitmaster's format/examples.json."""
    ex = json.loads((ROOT / "tests/fixtures/open_pitmaster_examples.json").read_text())
    for r in ex["valid"]:
        assert validate(r) is None
    for change, why in ex["invalid"]:
        assert why in (validate({**ex["valid"][0], **change}) or "")
    for e in (ENTRY, {**ENTRY, "weight_kg": None, "rating": None, "wrapped": None, "stall_h": None, "ambient_c": None,
                      "pit_c": None, "tags": []}, {**ENTRY, "weight_kg": 50, "ambient_c": -60, "total_h": 99}):
        assert validate(anonymise(e, "0.2.26", 40.8)) is None


def test_ready_waits_for_feedback():
    now = time.time()
    assert not ready({"ended": now - 3600, "rating": None, "tags": []}, now)
    assert ready({"ended": now - 3600, "rating": 3, "tags": []}, now)
    assert ready({"ended": now - 3600, "rating": None, "tags": ["dry"]}, now)
    assert ready({"ended": now - 13 * 3600, "rating": None, "tags": []}, now)


async def _setup(hass, tmp_path, aioclient_mock):
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    hass.config.latitude = 40.8
    aioclient_mock.clear_requests()  # replaces the offline default from conftest
    aioclient_mock.get(AGGREGATES_URL, json={"v": 1, "cooks": 42, "updated": "2026-11-23", "groups": [
        {"cut": "Pork shoulder", "weight": "8-10 lb", "pit": "225-250°F", "outside": "30-50°F", "n": 12, "total_h": 11.2,
         "total_p25": 10.1, "total_p75": 12.6, "stall_h": 2.8, "wrapped_pct": 58}]})
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(domain="smoker", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_opt_in_share_withdraw(hass: HomeAssistant, hass_client, hass_admin_user, aioclient_mock, tmp_path):
    await _setup(hass, tmp_path, aioclient_mock)
    client = await hass_client()
    # Community averages arrive whether or not you share.
    st = hass.states.get("sensor.smoker_community")
    assert st.state == "42" and "Pork shoulder 8-10 lb" in st.attributes["similar"][0]

    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(SUMMARY)})
    await hass.async_block_till_done()
    summary = await (await client.get("/api/smoker/sharing")).json()
    assert summary["enabled"] is False and summary["entries"][0]["status"] == "waiting"  # no feedback yet
    entry_id = summary["entries"][0]["entry"]
    r = await client.post(f"/api/smoker/journal/{entry_id}", json={"rating": 5, "tags": ["tender", "juicy", "nope"]})
    assert r.status == 400  # unknown tag
    r = await client.post(f"/api/smoker/journal/{entry_id}", json={"rating": 5, "tags": ["tender", "juicy"]})
    assert (await r.json())["tags"] == ["juicy", "tender"]
    summary = await (await client.get("/api/smoker/sharing")).json()
    assert summary["entries"][0]["status"] == "pending" and summary["entries"][0]["record"]["tags"] == ["juicy", "tender"]
    # Off by default: nothing can be sent.
    r = await client.post(f"/api/smoker/sharing/share/{entry_id}")
    assert r.status == 400 and "sharing is off" in (await r.json())["message"]
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "POST"]

    # Opt in, share this cook: exactly the previewed record goes out, with a hash of the key (never the key).
    preview = summary["entries"][0]["record"]
    aioclient_mock.post(SHARE_URL + "/v1/cooks", status=201, json={"ok": True})
    assert (await client.post("/api/smoker/sharing", json={"enabled": True})).status == 200
    s = await (await client.post(f"/api/smoker/sharing/share/{entry_id}")).json()
    assert s["entries"][0]["status"] == "shared" and s["shared"] == 1
    sent = [c for c in aioclient_mock.mock_calls if c[0] == "POST"][-1][2]
    assert set(sent) == {"record", "key_hash"} and len(sent["key_hash"]) == 64
    assert {k: v for k, v in sent["record"].items() if k != "id"} == {k: v for k, v in preview.items() if k != "id"}
    key = hass.data[sharing.DATA].data["shared"][entry_id]["key"]
    assert key not in json.dumps(sent)

    # The export is the same kind of record, with fresh ids.
    ex = await (await client.get("/api/smoker/sharing/export")).json()
    assert ex["records"][0]["id"] != sent["record"]["id"] and ex["records"][0]["cut"] == "Pork shoulder"

    # Withdraw: a DELETE with the key for each shared cook.
    aioclient_mock.delete(f"{SHARE_URL}/v1/cooks/{sent['record']['id']}", status=200, json={"ok": True})
    w = await (await client.post("/api/smoker/sharing/withdraw")).json()
    assert w["removed"] == 1 and w["shared"] == 0 and w["entries"][0]["status"] == "declined"
    d = [c for c in aioclient_mock.mock_calls if c[0] == "DELETE"][-1]
    assert d[3]["X-Delete-Key"] == key


async def test_auto_share_and_non_admin(hass: HomeAssistant, hass_client, hass_admin_user, aioclient_mock, tmp_path):
    await _setup(hass, tmp_path, aioclient_mock)
    client = await hass_client()
    aioclient_mock.post(SHARE_URL + "/v1/cooks", status=201, json={"ok": True})
    # A cook from before automatic sharing was turned on is never sent automatically.
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(SUMMARY)})
    await hass.async_block_till_done()
    old = hass.data["smoker_journal_data"].data["entries"][-1]
    old["ended"] -= 86400
    await client.post("/api/smoker/sharing", json={"enabled": True, "auto": True})
    await client.post(f"/api/smoker/journal/{old['id']}", json={"rating": 3})
    await hass.async_block_till_done()
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    # A new cook: waits for feedback, then goes by itself.
    hass.bus.async_fire("esphome.smoker_cook_complete", {"summary": json.dumps(SUMMARY)})
    await hass.async_block_till_done()
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    new = hass.data["smoker_journal_data"].data["entries"][-1]
    await client.post(f"/api/smoker/journal/{new['id']}", json={"tags": ["dry"]})
    await hass.async_block_till_done()
    assert [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    st = {e["entry"]: e["status"] for e in (await (await client.get("/api/smoker/sharing")).json())["entries"]}
    assert st[new["id"]] == "shared" and st[old["id"]] == "pending"
    # Only an administrator can turn sharing on or withdraw.
    hass_admin_user.groups = []
    assert (await client.post("/api/smoker/sharing", json={"enabled": False})).status == 403


async def test_check_sends_a_test_record_only(hass: HomeAssistant, hass_client, aioclient_mock, tmp_path):
    await _setup(hass, tmp_path, aioclient_mock)
    aioclient_mock.post(SHARE_URL + "/v1/cooks", status=202, json={"ok": True, "test": True})
    r = await (await (await hass_client()).get("/api/smoker/sharing/check")).json()
    assert r["ok"] is True
    sent = [c for c in aioclient_mock.mock_calls if c[0] == "POST"][-1][2]
    assert sent["test"] is True
    assert hass.data[sharing.DATA].data["enabled"] is False  # checking doesn't turn anything on
