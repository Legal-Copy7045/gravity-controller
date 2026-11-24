"""The controller's "Local only (no internet)" switch stops the integration's own internet requests too."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smoker.local_only import local_only


async def test_local_only_follows_the_controllers_switch(hass: HomeAssistant):
    devs, ents = dr.async_get(hass), er.async_get(hass)
    e = MockConfigEntry(domain="esphome", title="smoker", data={"host": "smoker.local"}, state=ConfigEntryState.NOT_LOADED)
    e.add_to_hass(hass)
    d = devs.async_get_or_create(config_entry_id=e.entry_id, identifiers={("esphome", "smoker")},
                                 model="legal-copy7045.gravity980-bridge")
    r = ents.async_get_or_create("switch", "esphome", "smoker-local-only", config_entry=e, device_id=d.id,
                                 original_name="Local only (no internet)")
    assert not local_only(hass)  # no state yet
    hass.states.async_set(r.entity_id, "off")
    assert not local_only(hass)
    hass.states.async_set(r.entity_id, "on")
    assert local_only(hass)
    # Another device's switch with the same name doesn't count.
    other = MockConfigEntry(domain="esphome", title="plug", data={"host": "plug.local"}, state=ConfigEntryState.NOT_LOADED)
    other.add_to_hass(hass)
    d2 = devs.async_get_or_create(config_entry_id=other.entry_id, identifiers={("esphome", "plug")}, model="plug")
    r2 = ents.async_get_or_create("switch", "esphome", "plug-local-only", config_entry=other, device_id=d2.id,
                                  original_name="Local only (no internet)")
    hass.states.async_set(r.entity_id, "off")
    hass.states.async_set(r2.entity_id, "on")
    assert not local_only(hass)
