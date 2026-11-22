"""Smoker: a live sidebar dashboard for the Gravity 980 smoker controller.

The controller itself is an ESPHome device (see the repository's firmware/);
this integration adds the dashboard page and the cook journal (with photo identification of what's being cooked). Automations, notifications and
the AI advisor live in the package (package/smoker.yaml, a copy of homeassistant/packages/smoker.yaml), which the
action smoker.install_package writes into /config/packages.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

import json
from pathlib import Path

from .journal import async_setup_journal, async_unload_journal
from .package_install import async_setup_package_install
from .panel import async_remove_panel, async_setup_panel

DOMAIN = "smoker"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await async_setup_journal(hass)
    await async_setup_panel(hass)
    version = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
    await async_setup_package_install(hass, version)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_unload_journal(hass)
    async_remove_panel(hass)
    return True
