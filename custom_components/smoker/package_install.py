"""smoker.install_package: write the Smoker package into Home Assistant's packages folder.

The package (helpers, automations, the AI advisor, the Home Assistant probe bridges) is plain YAML that Home Assistant
loads from /config/packages at start-up. This action writes the copy bundled with the integration there, filled in
with your phone, AI task and weather entities, so nobody has to copy files around. Admin only. Home Assistant has
to be restarted afterwards (the action says so; it never restarts anything itself).

Running it again (no fields needed) updates the package to the integration's version and keeps the choices made last
time, which are recorded on the file's first line. Any file it replaces is kept next to it as smoker.yaml.bak-<time>
(the last three).

Keeping it up to date: once the integration has installed the package, every start of the integration (so every
update through HACS) compares the installed package with the bundled one and, when they differ, rewrites it with the
same choices and reloads the parts of Home Assistant it uses (helpers, timers, templates, scripts, automations). No
second restart. A package that was copied in by hand (no "Installed by" line) is never touched, and neither is one you
edited after it was installed: the first line records a fingerprint (sha=…) of what was written, and a package that
no longer matches it is left alone with a notification (re-run the action to update it; your version is backed up).
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import voluptuous as vol

from homeassistant.components import persistent_notification

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.start import async_at_started

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
# The package's top-level keys, each reloadable without a restart.
RELOAD = ["input_boolean", "input_number", "input_text", "input_datetime", "timer", "template", "script", "automation"]
KEEP_BACKUPS = 3
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


def fingerprint(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def render(bundled: str, choices: dict, version: str) -> str:
    """The bundled package with the placeholders replaced and a header recording the choices and a fingerprint."""
    out = bundled
    for key, placeholder in DEFAULTS.items():
        out = out.replace(placeholder, choices.get(key, placeholder))
    head = f"{MARK} {version}: " + ", ".join(f"{k}={choices.get(k, DEFAULTS[k])}" for k in DEFAULTS)
    head += f", sha={fingerprint(out)}"
    return head + "\n# Re-run the action smoker.install_package to update it (your choices above are kept).\n" + out


def edited(text: str | None) -> bool:
    """Installed by the integration, then changed by hand (its body no longer matches the recorded fingerprint)."""
    if text is None or not text.startswith(MARK):
        return False
    m = re.search(r"\bsha=([0-9a-f]{16})", text.split("\n", 1)[0])
    return bool(m) and fingerprint(_body(text) or "") != m.group(1)


def _body(text: str | None) -> str | None:
    """The package without the integration's two header lines (they carry the version)."""
    if text is None or not text.startswith(MARK):
        return text
    return text.split("\n", 2)[2] if text.count("\n") >= 2 else ""


def install(config_dir: str, fields: dict, version: str, only_if_ours: bool = False) -> dict:
    pkg_dir = Path(config_dir) / "packages"
    target = pkg_dir / "smoker.yaml"
    old = target.read_text(encoding="utf-8") if target.exists() else None
    if only_if_ours and (old is None or not old.startswith(MARK)):
        return {"path": str(target), "changed": False, "backup": None, "restart_needed": False, "skipped": True}
    if only_if_ours and edited(old):  # your own changes: never overwritten by an automatic update
        return {"path": str(target), "changed": False, "backup": None, "restart_needed": False, "skipped": True,
                "edited": True}
    choices = {**(_previous_choices(old) if old else {}), **fields}
    if "notify" not in choices:
        raise HomeAssistantError(
            "Say which phone gets the smoker's alerts: notify: notify.mobile_app_<your phone> "
            "(Settings > Companion app shows the name)."
        )
    new = render(BUNDLED.read_text(encoding="utf-8"), choices, version)
    # Unchanged apart from the version in the header: leave it (no rewrite, no reload).
    same = old is not None and old.startswith(MARK) and _body(new) == _body(old) and "sha=" in old.split("\n", 1)[0]
    result = {"path": str(target), "changed": not same, "backup": None, "restart_needed": not same}
    if same:
        return result
    pkg_dir.mkdir(exist_ok=True)
    if old is not None:
        backup = pkg_dir / f"smoker.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        backup.write_text(old, encoding="utf-8")
        result["backup"] = str(backup)
        for stale in sorted(pkg_dir.glob("smoker.yaml.bak-*"))[:-KEEP_BACKUPS]:
            stale.unlink(missing_ok=True)
    tmp = target.with_suffix(".yaml.tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(target)
    conf = Path(config_dir) / "configuration.yaml"
    text = conf.read_text(encoding="utf-8") if conf.exists() else ""
    result["packages_loaded"] = bool(re.search(r"^\s*packages\s*:", text, re.M))
    return result


async def _reload(hass: HomeAssistant) -> list[str]:
    """Reload what the package defines; returns the domains that failed."""
    failed = []
    for domain in RELOAD:
        if not hass.services.has_service(domain, "reload"):
            continue
        try:
            await hass.services.async_call(domain, "reload", {}, blocking=True)
        except Exception:  # noqa: BLE001 - report, keep reloading the rest
            failed.append(domain)
    return failed


async def async_update_installed(hass: HomeAssistant, version: str) -> dict:
    """After an integration update: bring a package this integration installed up to date, then reload it."""
    res = await hass.async_add_executor_job(install, hass.config.config_dir, {}, version, True)
    if res.get("edited"):
        persistent_notification.async_create(
            hass, f"Your Smoker package has changes of your own, so it wasn't updated to {version}. To update it, run "
            "the action smoker.install_package (your version is kept next to it as a backup) and copy your changes "
            "back in.", "Smoker package", "smoker_package")
        return res
    if not res.get("changed"):
        return res
    failed = await _reload(hass)
    res["restart_needed"] = bool(failed)
    msg = f"Updated the Smoker package to {version} (the previous one is kept as {Path(res['backup']).name})"
    msg += (f". Couldn't reload {', '.join(failed)}: restart Home Assistant to finish." if failed
            else " and reloaded it: nothing else to do.")
    persistent_notification.async_create(hass, msg, "Smoker package", "smoker_package")
    return res


async def async_setup_package_install(hass: HomeAssistant, version: str) -> None:
    async def at_started(_hass: HomeAssistant) -> None:
        try:
            await async_update_installed(hass, version)
        except Exception as err:  # noqa: BLE001 - never break the integration over this
            persistent_notification.async_create(
                hass, f"Couldn't update the Smoker package: {err}", "Smoker package", "smoker_package")

    async_at_started(hass, at_started)

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
