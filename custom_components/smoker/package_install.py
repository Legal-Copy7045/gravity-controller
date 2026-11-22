"""smoker.install_package: write the Smoker package into Home Assistant's packages folder.

The package (helpers, automations, the AI advisor, the Home Assistant probe bridges) is plain YAML that Home Assistant
loads from /config/packages at start-up. This action writes the copy bundled with the integration there, filled in
with your phone, AI task and weather entities, so nobody has to copy files around. Admin only. Home Assistant has
to be restarted afterwards (the action says so; it never restarts anything itself).

Running it again (no fields needed) updates the package to the integration's version and keeps the choices made last
time, which are recorded on the file's first line. Any file it replaces is kept next to it as smoker.yaml.bak-<time>.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service

DOMAIN = "smoker"
SERVICE = "install_package"
BUNDLED = Path(__file__).parent / "package" / "smoker.yaml"
# Placeholders in the bundled package, and the field that replaces each.
DEFAULTS = {
    "notify": "notify.mobile_app_your_phone",
    "ai_task": "ai_task.google_ai_task",
    "weather": "weather.forecast_home",
}
MARK = "# Installed by the Smoker integration"
_EID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _entity(domain: str):
    def check(v):
        v = str(v).strip()
        if not _EID.match(v) or not v.startswith(domain + "."):
            raise vol.Invalid(f"expected a {domain}.… entity or action, got {v!r}")
        return v
    return check


SCHEMA = vol.Schema(
    {
        vol.Optional("notify"): _entity("notify"),
        vol.Optional("ai_task"): _entity("ai_task"),
        vol.Optional("weather"): _entity("weather"),
    }
)


def _previous_choices(text: str) -> dict:
    first = text.split("\n", 1)[0]
    if not first.startswith(MARK):
        return {}
    return {k: v for k, v in re.findall(r"\b(notify|ai_task|weather)=([a-z_]+\.[a-z0-9_]+)", first)}


def render(bundled: str, choices: dict, version: str) -> str:
    """The bundled package with the placeholders replaced and a header recording the choices."""
    out = bundled
    for key, placeholder in DEFAULTS.items():
        out = out.replace(placeholder, choices.get(key, placeholder))
    head = f"{MARK} {version}: " + ", ".join(f"{k}={choices.get(k, DEFAULTS[k])}" for k in DEFAULTS)
    return head + "\n# Re-run the action smoker.install_package to update it (your choices above are kept).\n" + out


def install(config_dir: str, fields: dict, version: str) -> dict:
    pkg_dir = Path(config_dir) / "packages"
    target = pkg_dir / "smoker.yaml"
    old = target.read_text(encoding="utf-8") if target.exists() else None
    choices = {**(_previous_choices(old) if old else {}), **fields}
    if "notify" not in choices:
        raise HomeAssistantError(
            "Say which phone gets the smoker's alerts: notify: notify.mobile_app_<your phone> "
            "(Settings > Companion app shows the name)."
        )
    new = render(BUNDLED.read_text(encoding="utf-8"), choices, version)
    result = {"path": str(target), "changed": new != old, "backup": None, "restart_needed": new != old}
    if new == old:
        return result
    pkg_dir.mkdir(exist_ok=True)
    if old is not None:
        backup = pkg_dir / f"smoker.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        backup.write_text(old, encoding="utf-8")
        result["backup"] = str(backup)
    tmp = target.with_suffix(".yaml.tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(target)
    conf = Path(config_dir) / "configuration.yaml"
    text = conf.read_text(encoding="utf-8") if conf.exists() else ""
    result["packages_loaded"] = bool(re.search(r"^\s*packages\s*:", text, re.M))
    return result


async def async_setup_package_install(hass: HomeAssistant, version: str) -> None:
    async def handle(call: ServiceCall) -> ServiceResponse:
        res = await hass.async_add_executor_job(install, hass.config.config_dir, dict(call.data), version)
        if res["changed"]:
            msg = f"Wrote {res['path']}" + (f" (the old one is kept as {Path(res['backup']).name})" if res["backup"] else "")
            msg += ". Restart Home Assistant to load it."
            if not res.get("packages_loaded"):
                msg += (" configuration.yaml doesn't load packages yet: add `packages: !include_dir_named packages` "
                        "under `homeassistant:` first.")
            persistent_notification.async_create(hass, msg, "Smoker package", "smoker_package")
        return res

    if not hass.services.has_service(DOMAIN, SERVICE):
        async_register_admin_service(hass, DOMAIN, SERVICE, handle, SCHEMA, supports_response=SupportsResponse.OPTIONAL)
