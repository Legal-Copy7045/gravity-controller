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
from .sharing import async_setup_sharing, async_unload_sharing
from .package_install import async_setup_package_install
from .panel import async_remove_panel, async_setup_panel
from .watchdog import async_setup_watchdog, async_unload_watchdog

DOMAIN = "smoker"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    journal = await async_setup_journal(hass)
    await async_setup_panel(hass)
    version = await hass.async_add_executor_job(
        lambda: json.loads((Path(__file__).parent / "manifest.json").read_text())["version"])
    await async_setup_sharing(hass, journal, version)
    await async_setup_package_install(hass, version)
    await async_setup_watchdog(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_unload_journal(hass)
    async_unload_sharing(hass)
    async_remove_panel(hass)
    async_unload_watchdog(hass)
    return True
