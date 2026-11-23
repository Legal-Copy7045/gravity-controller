"""smoker.set_device_pin: set, replace or clear the controller's device page PIN from Home Assistant.

On the controller's own page the first PIN can only be set within 15 minutes of powering it on (so someone else on
the Wi-Fi can't claim the page first), and changing it needs the current one. Home Assistant holds the controller's
API encryption key, so it's trusted to set or replace the PIN at any time: this action calls the controller's
set_device_pin action (firmware 0.2.x and later). An empty PIN clears it. Admin only.

The PIN follows the controller's rules (6 to 32 characters, not 123456 or 111111): checked here first so a mistake is
shown straight away, and again on the controller. It is never logged, and never put in an error message: Home
Assistant's usual validation errors repeat the value they refused, so the checks are made here, not in the schema.
The controller hashes it in the background (a second or two); its "Device page PIN" sensor then says "set" or why
not.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

_LOGGER = logging.getLogger(__name__)

DOMAIN = "smoker"
SERVICE = "set_device_pin"
SET_PIN = ("esphome", "gravity980_set_device_pin")  # the controller's action
PIN_MIN, PIN_MAX = 6, 32

# cv.string: a PIN typed as a number in YAML (482913) arrives as an int.
SCHEMA = vol.Schema({vol.Optional("pin", default=""): vol.Any(None, cv.string)})


def pin_problem(pin: str) -> str:
    """Why the controller would refuse this PIN ("" if it's fine, or empty: clearing). Same rules as pin_auth.cpp."""
    if pin == "":
        return ""
    b = pin.encode()  # the controller counts bytes
    if len(b) < PIN_MIN:
        return "Use at least 6 characters (or leave it empty to clear the PIN)"
    if len(b) > PIN_MAX:
        return "Use at most 32 characters"
    same = all(c == b[0] for c in b)
    sequence = all(b[i] - b[i - 1] in (1, -1) for i in range(1, len(b)))
    if same or sequence:
        return "Too easy to guess (repeated or in sequence)"
    return ""


async def async_setup_device_pin(hass: HomeAssistant) -> None:
    async def handle(call: ServiceCall) -> None:
        pin = call.data.get("pin") or ""
        why = pin_problem(pin)
        if why:
            raise ServiceValidationError(why)  # (never the PIN itself)
        if not hass.services.has_service(*SET_PIN):
            raise HomeAssistantError(
                "The smoker controller isn't connected, or its firmware doesn't have this action yet: update the "
                "firmware (Settings > Devices, the Smoker's Firmware update)")
        await hass.services.async_call(*SET_PIN, {"pin": pin}, blocking=True)
        _LOGGER.info("Device page PIN %s: the controller's \"Device page PIN\" sensor shows the result",
                     "clear sent to the controller" if pin == "" else "sent to the controller")

    async_register_admin_service(hass, DOMAIN, SERVICE, handle, SCHEMA)


def async_unload_device_pin(hass: HomeAssistant) -> None:
    hass.services.async_remove(DOMAIN, SERVICE)
