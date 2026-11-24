"""Cook replay: a finished cook's temperature curves and events, kept with the journal.

The dashboard replays a journal entry (the cook's curves with a scrubber, its events) and draws it on a picture to
share. Home Assistant's history has all of it, but only until the recorder purges it (10 days by default), so:

* when a cook finishes (journal.handle_cook_complete), shortly afterwards (once the recorder has written the last
  minutes) the cook's pit, pit target and food temperatures and its events are read from the history and kept,
  compact, in their own store (.storage/smoker_cook_replays, at most 240 points a curve), so the journal itself and
  the page's journal list stay small;
* GET /api/smoker/journal/<id>/replay answers with what was kept, or, for a cook from before this (or one whose
  snapshot failed), with what the history still has (`"kept": false`).

Events: lid opened (with how long), wrapped / unwrapped, stall began / ended, off the grill (pulled), program step
changes ("Step 2/3" in the Program status) and charcoal top-ups (the Charcoal level jumping up). Times are epoch
seconds; temperatures are in the entities' own unit (`unit`).
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORE_KEY = "smoker_cook_replays"
STORE_VERSION = 1
MAX_POINTS = 240     # per curve
MIN_STEP_S = 60
MAX_EVENTS = 80
AFTER_S = 300        # the history is read up to 5 minutes past the end (the rest, the last readings)
SNAPSHOT_DELAY_S = 30  # the recorder commits every few seconds: wait for the cook's last minutes to be written
FUEL_JUMP = 8.0      # a charcoal level this many points above the last one is a top-up
STEP = re.compile(r"\bStep (\d+)/(\d+)")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _grid(pts: list[tuple[float, str]], t0: float, step: float, n: int) -> list[float | None]:
    """The last reading at or before each grid time (a sensor only records changes); None where there's none."""
    out: list[float | None] = []
    i, last = 0, None
    for k in range(n):
        t = t0 + k * step
        while i < len(pts) and pts[i][0] <= t:
            last = _f(pts[i][1])
            i += 1
        out.append(None if last is None else round(last, 1))
    return out


def _events(series: dict[str, list[tuple[float, str]]], start: float, end: float, slot: int | None) -> list[dict]:
    ev: list[dict] = []
    inside = lambda t: start <= t <= end  # noqa: E731

    def edges(role: str, on_k: str | None, off_k: str | None, with_slot: bool) -> None:
        prev = None
        for t, s in series.get(role, []):
            if s not in ("on", "off"):
                continue  # unknown / unavailable: the last known state stands
            if prev is not None and s != prev and inside(t):
                k = on_k if s == "on" else off_k
                if k:
                    ev.append({"t": round(t), "k": k, **({"slot": slot} if with_slot and slot else {})})
            prev = s

    # The lid: when it opened and for how long.
    opened = None
    prev = None
    for t, s in series.get("lid", []):
        if s not in ("on", "off"):
            continue
        if s == "on" and prev == "off" and inside(t):
            opened = {"t": round(t), "k": "lid"}
            ev.append(opened)
        elif s == "off" and opened is not None:
            opened["d"] = round(t - opened["t"])
            opened = None
        prev = s
    edges("wrapped", "wrap", "unwrap", True)
    edges("stall", "stall_start", "stall_end", True)
    edges("pulled", "pulled", None, True)
    # Program steps: "Step 2/3, pit 250°F, ..." in the Program status; an event when the step changes.
    prev_step = None
    for t, s in series.get("program", []):
        m = STEP.search(s or "")
        n = int(m.group(1)) if m else None
        if n is not None and n != prev_step and inside(t) and (prev_step is not None or t > start):
            ev.append({"t": round(t), "k": "step", "v": n})
        if m or (s or "") not in ("unknown", "unavailable", ""):
            prev_step = n
    # Charcoal top-ups: the level jumping up.
    level = None
    for t, s in series.get("fuel", []):
        v = _f(s)
        if v is None:
            continue
        if level is not None and v - level >= FUEL_JUMP and inside(t):
            ev.append({"t": round(t), "k": "fuel", "v": round(v)})
        level = v
    ev.sort(key=lambda e: e["t"])
    return ev[:MAX_EVENTS]


