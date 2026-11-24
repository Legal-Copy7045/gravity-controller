"""The controller's "Local only (no internet)" switch, honoured by the integration too.

When it's on for a Smoker controller, the integration makes no internet requests on its behalf: no Open Pitmaster
uploads, withdrawals or community averages, and no AI photo reading. Home Assistant's own integrations are untouched.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

NAME = "Local only (no internet)"
MESSAGE = "Local only is on for the controller: nothing is sent to the internet. Turn it off under Setup to use this."


def local_only(hass: HomeAssistant) -> bool:
    """True if any Smoker controller has "Local only" on."""
    from .watchdog import is_smoker_device

    devs, ents = dr.async_get(hass), er.async_get(hass)
    for ent in ents.entities.values():
        if ent.domain != "switch" or ent.disabled_by is not None:
            continue
        if (ent.original_name or "") != NAME and not ent.entity_id.endswith("_local_only_no_internet"):
            continue
        dev = devs.async_get(ent.device_id) if ent.device_id else None
        if dev is None or not is_smoker_device(dev):
            continue
        st = hass.states.get(ent.entity_id)
        if st is not None and st.state == "on":
            return True
    return False
