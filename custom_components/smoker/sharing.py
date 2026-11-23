"""Open Pitmaster: anonymous, opt-in sharing of finished cooks, and the averages built from everyone's shared cooks.

Off until the owner turns it on (Setup > Share cooks). A cook is ready to share once it has feedback (stars or
"How was it?" tags) or 12 h after it ended; then it's offered on the page ("Share this cook?") or, with "share
automatically", sent (automatic sharing covers only cooks that end after it was turned on, never your history). What is sent is ONLY the record built by
`anonymise()`: rounded, banded values with no date, time, place, notes, photos, names or ids that link cooks.
docs/sharing.md describes it; the receiving service (github.com/Legal-Copy7045/open-pitmaster) refuses anything else.

Each shared cook gets a fresh random id and a deletion key that never leaves this Home Assistant except to delete
it ("Remove my shared cooks"). Withdrawal deletes every cook shared from here.

The community averages (aggregates.json, built nightly from all shared cooks) are fetched whether or not you share,
and published as sensor.smoker_community for the AI pitmaster's prompts.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import secrets
import time
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientTimeout, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .journal import TAGS

_LOGGER = logging.getLogger(__name__)

DATA = "smoker_sharing"
# Open Pitmaster (github.com/Legal-Copy7045/open-pitmaster): the receiving service and the nightly averages.
SHARE_URL = "https://api.open-pitmaster.workers.dev"
AGGREGATES_URL = "https://raw.githubusercontent.com/Legal-Copy7045/open-pitmaster/main/data/aggregates.json"
PRIVACY_URL = "https://github.com/Legal-Copy7045/gravity-controller/blob/main/docs/sharing.md"
CUTS = {"Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish", "Auto"}
TIMEOUT = ClientTimeout(total=20)
READY_AFTER = 12 * 3600  # a cook without feedback is offered this long after it ended
SETTLE = 600  # automatic sharing waits this long after the last star/tag/note change (seconds)



def _band(v: float | None, step: float, lo: float, hi: float, floor: bool = False) -> float | None:
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    q = (v // step) * step if floor else round(v / step) * step
    q = min(hi, max(lo, q))
    return round(q, 1) if step < 1 else int(round(q))


def _season(ts: float, latitude: float) -> str:
    month = dt_util.as_local(dt_util.utc_from_timestamp(ts)).month
    north = ["winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer", "autumn", "autumn", "autumn", "winter"]
    s = north[month - 1]
    if latitude < 0:
        s = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}[s]
    return s


def anonymise(entry: dict[str, Any], release: str, latitude: float, record_id: str | None = None) -> dict[str, Any] | None:
    """The only thing that ever leaves: rounded and banded, no time, place, notes, photos or names.

    None if the cook can't be shared (no total time, or out of range).
    """
    c2f = lambda c: None if c is None else float(c) * 9 / 5 + 32  # noqa: E731
    total = _band(entry.get("total_h"), 0.1, 0.5, 36)
    if total is None or not entry.get("total_h") or float(entry["total_h"]) < 0.5:
        return None
    stall = _band(entry.get("stall_h"), 0.1, 0, 24)
    if stall is not None and stall > total:
        stall = total
    weight = entry.get("weight_kg")
    rating = entry.get("rating")
    wrapped = entry.get("wrapped")
    cut = entry.get("profile") if entry.get("profile") in CUTS else "Auto"
    pit = c2f(entry.get("pit_c"))
    return {
        "v": 1,
        "id": record_id or secrets.token_hex(16),
        "grill": "gravity980",
        "release": release,
        "season": _season(float(entry.get("ended") or time.time()), latitude),
        "cut": cut,
        "weight_lb": _band(None if weight in (None, 0) else float(weight) * 2.20462, 0.5, 0.5, 25),
        "wrapped": wrapped if isinstance(wrapped, bool) else None,
        "pit_f": None if pit is None or pit < 200 else _band(pit, 5, 200, 700),
        "target_f": _band(c2f(entry.get("target_c")), 1, 100, 250),
        "stall_h": stall,
        "total_h": total,
        "outside_f": _band(c2f(entry.get("ambient_c")), 5, -10, 110, floor=True),
        "rating": rating if isinstance(rating, int) and 1 <= rating <= 5 else None,
        "tags": [t for t in TAGS if t in (entry.get("tags") or [])],
    }


# Group labels as open-pitmaster's build.py writes them (band(): "under 4 lb", "4-6 lb", "15+ lb", "any weight"...).
_BANDS = {
    "weight": re.compile(r"(under \d{1,3} lb|\d{1,3}-\d{1,3} lb|\d{1,3}\+ lb|any weight)"),
    "pit": re.compile(r"(under \d{3}°F|\d{3}-\d{3}°F|\d{3}\+°F|any pit)"),
    "outside": re.compile(r"(under -?\d{1,3}°F|-?\d{1,3}--?\d{1,3}°F|-?\d{1,3}\+°F|any weather)"),
}


def _fnum(v: Any, lo: float, hi: float, null: bool = False) -> bool:
    if v is None:
        return null
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and lo <= v <= hi


def valid_group(g: Any) -> bool:
    """One group of the downloaded averages, exactly as the builder makes it. Its text goes into the AI's prompts, so
    anything else (odd labels, unknown tags, nonsense numbers) is dropped rather than passed on. Never raises."""
    try:
        if not isinstance(g, dict) or g.get("cut") not in CUTS:
            return False
        if not all(isinstance(g.get(k), str) and rx.fullmatch(g[k]) for k, rx in _BANDS.items()):
            return False
        n = g.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or not 0 < n < 10_000_000:
            return False
        if not (_fnum(g.get("total_h"), 0, 72) and _fnum(g.get("total_p25"), 0, 72, True)
                and _fnum(g.get("total_p75"), 0, 72, True) and _fnum(g.get("stall_h"), 0, 72, True)
                and _fnum(g.get("wrapped_pct"), 0, 100, True) and _fnum(g.get("rating"), 1, 5, True)):
            return False
        tags = g.get("tags", {})
        if tags is None:
            tags = {}
        if not isinstance(tags, dict) or any(t not in TAGS or isinstance(p, bool) or not isinstance(p, int)
                                             or not 0 <= p <= 100 for t, p in tags.items()):
            return False
        return True
    except Exception:  # noqa: BLE001 - whatever it is, it's not a group we use
        return False


def ready(entry: dict, now: float | None = None) -> bool:
    """Feedback given (so the shared record says how it turned out), or long enough that none is coming."""
    now = time.time() if now is None else now
    return bool(entry.get("rating") or entry.get("tags")) or now - float(entry.get("ended") or 0) >= READY_AFTER


class Sharing:
    def __init__(self, hass: HomeAssistant, journal, version: str) -> None:
        self.hass, self.journal, self.version = hass, journal, version
        self.store = Store(hass, 1, "smoker_sharing")
        # shared: entry id -> {"id": record id, "key": deletion key}; the keys never leave except to delete.
        # auto_since: automatic sharing covers cooks that end after this (never the history from before).
        self.data: dict[str, Any] = {"enabled": False, "auto": False, "auto_since": None, "shared": {}, "declined": [],
                                     "url": ""}
        self.community: dict[str, Any] | None = None
        self._unsub = None
        self._sending: set[str] = set()      # entries being uploaded right now (one upload per cook)
        self._touched: dict[str, float] = {}  # entry id -> last feedback change (automatic sharing waits)

    @property
    def url(self) -> str:
        return (self.data.get("url") or SHARE_URL).rstrip("/")

    async def async_load(self) -> None:
        self.data.update(await self.store.async_load() or {})
        self.attach()

    def attach(self) -> None:
        if self._on_entry not in self.journal.listeners:
            self.journal.listeners.append(self._on_entry)
        if self._unsub is None:
            self._unsub = async_track_time_interval(self.hass, self._tick, timedelta(hours=1))
            self.hass.async_create_task(self._refresh_community())

    async def _tick(self, now=None) -> None:
        """Hourly: automatic sharing of cooks that became ready; the community averages every 12 h."""
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 12 == 0:
            await self._refresh_community()
        await self.share_ready()

    async def share_ready(self) -> int:
        if not (self.data["enabled"] and self.data["auto"]):
            return 0
        since = float(self.data.get("auto_since") or time.time())
        n = 0
        now = time.time()
        for e in list(self.journal.data["entries"]):
            # Wait SETTLE s after the last star/tag/note change, so a cook goes out with all its feedback at once.
            if now - self._touched.get(e["id"], 0) < SETTLE:
                continue
            if (float(e.get("ended") or 0) >= since and self.status(e) == "pending"):
                try:
                    await self.share(e["id"])
                    n += 1
                except ValueError as err:
                    _LOGGER.debug("Automatic sharing will retry: %s", err)
                    break
        return n

    def unload(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._on_entry in self.journal.listeners:
            self.journal.listeners.remove(self._on_entry)

    def _save(self) -> None:
        self.store.async_delay_save(lambda: self.data, 1)

    def record_for(self, entry: dict) -> dict | None:
        rid = (self.data["shared"].get(entry["id"]) or {}).get("id")
        return anonymise(entry, self.version, self.hass.config.latitude or 0.0, rid)

    def status(self, entry: dict) -> str:
        if entry["id"] in self.data["shared"]:
            return "shared"
        if entry["id"] in self.data["declined"]:
            return "declined"
        if not self.record_for(entry):
            return "ineligible"
        return "pending" if ready(entry) else "waiting"

    def summary(self) -> dict:
        entries = self.journal.data["entries"]
        return {
            "enabled": self.data["enabled"], "auto": self.data["auto"], "privacy": PRIVACY_URL,
            "shared": len(self.data["shared"]),
            "entries": [{"entry": e["id"], "status": self.status(e), "record": self.record_for(e)} for e in entries],
            "community": {k: (self.community or {}).get(k) for k in ("cooks", "updated")},
        }

    @callback
    def _on_entry(self, entry: dict, event: str = "new") -> None:
        if not (self.data["enabled"] and self.data["auto"]):
            return
        if entry and entry.get("id"):
            self._touched[entry["id"]] = time.time()
        # Shared once the feedback has settled (or by the hourly tick).
        async_call_later(self.hass, SETTLE + 5, self._settled)

    @callback
    def _settled(self, _now=None) -> None:
        self.hass.async_create_task(self.share_ready())

    async def share(self, entry_id: str) -> dict:
        if not self.data["enabled"]:
            raise ValueError("sharing is off: turn it on in Setup first")
        entry = next((e for e in self.journal.data["entries"] if e["id"] == entry_id), None)
        if entry is None:
            raise ValueError("no such cook")
        if entry_id in self.data["shared"]:
            return self.data["shared"][entry_id]
        if entry_id in self._sending:
            raise ValueError("already sending this cook")
        # The record id and deletion key are chosen once and saved before sending, so a retry (or a reply lost to a
        # timeout) re-sends the same record instead of a second copy whose key would be lost.
        pend = self.data.setdefault("pending", {})
        if entry_id not in pend:
            pend[entry_id] = {"id": secrets.token_hex(16), "key": secrets.token_hex(24)}
            self._save()
        rid, key = pend[entry_id]["id"], pend[entry_id]["key"]
        record = anonymise(entry, self.version, self.hass.config.latitude or 0.0, rid)
        if record is None:
            raise ValueError("this cook can't be shared (no total time recorded)")
        body = {"record": record, "key_hash": hashlib.sha256(key.encode()).hexdigest()}
        self._sending.add(entry_id)
        try:
            async with async_get_clientsession(self.hass).post(self.url + "/v1/cooks", json=body, timeout=TIMEOUT) as r:
                if r.status not in (201, 409):  # 409: this id is already stored (an earlier try got through)
                    raise ValueError(f"the sharing service said {r.status}: {(await r.text())[:200]}")
        except (ClientError, TimeoutError) as err:
            raise ValueError(f"couldn't reach the sharing service ({err.__class__.__name__}); try again later") from err
        finally:
            self._sending.discard(entry_id)
        pend.pop(entry_id, None)
        self.data["shared"][entry_id] = {"id": record["id"], "key": key}
        if entry_id in self.data["declined"]:
            self.data["declined"].remove(entry_id)
        self._save()
        return self.data["shared"][entry_id]

    async def check(self) -> dict:
        """Is the sharing service reachable and accepting the format? Sends a test record, which it never stores."""
        rec = anonymise({"total_h": 10.0, "profile": "Pork shoulder"}, self.version, 40.0)
        body = {"record": rec, "key_hash": hashlib.sha256(secrets.token_hex(8).encode()).hexdigest(), "test": True}
        try:
            async with async_get_clientsession(self.hass).post(self.url + "/v1/cooks", json=body, timeout=TIMEOUT) as r:
                return {"ok": r.status == 202, "status": r.status, "said": (await r.text())[:200]}
        except ClientError as err:
            return {"ok": False, "status": None, "said": err.__class__.__name__}

    def decline(self, entry_id: str) -> None:
        if entry_id not in self.data["declined"] and entry_id not in self.data["shared"]:
            self.data["declined"].append(entry_id)
            self._save()

    async def withdraw(self) -> dict:
        """Delete every cook shared from here (the deletion keys prove they're ours)."""
        gone, failed = 0, 0
        session = async_get_clientsession(self.hass)
        # Uploads whose reply was lost may be stored too: delete them as well (404 = never stored).
        for entry_id, s in list(self.data.get("pending", {}).items()):
            try:
                async with session.delete(f"{self.url}/v1/cooks/{s['id']}", headers={"X-Delete-Key": s["key"]},
                                          timeout=TIMEOUT) as r:
                    ok = r.status in (200, 404)
            except ClientError:
                ok = False
            if ok:
                del self.data["pending"][entry_id]
                if entry_id not in self.data["declined"]:
                    self.data["declined"].append(entry_id)
            else:
                failed += 1
        for entry_id, s in list(self.data["shared"].items()):
            try:
                async with session.delete(f"{self.url}/v1/cooks/{s['id']}", headers={"X-Delete-Key": s["key"]},
                                          timeout=TIMEOUT) as r:
                    ok = r.status in (200, 404)
            except ClientError:
                ok = False
            if ok:
                del self.data["shared"][entry_id]
                self.data["declined"].append(entry_id)
                gone += 1
            else:
                failed += 1
        self._save()
        return {"removed": gone, "failed": failed}

    def set(self, enabled: bool | None, auto: bool | None) -> None:
        if enabled is not None:
            if bool(enabled) and not self.data["enabled"]:
                # Turned back on: automatic sharing starts from now (never the cooks made while it was off).
                self.data["auto_since"] = time.time()
            self.data["enabled"] = bool(enabled)
        if auto is not None:
            if bool(auto) and not self.data["auto"]:
                self.data["auto_since"] = time.time()
            self.data["auto"] = bool(auto)
        self._save()

    def export(self) -> list[dict]:
        """Every cook as it would be shared (fresh ids: nothing here links to a shared copy)."""
        lat = self.hass.config.latitude or 0.0
        return [r for e in self.journal.data["entries"] if (r := anonymise(e, self.version, lat))]

    async def _refresh_community(self, _now=None) -> None:
        try:
            async with async_get_clientsession(self.hass).get(AGGREGATES_URL, timeout=TIMEOUT) as r:
                if r.status != 200:
                    return
                data = await r.json(content_type=None)
        except Exception:  # noqa: BLE001 - offline or odd answer: keep the last averages, try again later
            return
        if isinstance(data, dict) and data.get("v") == 1:
            groups = data.get("groups") if isinstance(data.get("groups"), list) else []
            cooks = data.get("cooks")
            self.community = {
                "v": 1,
                "cooks": cooks if isinstance(cooks, int) and not isinstance(cooks, bool) and cooks >= 0 else 0,
                "updated": data["updated"] if isinstance(data.get("updated"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["updated"]) else None,
                "groups": [g for g in groups if valid_group(g)],
            }
            self._publish_community()

    @callback
    def _publish_community(self) -> None:
        c = self.community or {}
        # Compact for the AI prompt: one line per group with enough cooks behind it.
        def line(g: dict) -> str:
            said = ", ".join(f"{t} {pct}%" for t, pct in list((g.get("tags") or {}).items())[:4])
            return (f"{g['cut']} {g['weight']} at {g['pit']} ({g['outside']} outside): median {g['total_h']} h"
                    + (f" (middle half {g['total_p25']}-{g['total_p75']} h)"
                       if g.get("total_p25") is not None and g.get("total_p75") is not None else "")
                    + (f", stall {g['stall_h']} h" if g.get("stall_h") is not None else "")
                    + (f", wrapped {g['wrapped_pct']}%" if g.get("wrapped_pct") is not None else "")
                    + (f", rated {g['rating']}/5" if g.get("rating") else "")
                    + (f", cooks said: {said}" if said else "") + f"; {g['n']} cooks")

        lines = [line(g) for g in (c.get("groups") or [])[:40]]
        self.hass.states.async_set("sensor.smoker_community", c.get("cooks", 0), {
            "friendly_name": "Smoker community cooks", "icon": "mdi:account-group", "unit_of_measurement": "cooks",
            "updated": c.get("updated"), "similar": lines, "source": PRIVACY_URL})


def _sharing(request: web.Request) -> Sharing:
    return request.app["hass"].data[DATA]


class SharingView(HomeAssistantView):
    """GET: settings, each cook's status and the exact record that would be (or was) sent. POST: turn on/off (admin)."""

    url = "/api/smoker/sharing"
    name = "api:smoker:sharing"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        return self.json(_sharing(request).summary())

    async def post(self, request: web.Request) -> web.Response:
        if not request["hass_user"].is_admin:
            return self.json_message("only an administrator can change sharing", 403)
        try:
            body = await request.json()
        except ValueError:
            return self.json_message("invalid JSON", 400)
        s = _sharing(request)
        s.set(body.get("enabled"), body.get("auto"))
        return self.json(s.summary())


class SharingActionView(HomeAssistantView):
    """POST share/<entry> | decline/<entry> | withdraw; GET export (your cooks, anonymised) | check (test upload)."""

    url = "/api/smoker/sharing/{action}"
    extra_urls = ["/api/smoker/sharing/{action}/{entry_id}"]
    name = "api:smoker:sharing:action"
    requires_auth = True

    async def get(self, request: web.Request, action: str, entry_id: str | None = None) -> web.Response:
        if action == "check":
            return self.json(await _sharing(request).check())
        if action != "export":
            return self.json_message("not found", 404)
        return self.json({"v": 1, "privacy": PRIVACY_URL, "records": _sharing(request).export()})

    async def post(self, request: web.Request, action: str, entry_id: str | None = None) -> web.Response:
        s = _sharing(request)
        try:
            if action == "share" and entry_id:
                # A cook the owner said no to ("Not this one") is shared only by an administrator.
                if entry_id in s.data["declined"] and not request["hass_user"].is_admin:
                    return self.json_message("only an administrator can share a cook that was declined", 403)
                await s.share(entry_id)
            elif action == "decline" and entry_id:
                s.decline(entry_id)
            elif action == "withdraw":
                if not request["hass_user"].is_admin:
                    return self.json_message("only an administrator can withdraw shared cooks", 403)
                return self.json({**await s.withdraw(), **s.summary()})
            else:
                return self.json_message("not found", 404)
        except ValueError as err:
            return self.json_message(str(err), 400)
        return self.json(s.summary())


async def async_setup_sharing(hass: HomeAssistant, journal, version: str) -> None:
    if DATA in hass.data:  # reloaded: views are still registered, listen again
        hass.data[DATA].attach()
        if hass.data[DATA].community:  # its sensor was removed with the entry: put the last averages back
            hass.data[DATA]._publish_community()
        return
    s = Sharing(hass, journal, version)
    await s.async_load()
    hass.data[DATA] = s
    hass.http.register_view(SharingView())
    hass.http.register_view(SharingActionView())


def async_unload_sharing(hass: HomeAssistant) -> None:
    s = hass.data.get(DATA)
    if s:
        s.unload()
