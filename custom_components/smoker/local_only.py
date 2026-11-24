"""The controller's "Local only (no internet)" switch, honoured by the integration too.

When it's on for a Smoker controller, the integration makes no internet requests on its behalf: no Open Pitmaster
uploads, withdrawals or community averages, and no AI photo reading. Home Assistant's own integrations are untouched.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

NAME = "Local only (no internet)"
MESSAGE = ("Local only is on for the controller (or it hasn't been seen since Home Assistant started): nothing is sent "
           "to the internet. Turn it off under Setup, with the controller on, to use this.")


# entity id -> last known on/off. Kept in memory only, so after a Home Assistant restart a controller that is switched
# off counts as local only until it's seen (fails closed: no upload goes out on a guess).
_LAST: dict[str, bool] = {}


def local_only(hass: HomeAssistant) -> bool:
    """True if any Smoker controller has "Local only" on, had it on when it was last seen, or hasn't been seen since
    Home Assistant started."""
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
        if st is not None and st.state in ("on", "off"):
            _LAST[ent.entity_id] = st.state == "on"
        if _LAST.get(ent.entity_id, True):
            return True
    return False
