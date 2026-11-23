"""Reconnect Home Assistant to the controller when Home Assistant's ESPHome link gets stuck.

ESPHome normally reconnects on its own. Occasionally it doesn't: the controller keeps running (its own page answers)
while every entity in Home Assistant stays unavailable until someone reloads the device. Once a minute this checks each
Smoker controller (an ESPHome device whose model is the gravity980 project); when it has been unavailable for 3 minutes
and its web page answers, the ESPHome entry is reloaded. If the page doesn't answer (powered off, or no web server),
it tries once after 15 minutes. At most one reload per controller every 10 minutes (30 when the page doesn't answer).
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)
KEY = "smoker_watchdog"
STUCK_S = 180          # unavailable this long, page answering -> reload
STUCK_DARK_S = 900     # unavailable this long, page not answering -> try a reload anyway
GAP_S = 600            # between reloads (page answering)
GAP_DARK_S = 1800      # between reloads (page not answering)


def is_smoker_device(device) -> bool:
    return "gravity980" in (device.model or "").lower()


def decide(unavailable_for: float | None, page_ok: bool, since_reload: float | None) -> bool:
    """Should the ESPHome entry be reloaded now? (pure: tested)"""
    if unavailable_for is None:
        return False
    if page_ok:
        return unavailable_for >= STUCK_S and (since_reload is None or since_reload >= GAP_S)
    return unavailable_for >= STUCK_DARK_S and (since_reload is None or since_reload >= GAP_DARK_S)


class Watchdog:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.lost: dict[str, float] = {}      # entry_id -> monotonic time it was first seen unavailable
        self.reloaded: dict[str, float] = {}  # entry_id -> monotonic time of the last reload
        self.unsub = None

    def _controllers(self):
        devs, ents = dr.async_get(self.hass), er.async_get(self.hass)
        for entry in self.hass.config_entries.async_entries("esphome"):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            devices = [d for d in dr.async_entries_for_config_entry(devs, entry.entry_id) if is_smoker_device(d)]
            if not devices:
                continue
            ids = [e.entity_id for e in er.async_entries_for_config_entry(ents, entry.entry_id) if not e.disabled_by]
            yield entry, ids

    async def _page_ok(self, host: str | None) -> bool:
        if not host:
            return False
        try:
            async with async_get_clientsession(self.hass).get(
                    f"http://{host}/local/status", timeout=aiohttp.ClientTimeout(total=5)) as r:
                return r.status < 500
        except Exception:  # noqa: BLE001 - any failure means "not answering"
            return False

    async def check(self, _now=None) -> None:
        now = time.monotonic()
        for entry, ids in list(self._controllers()):
            states = [self.hass.states.get(i) for i in ids]
            states = [s for s in states if s is not None]
            down = bool(states) and all(s.state == "unavailable" for s in states)
            if not down:
                self.lost.pop(entry.entry_id, None)
                continue
            first = self.lost.setdefault(entry.entry_id, now)
            last = self.reloaded.get(entry.entry_id)
            gone = now - first
            if gone < STUCK_S:
                continue
            page = await self._page_ok(entry.data.get("host"))
            if decide(gone, page, None if last is None else now - last):
                self.reloaded[entry.entry_id] = now
                _LOGGER.warning("Smoker controller %s unavailable for %d min%s: reloading its ESPHome connection",
                                entry.title, gone // 60, " while its page still answers" if page else "")
                self.hass.async_create_task(self.hass.config_entries.async_reload(entry.entry_id))


async def async_setup_watchdog(hass: HomeAssistant) -> None:
    w = hass.data.get(KEY)
    if w is None:
        w = hass.data[KEY] = Watchdog(hass)
    if w.unsub is None:
        w.unsub = async_track_time_interval(hass, w.check, timedelta(seconds=60))


@callback
def async_unload_watchdog(hass: HomeAssistant) -> None:
    w = hass.data.pop(KEY, None)
    if w and w.unsub:
        w.unsub()
