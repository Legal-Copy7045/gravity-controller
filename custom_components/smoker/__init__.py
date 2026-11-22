"""Smoker: a live sidebar dashboard for the Gravity 980 smoker controller.

The controller itself is an ESPHome device (see the repository's firmware/);
this integration adds the dashboard page and the cook journal (with photo identification of what's being cooked). Automations, notifications and
the AI advisor live in homeassistant/packages/smoker.yaml.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .journal import async_setup_journal, async_unload_journal
from .panel import async_remove_panel, async_setup_panel

DOMAIN = "smoker"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await async_setup_journal(hass)
    await async_setup_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_unload_journal(hass)
    async_remove_panel(hass)
    return True
