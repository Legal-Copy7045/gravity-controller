"""The Smoker page, served as a Home Assistant sidebar panel (same pattern as the MagicbHAnds and home-dashboards pages).

frontend/page.html gets frontend/common.js (helpers), frontend/shim.js (window.hdHA: live states and a small
allowlist of controls) and the styles (system fonts: nothing is loaded from outside Home Assistant), and is served to logged-in users at /api/smoker/page.
frontend/panel.js is the sidebar element that loads it into a frame and hands it the live `hass` object.
"""

from __future__ import annotations

import json

from pathlib import Path

from aiohttp import web

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant

FRONTEND = Path(__file__).parent / "frontend"
PANEL_PATH = "smoker-dashboard"
STATIC = "/smoker_static"
_SETUP = "smoker_panel_http"


def build_page() -> str:
    """The page with its helpers, shim and styles (blocking: run in the executor)."""
    read = lambda name: (FRONTEND / name).read_text(encoding="utf-8")  # noqa: E731
    html = read("page.html").replace("/*COMMON*/", read("common.js"))
    version = json.loads((FRONTEND.parent / "manifest.json").read_text(encoding="utf-8"))["version"]
    head = "<script>window.SMOKER_INTEGRATION = " + json.dumps(version) + ";" + read("shim.js") + "</script>\n"
    # No web fonts: the page used to load them from Google Fonts on every view (telling Google each time the dashboard
    # was opened). The styles name the fonts first and fall back to the system's own, so it looks right without them.
    style = "<style>" + read("style.css") + "</style>\n"
    html = html.replace("<head>", "<head>" + head, 1)
    i = html.find("</head>")
    return html[:i] + style + html[i:] if i >= 0 else style + html


class PageView(HomeAssistantView):
    """GET /api/smoker/page: the dashboard, for logged-in users only."""

    url = "/api/smoker/page"
    name = "api:smoker:page"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        html = await request.app["hass"].async_add_executor_job(build_page)
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "private, no-cache"})


async def async_setup_panel(hass: HomeAssistant) -> None:
    if not hass.data.get(_SETUP):
        hass.http.register_view(PageView())
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC, str(FRONTEND), False)])
        hass.data[_SETUP] = True
    if "frontend" not in hass.config.components or PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    version = int(await hass.async_add_executor_job(lambda: (FRONTEND / "panel.js").stat().st_mtime))
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="smoker-panel",
        sidebar_title="Smoker",
        sidebar_icon="mdi:grill",
        module_url=f"{STATIC}/panel.js?v={version}",
        require_admin=False,
        config={},
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        frontend.async_remove_panel(hass, PANEL_PATH)
