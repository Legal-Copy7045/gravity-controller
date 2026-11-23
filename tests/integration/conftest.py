import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def community_averages_offline(aioclient_mock):
    """The integration fetches the community averages at start: no network in tests."""
    from custom_components.smoker.sharing import AGGREGATES_URL

    aioclient_mock.get(AGGREGATES_URL, status=404)
    yield


@pytest.fixture
def smoker_device_id(hass):
    """A device registered like the smoker controller (ESPHome, project model gravity980-bridge): esphome.smoker_*
    events are only taken from it."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="esphome", data={"host": "192.0.2.10"})
    entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("esphome", "smoker-test")},
                                                 manufacturer="Espressif", model="gravity980-bridge")
    return dev.id


@pytest.fixture
def other_device_id(hass):
    """Some other ESPHome device (a plug, a sensor...)."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="esphome", data={"host": "192.0.2.11"})
    entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("esphome", "plug-test")},
                                                 manufacturer="Espressif", model="esp32dev")
    return dev.id
