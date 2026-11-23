"""The watchdog that reconnects Home Assistant to a controller whose ESPHome link got stuck."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smoker import watchdog
from custom_components.smoker.watchdog import Watchdog, decide


def test_decide():
    assert not decide(None, True, None)
    assert not decide(120, True, None)           # give ESPHome's own reconnect a chance
    assert decide(200, True, None)               # stuck while the page answers
    assert not decide(200, True, 300)            # just reloaded
    assert decide(200, True, 700)
    assert not decide(600, False, None)          # page silent: probably off, wait longer
    assert decide(1000, False, None)
    assert not decide(1000, False, 900)


async def test_reloads_a_stuck_controller_only(hass: HomeAssistant):
    devs, ents = dr.async_get(hass), er.async_get(hass)
    made = {}
    for name, model in (("smoker", "gravity980-bridge"), ("other", "bluetooth-proxy")):
        e = MockConfigEntry(domain="esphome", title=name, data={"host": f"{name}.local"}, state=ConfigEntryState.LOADED)
        e.add_to_hass(hass)
        d = devs.async_get_or_create(config_entry_id=e.entry_id, identifiers={("esphome", name)}, model=model)
        r = ents.async_get_or_create("sensor", "esphome", f"{name}-uptime", config_entry=e, device_id=d.id)
        hass.states.async_set(r.entity_id, "unavailable")
        made[name] = e
    w = Watchdog(hass)
    t = [1000.0]
    with patch.object(watchdog.time, "monotonic", lambda: t[0]), \
            patch.object(Watchdog, "_page_ok", AsyncMock(return_value=True)), \
            patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload:
        await w.check()
        t[0] += 100
        await w.check()
        assert not reload.called                 # 100 s: not yet
        t[0] += 100
        await w.check()
        await hass.async_block_till_done()
        assert [c.args[0] for c in reload.call_args_list] == [made["smoker"].entry_id]  # never the other device
        t[0] += 60
        await w.check()
        await hass.async_block_till_done()
        assert reload.call_count == 1            # not again straight away
    for e in made.values():  # don't make the test's teardown load the real ESPHome integration
        e.mock_state(hass, ConfigEntryState.NOT_LOADED)
