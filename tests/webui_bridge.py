#!/usr/bin/env python3
"""Stand-in for ESPHome's web_server, for testing the device page (firmware/device-ui) against the host build.

ESPHome's host platform has no web_server (2026.11 limits it to ESP32/ESP8266/BK72xx/LN882x/RP2040/RTL87xx), so
this serves the same HTTP interface from the host firmware's native API, mimicking web_server v3 on ESP-IDF
(esphome/components/web_server/web_server.cpp, web_server_idf/sse_chunk.cpp):

  GET  /                          the index ESPHome builds (build_index_html() of core.yaml's web_server block)
  GET  /0.js, /0.css              js_include / css_include, gzipped (Content-Encoding: gzip)
  GET  /events                    SSE: "ping" {title, comment, ota, log, lang, uptime} (retry 30000), then one
                                  "state" event per entity with detail (domain, name, icon, entity_category,
                                  uom / option / min_value...), then "state" events with id + value + state;
                                  {"uptime"} pings every 10 s
  GET  /<domain>/<name>           state JSON (?detail=all for the detail fields)
  POST /<domain>/<name>/<action>  switch turn_on|turn_off|toggle, button press, number set?value=,
                                  select set?option=, text set?value=  -> 200, or 404

Ids are "<domain>/<entity name>" (names, not object ids, since ESPHome 2026.x). Values follow the C++ JSON:
sensor value float (null when NaN) and state "NA" or "<value> <uom>"; number value/min/max/step as strings
("NaN" / state "NA" when unknown); switch/binary_sensor value bool, state "ON"/"OFF".

    python3 tests/webui_bridge.py --http 18080 --api 127.0.0.1:6053
"""

import argparse
import asyncio
import gzip
import json
import math
import os
import sys
import time

import yaml
from aiohttp import web
from aioesphomeapi import (APIClient, BinarySensorInfo, ButtonInfo, NumberInfo, SelectInfo, SensorInfo, SwitchInfo,
                           TextInfo, TextSensorInfo)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "firmware", "core.yaml")
DOMAINS = [(BinarySensorInfo, "binary_sensor"), (SensorInfo, "sensor"), (SwitchInfo, "switch"), (ButtonInfo, "button"),
           (TextSensorInfo, "text_sensor"), (NumberInfo, "number"), (TextInfo, "text"), (SelectInfo, "select")]


class AnyTag(yaml.SafeLoader):
    pass


AnyTag.add_multi_constructor("!", lambda loader, suffix, node: None)


def web_server_config():
    """core.yaml's web_server block, with ESPHome's defaults for version 3."""
    with open(CORE, encoding="utf-8") as f:
        conf = yaml.load(f, Loader=AnyTag)["web_server"]
    conf.setdefault("css_url", "")
    conf.setdefault("js_url", "https://oi.esphome.io/v3/www.js")
    return conf


def index_html(conf):
    try:  # ESPHome's own builder when it's installed (it is wherever the host firmware is built)
        from esphome.components.web_server import build_index_html
        return build_index_html(conf)
    except ImportError:  # the same markup, copied from esphome 2026.11 web_server/__init__.py
        h = "<!DOCTYPE html><html><head><meta charset=UTF-8><link rel=icon href=data:>"
        if conf.get("css_include"):
            h += "<link rel=stylesheet href=/0.css>"
        if conf["css_url"]:
            h += f'<link rel=stylesheet href="{conf["css_url"]}">'
        h += "</head><body>"
        if conf.get("js_include"):
            h += "<script type=module src=/0.js></script>"
        h += "<esp-app></esp-app>"
        if conf["js_url"]:
            h += f'<script src="{conf["js_url"]}"></script>'
        return h + "</body></html>"


def accuracy(step):  # step_to_accuracy_decimals(): decimals of the step at five significant digits
    if not step or not math.isfinite(step):
        return 0
    s = f"{abs(step):.5g}"
    return len(s.split(".")[1]) if "." in s and "e" not in s else 0


def fnum(v, d):
    return f"{v:.{max(d, 0)}f}"


