"""Check the controller's events before anything acts on them, then pass them on under the smoker's own names.

The controller sends Home Assistant three events: esphome.smoker_notify (an alert for your phone),
esphome.smoker_context (live state for the AI advisor) and esphome.smoker_cook_complete (a finished cook). Home
Assistant's ESPHome integration fires them as {"device_id": <the sending device>, **the device's data}, so the device's
own data can overwrite device_id: any ESPHome device on the network could claim to be the smoker. Checking the
device's model alone is therefore not enough.

So each event is checked here:

* it was fired inside Home Assistant (origin LOCAL) and not on behalf of a user: an event fired through the companion
  app's webhook or the REST API (origin REMOTE, or a user in its context) is never the controller;
* the device it names is the smoker controller (an ESPHome device whose model is the gravity980 project);
* it carries the event secret, once the controller has shown it knows it.

The secret: a random value this integration makes once (kept in .storage/smoker_event_secret, never in a state that
other devices or users can read; the raw esphome.smoker_* events that carry it are visible to admins on the event bus,
and the package keeps them out of the recorder) and hands to the controller with its `set_event_secret` action whenever that action
is there (firmware that has it keeps the secret in flash and adds "secret" to every smoker event). Until the
controller has sent one event with the right secret, events without one are still taken (older firmware keeps working);
from the first good one on, an event without the secret, or with a wrong one, is dropped.

Events that pass are fired again as smoker_controller_notify / smoker_controller_context /
smoker_controller_cook_complete (the secret taken out). The package's automations and the journal listen to those,
and also check that they were fired inside Home Assistant without a user (a phone can fire events through its
webhook, but only as a remote event with its user attached).
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from typing import Any

import voluptuous as vol
from homeassistant.const import EVENT_SERVICE_REGISTERED
from homeassistant.core import Event, EventOrigin, HomeAssistant, callback
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

DATA = "smoker_controller_events"
STORE_KEY = "smoker_event_secret"
# The controller's events and the names they're passed on under.
RELAY = {
    "esphome.smoker_notify": "smoker_controller_notify",
    "esphome.smoker_context": "smoker_controller_context",
    "esphome.smoker_cook_complete": "smoker_controller_cook_complete",
}
SET_SECRET = ("esphome", "gravity980_set_event_secret")  # the controller's action (firmware with event secrets)


def fired_inside(event: Event) -> bool:
    """Fired by Home Assistant itself (an integration or an automation), not through the API or a phone's webhook."""
    return event.origin is EventOrigin.local and event.context.user_id is None


class ControllerEvents:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store = Store(hass, 1, STORE_KEY, private=True)
        self.secret = ""
        self.confirmed = False  # the controller has sent the secret at least once: from then on it's required
        self.unsubs: list = []
        self.warned = False
        self._repaired_at = -1e9

    async def async_load(self) -> None:
        stored = await self.store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("secret"), str) and len(stored["secret"]) >= 32:
            self.secret = stored["secret"]
            self.confirmed = bool(stored.get("confirmed"))
        else:
            self.secret = secrets.token_hex(16)
            self.confirmed = False
            await self.store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"secret": self.secret, "confirmed": self.confirmed}

    def check(self, event: Event) -> bool:
        """Should this controller event be acted on? (Also learns that the controller now sends the secret.)"""
        from .journal import from_smoker

        if not fired_inside(event) or not from_smoker(self.hass, event):
            return False
        given = event.data.get("secret")
        if isinstance(given, str) and given:
            if not hmac.compare_digest(given.encode(), self.secret.encode()):
                self._repair()  # e.g. this integration was reinstalled with a new secret: hand it over again
                return False
            if not self.confirmed:
                self.confirmed = True
                self.store.async_delay_save(self._data, 1)
                _LOGGER.info("The smoker controller now signs its events: unsigned ones are dropped from now on")
            return True
        if self.confirmed:
            # The controller forgot the secret (a factory reset, a reflash): hand it over again so the next event counts.
            self._repair()
            if not self.warned:  # (once per start: e.g. the controller was flashed back to older firmware)
                self.warned = True
                _LOGGER.warning("Dropped a smoker event without the event secret (the controller used to send it); "
                                "if the controller's firmware was downgraded, update it again")
            return False
        return True  # firmware without event secrets yet

    @callback
    def _repair(self) -> None:
        """Send the secret to the controller again (at most once a minute)."""
        now = time.monotonic()
        if now - self._repaired_at < 60:
            return
        self._repaired_at = now
        self.hass.async_create_task(self.async_push_secret())

    @callback
    def handle(self, event: Event) -> None:
        if not self.check(event):
            _LOGGER.debug("Ignored %s: not from the smoker controller", event.event_type)
            return
        data = {k: v for k, v in event.data.items() if k != "secret"}
        self.hass.bus.async_fire(RELAY[event.event_type], data, context=event.context)

    async def async_push_secret(self) -> None:
        """Hand the secret to the controller (when its firmware has the action)."""
        if not self.hass.services.has_service(*SET_SECRET):
            return
        # From firmware 1.4.1 the controller replaces a secret only when the call carries the current one ("old"):
        # this integration's own (the same) on every reconnection. Older firmware has no "old" field.
        for data in ({"secret": self.secret, "old": self.secret}, {"secret": self.secret}):
            try:
                await self.hass.services.async_call(*SET_SECRET, data, blocking=True)
                return
            except vol.Invalid:
                continue  # older firmware: no "old"
            except Exception as err:  # noqa: BLE001 - the controller may be offline; sent again when it reconnects
                _LOGGER.debug("Couldn't give the controller its event secret: %s", err)
                return

    @callback
    def _service_registered(self, event: Event) -> None:
        # ESPHome registers the controller's actions each time it connects: send the secret then.
        if (event.data.get("domain"), event.data.get("service")) == SET_SECRET:
            self.hass.async_create_task(self.async_push_secret())


async def async_setup_controller_events(hass: HomeAssistant) -> ControllerEvents:
    ce = hass.data.get(DATA)
    if ce is None:
        ce = ControllerEvents(hass)
        await ce.async_load()
        hass.data[DATA] = ce
    async_unload_controller_events(hass)
    ce.unsubs = [hass.bus.async_listen(name, ce.handle) for name in RELAY]
    ce.unsubs.append(hass.bus.async_listen(EVENT_SERVICE_REGISTERED, ce._service_registered))
    hass.async_create_task(ce.async_push_secret())
    return ce


def async_unload_controller_events(hass: HomeAssistant) -> None:
    ce = hass.data.get(DATA)
    if ce:
        for unsub in ce.unsubs:
            unsub()
        ce.unsubs = []