def build(series: dict[str, list[tuple[float, str]]], start: float, end: float, slot: int | None,
          unit: str = "") -> dict[str, Any]:
    """A replay from history: `series` maps a role (pit, target, food, lid, wrapped, stall, pulled, program, fuel) to
    its (epoch seconds, state) changes, oldest first, starting with the state at `start`."""
    span = max(60.0, end - start)
    step = max(MIN_STEP_S, math.ceil(span / (MAX_POINTS - 1) / 60) * 60)
    n = int(span // step) + 1
    out: dict[str, Any] = {"v": 1, "start": round(start), "end": round(end), "step": step, "unit": unit, "slot": slot}
    for role in ("pit", "target", "food"):
        vals = _grid(sorted(series.get(role, [])), start, step, n)
        out[role] = vals if any(v is not None for v in vals) else []
    out["events"] = _events({k: sorted(v) for k, v in series.items()}, start, end, slot)
    return out


def _slot(entry: dict) -> int | None:
    m = re.fullmatch(r"food(\d)", entry.get("probe") or "")
    return int(m.group(1)) if m else None


def entity_ids(hass: HomeAssistant, slot: int | None) -> dict[str, str]:
    """The smoker's entities for each role, found by name as the page does ("Smoker Pit temperature"), else by the
    ids Home Assistant gives them by default."""
    names = {"pit": ("sensor", "Pit temperature"), "target": ("number", "Pit target"), "lid": ("binary_sensor", "Lid"),
             "program": ("sensor", "Program status"), "fuel": ("sensor", "Charcoal level")}
    if slot:
        names.update({"food": ("sensor", f"Food {slot} temperature"), "wrapped": ("switch", f"Food {slot} wrapped"),
                      "stall": ("binary_sensor", f"Food {slot} stall"), "pulled": ("switch", f"Food {slot} pulled")})
    found: dict[str, str] = {}
    for role, (domain, name) in names.items():
        want = f"smoker {name}".lower()
        hit = next((s.entity_id for s in hass.states.async_all(domain)
                    if str(s.attributes.get("friendly_name") or "").lower() == want), None)
        default = f"{domain}.smoker_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if hit is None and hass.states.get(default) is not None:
            hit = default
        if hit:
            found[role] = hit
    return found


async def async_read(hass: HomeAssistant, entry: dict) -> dict[str, Any] | None:
    """The cook's replay from Home Assistant's history (None without the recorder)."""
    if "recorder" not in hass.config.components:
        return None
    from homeassistant.components.recorder import get_instance, history
    from homeassistant.util import dt as dt_util

    slot = _slot(entry)
    ids = entity_ids(hass, slot)
    if not ids:
        return None
    start, end = float(entry["started"]), float(entry["ended"])
    t0, t1 = dt_util.utc_from_timestamp(start), dt_util.utc_from_timestamp(end + AFTER_S)

    def query():
        return history.get_significant_states(hass, t0, t1, list(ids.values()), None, include_start_time_state=True,
                                              significant_changes_only=False, minimal_response=False, no_attributes=True)

    states = await get_instance(hass).async_add_executor_job(query)
    series: dict[str, list[tuple[float, str]]] = {}
    for role, eid in ids.items():
        series[role] = [(s.last_changed.timestamp(), s.state) for s in states.get(eid, []) if hasattr(s, "last_changed")]
    pit = hass.states.get(ids.get("pit", ""))
    unit = str(pit.attributes.get("unit_of_measurement") or "") if pit else ""
    return build(series, start, end, slot, unit)


class Replays:
    """The kept replays, by journal entry id (only those still in the journal)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self.data: dict[str, dict] = {}
        self.pending: list = []  # snapshot timers (cancelled on unload)

    async def async_load(self) -> None:
        stored = await self.store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("replays"), dict):
            self.data = stored["replays"]

    def keep(self, entry_id: str, replay: dict, keep_ids: set[str]) -> None:
        self.data[entry_id] = replay
        self.data = {k: v for k, v in self.data.items() if k in keep_ids}
        self.store.async_delay_save(lambda: {"replays": self.data}, 5)

    def forget(self, keep_ids: set[str]) -> None:
        if set(self.data) - keep_ids:
            self.data = {k: v for k, v in self.data.items() if k in keep_ids}
            self.store.async_delay_save(lambda: {"replays": self.data}, 5)

    async def async_snapshot(self, journal, entry: dict) -> None:
        """Read the finished cook from the history and keep it."""
        try:
            r = await async_read(self.hass, entry)
        except Exception as err:  # noqa: BLE001 - the replay is a nicety: never break the journal over it
            _LOGGER.warning("Couldn't keep the replay of the cook that just finished: %s", err)
            return
        if r and (r["pit"] or r["food"]):
            self.keep(entry["id"], r, {e["id"] for e in journal.data["entries"]})

    def schedule(self, journal, entry: dict) -> None:
        if "recorder" not in self.hass.config.components:
            return
        from homeassistant.helpers.event import async_call_later

        @callback
        def fire(_now) -> None:  # (on the event loop)
            self.pending[:] = [u for u in self.pending if u is not unsub]
            self.hass.async_create_task(self.async_snapshot(journal, entry), "smoker cook replay")

        unsub = async_call_later(self.hass, SNAPSHOT_DELAY_S, fire)
        self.pending.append(unsub)

    def cancel(self) -> None:
        for u in self.pending:
            u()
        self.pending.clear()


class ReplayView(HomeAssistantView):
    """GET /api/smoker/journal/<id>/replay: the kept replay, else what Home Assistant's history still has."""

    url = "/api/smoker/journal/{entry_id}/replay"
    name = "api:smoker:journal:replay"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        from .journal import DATA

        hass = request.app["hass"]
        j = hass.data[DATA]
        entry = next((e for e in j.data["entries"] if e["id"] == entry_id), None)
        if entry is None:
            return self.json_message("not found", 404)
        kept = j.replays.data.get(entry_id)
        if kept:
            return self.json({**kept, "kept": True})
        try:
            r = await async_read(hass, entry)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Couldn't read the cook's history: %s", err)
            r = None
        if r is None:
            return self.json({"v": 1, "start": round(entry["started"]), "end": round(entry["ended"]), "pit": [],
                              "target": [], "food": [], "events": [], "kept": False})
        return self.json({**r, "kept": False})