class Bridge:
    def __init__(self, title):
        self.title = title
        self.info = {}      # key -> (domain, info)
        self.by_name = {}   # (domain, name) -> key
        self.state = {}     # key -> state object
        self.clients = set()
        self.t0 = time.monotonic()
        self.cli = None

    def json(self, key, detail):
        dom, info = self.info[key]
        st = self.state.get(key)
        o = {"id": f"{dom}/{info.name}"}
        if dom == "sensor":
            v = None if st is None or st.missing_state or not math.isfinite(st.state) else st.state
            o["value"] = v
            o["state"] = "NA" if v is None else fnum(v, info.accuracy_decimals) + (f" {info.unit_of_measurement}" if info.unit_of_measurement else "")
        elif dom == "number":
            d = accuracy(info.step)
            v = None if st is None or st.missing_state or not math.isfinite(st.state) else st.state
            o["value"] = "NaN" if v is None else fnum(v, d)
            o["state"] = "NA" if v is None else fnum(v, d) + (f" {info.unit_of_measurement}" if info.unit_of_measurement else "")
            if detail:
                o.update(min_value=fnum(info.min_value, d), max_value=fnum(info.max_value, d), step=fnum(info.step, d),
                         mode=int(info.mode or 0))
                if info.unit_of_measurement:
                    o["uom"] = info.unit_of_measurement
        elif dom in ("binary_sensor", "switch"):
            v = bool(st and st.state)
            o["value"], o["state"] = v, "ON" if v else "OFF"
            if detail and dom == "switch":
                o["assumed_state"] = info.assumed_state
        elif dom in ("text_sensor", "select", "text"):
            v = st.state if st is not None and not getattr(st, "missing_state", False) else ""
            o["value"] = o["state"] = v
            if dom == "text":
                o.update(min_length=info.min_length, max_length=info.max_length, pattern=info.pattern)
                if detail:
                    o["mode"] = int(info.mode or 0)
            if dom == "select" and detail:
                o["option"] = list(info.options)
        if detail:
            o.update(domain=dom, name=info.name, icon=info.icon, entity_category=int(info.entity_category or 0))
            if info.disabled_by_default:
                o["is_disabled_by_default"] = True
            if dom == "sensor" and info.unit_of_measurement:
                o["uom"] = info.unit_of_measurement
        return o

    async def send(self, resp, event, data, eid=0, retry=0):
        msg = (f"retry: {retry}\r\n" if retry else "") + (f"id: {eid}\r\n" if eid else "") + f"event: {event}\r\n"
        msg += f"data: {json.dumps(data, separators=(',', ':'))}\r\n\r\n"
        await resp.write(msg.encode())

    def on_state(self, s):
        if s.key not in self.info:
            return
        self.state[s.key] = s
        data = self.json(s.key, False)
        for resp in list(self.clients):
            asyncio.ensure_future(self._safe(resp, data))

    async def _safe(self, resp, data):
        try:
            await self.send(resp, "state", data)
        except Exception:
            self.clients.discard(resp)

    async def events(self, request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(request)
        up = int(time.monotonic() - self.t0)
        ms = int((time.monotonic() - self.t0) * 1000) or 1
        await self.send(resp, "ping", {"title": self.title, "comment": "", "ota": False, "log": True, "lang": "en",
                                       "uptime": up}, ms, 30000)
        for key in list(self.info):
            await self.send(resp, "state", self.json(key, True))
        self.clients.add(resp)
        try:
            while True:
                await asyncio.sleep(10)
                ms = int((time.monotonic() - self.t0) * 1000)
                await resp.write(f"retry: 30000\r\nid: {ms}\r\nevent: ping\r\ndata: {{\"uptime\":{ms // 1000}}}\r\n\r\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.clients.discard(resp)
        return resp

    def find(self, request):
        dom, name = request.match_info["domain"], request.match_info["name"]
        return self.by_name.get((dom, name)), dom

    async def get(self, request):
        key, _ = self.find(request)
        if key is None:
            return web.Response(status=404)
        return web.json_response(self.json(key, request.query.get("detail") == "all"))

    async def post(self, request):
        if not LOCAL.gate(request):
            return web.json_response({"error": "Enter the PIN to make changes", "pin": True}, status=401)
        key, dom = self.find(request)
        act = request.match_info["action"]
        if key is None:
            return web.Response(status=404)
        q = dict(request.query)
        if request.can_read_body:
            q.update(await request.post())
        st = self.state.get(key)
        c = self.cli
        if dom == "switch" and act in ("toggle", "turn_on", "turn_off"):
            c.switch_command(key, (not (st and st.state)) if act == "toggle" else act == "turn_on")
        elif dom == "button" and act == "press":
            c.button_command(key)
        elif dom == "number" and act == "set":
            try:
                v = float(q.get("value", ""))
            except ValueError:
                return web.Response(status=200)  # parse_number fails: nothing set, still 200
            c.number_command(key, v)
        elif dom == "select" and act == "set":
            if "option" in q:
                c.select_command(key, q["option"])
        elif dom == "text" and act == "set":
            if "value" in q:
                c.text_command(key, q["value"])
        else:
            return web.Response(status=404)
        return web.Response(status=200)


LOCAL = None


class Local:
    """Stand-in for components/standalone's /local/ API and its PIN gate (the crypto itself is tested in test_core)."""

    def __init__(self):
        self.pin, self.tokens, self.fails = None, set(), 0
        self.s = {"route": "auto", "ntfy_server": "https://ntfy.sh", "set": {"ntfy": False, "pushover": False,
                                                                            "telegram": False, "ai": False},
                  "location": False, "tz": False, "lat": None, "lon": None,
                  "plan": {"serve_by": 0, "rest_min": 60, "now": 0}}
        rec = {"v": 1, "id": "0123456789abcdef0123456789abcdef", "grill": "gravity980", "release": "0.2.29",
               "season": "autumn", "cut": "Pork shoulder", "weight_lb": 8.5, "wrapped": True, "pit_f": 250,
               "target_f": 203, "stall_h": 3.1, "total_h": 11.6, "outside_f": 35, "rating": None, "tags": []}
        self.journal = {"share": {"enabled": False, "auto": False}, "results": [], "entries": [
            {"id": "a1b2c3d4", "ended": 1795300000, "profile": "Pork shoulder", "weight_kg": 3.86, "pit_c": 121.1,
             "stall_h": 3.1, "total_h": 11.6, "ambient_c": 2.0, "wrapped": True, "notes": "", "share": "pending",
             "tags": [], "record": rec}]}

    def authed(self, request):
        return self.pin is not None and request.headers.get("X-Smoker-Token", "") in self.tokens

    def status(self, request):
        a = self.authed(request)
        return {**self.s, "pin": self.pin is not None, "authed": a, "locked": 0, "ha": True, "ai_provider": "",
                "ai_model": "", "weather_age_min": -1, "last": {"ntfy": "", "pushover": "", "telegram": ""},
                **({} if a else {"lat": None, "lon": None})}

    def gate(self, request):  # writes need the PIN once one is set
        return self.pin is None or self.authed(request)

    def token(self):
        t = os.urandom(32).hex()
        self.tokens.add(t)
        return t

    async def handle(self, request):
        path = request.match_info["path"]
        if request.method == "GET":
            if path == "history":
                n = min(int(request.query.get("hours", "6")) * 60, 180)
                pit = [round(250 + 5 * ((i % 20) - 10) / 10, 1) for i in range(n)]
                return web.json_response({"step_min": 1, "age_s": 10, "names": ["Pit", "Pit target", "Food 1"],
                                          "series": [pit, [250.0] * n, [round(120 + i * 0.2, 1) for i in range(n)]]})
            if path == "journal":
                return web.json_response(self.journal)
            if path == "community":
                return web.json_response({"cooks": 42, "updated": "2026-11-23", "groups": [
                    {"cut": "Pork shoulder", "line": "Pork shoulder 8-10 lb at 225-255°F: typically 11.2 h; 12 cooks"}]})
            return web.json_response(self.status(request))
        body = await request.json() if request.can_read_body else {}
        err = lambda m, c=400: web.json_response({"error": m}, status=c)  # noqa: E731
        if path == "pin":
            if self.pin is not None and body.get("current") != self.pin:
                return err("The current PIN is wrong")
            p = body.get("pin", "")
            if len(p) < 6 or len(set(p)) == 1 or p in ("123456", "654321"):
                return err("Use at least 6 characters")
            self.pin, self.tokens = p, set()
            return web.json_response({"token": self.token()})
        if path == "login":
            if body.get("pin") != self.pin:
                return err("Wrong PIN", 401)
            return web.json_response({"token": self.token()})
        if path == "logout":
            self.tokens.discard(request.headers.get("X-Smoker-Token", ""))
            return web.json_response({})
        if self.pin is None:
            return err("Set a PIN for the device page first", 409)
        if not self.authed(request):
            return err("Enter the PIN", 401)
        if path == "secret":
            k = body.get("name", "").split("_")[0]
            self.s["set"][k] = bool(body.get("value"))
        elif path == "settings":
            for k in ("route", "ntfy_server"):
                if k in body:
                    self.s[k] = body[k]
            if "lat" in body:
                self.s.update(location=True, lat=round(body["lat"], 2), lon=round(body["lon"], 2))
            if body.get("clear_location"):
                self.s.update(location=False, lat=None, lon=None)
            if "tz" in body:
                self.s["tz"] = True
                self.s["tz_rules"] = body["tz"]
        elif path == "plan":
            self.s["plan"].update({k: body[k] for k in ("serve_by", "rest_min") if k in body})
            if self.s["plan"]["serve_by"]:
                self.s["plan"]["light_by"] = self.s["plan"]["serve_by"] - (600 + self.s["plan"]["rest_min"]) * 60
                self.s["plan"]["est_min"] = 600
        elif path == "fuel":
            self.s["last_fuel"] = body
        elif path.startswith("journal/"):
            e = self.journal["entries"][0]
            if path.endswith("/delete"):
                self.journal["entries"] = []
            else:
                for k in ("rating", "tags", "notes"):
                    if k in body:
                        e[k] = body[k]
                        if k != "notes":
                            e["record"][k] = body[k]
                if e.get("rating") or e.get("tags"):
                    e["share"] = e["share"] if e["share"] != "waiting" else "pending"
            return web.json_response(self.journal)
        elif path == "share/settings":
            self.journal["share"].update({k: body[k] for k in ("enabled", "auto") if k in body})
            return web.json_response(self.journal)
        elif path.startswith("share/"):
            e = self.journal["entries"][0]
            if not self.journal["share"]["enabled"]:
                return err("Turn on sharing first", 409)
            e["share"] = "declined" if path.endswith("/decline") else "shared"
            return web.json_response(self.journal)
        elif path == "test-notify":
            self.s["last_test"] = True
        else:
            return err("not found", 404)
        return web.json_response(self.status(request))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", type=int, default=18080)
    ap.add_argument("--api", default="127.0.0.1:6053")
    a = ap.parse_args()
    conf = web_server_config()
    here = os.path.dirname(CORE)
    files = {}
    for k, path, ctype in (("js_include", "/0.js", "text/javascript"), ("css_include", "/0.css", "text/css")):
        if conf.get(k):
            with open(os.path.join(here, conf[k]), "rb") as f:
                files[path] = (gzip.compress(f.read()), ctype)
    index = index_html(conf)

    host, port = a.api.split(":")
    cli = APIClient(host, int(port), None)
    for _ in range(60):
        try:
            await cli.connect(login=True)
            break
        except Exception:
            await asyncio.sleep(0.5)
    else:
        sys.exit("cannot reach the device API")
    dev = await cli.device_info()
    entities, _ = await cli.list_entities_services()
    br = Bridge(dev.friendly_name or dev.name)
    br.cli = cli
    for cls, dom in DOMAINS:
        for e in entities:
            if type(e) is cls:
                br.info[e.key] = (dom, e)
                br.by_name[(dom, e.name)] = e.key
    cli.subscribe_states(br.on_state)

    global LOCAL
    LOCAL = Local()
    app = web.Application()

    async def root(_):
        return web.Response(text=index, content_type="text/html")

    def static(path):
        body, ctype = files[path]
        return lambda _: web.Response(body=body, headers={"Content-Type": ctype, "Content-Encoding": "gzip"})

    app.router.add_get("/", root)
    for p in files:
        app.router.add_get(p, static(p))
    app.router.add_get("/events", br.events)
    app.router.add_route("*", "/local/{path:.*}", LOCAL.handle)
    app.router.add_get("/{domain}/{name}", br.get)
    app.router.add_post("/{domain}/{name}/{action}", br.post)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", a.http).start()
    print(f"web_server stand-in on http://127.0.0.1:{a.http}/ ({len(br.info)} entities)", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
