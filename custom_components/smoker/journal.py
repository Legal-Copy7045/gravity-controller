"""Cook journal and "what's being cooked" from photos.

* Every finished cook (the controller's `esphome.smoker_cook_complete` event) becomes a journal entry: protein,
  weight, pit, stall, total time, weather, plus your notes and rating, and the items you scanned for it.
* POST photos of the barcode/label of one or more packages to /api/smoker/identify: the AI (Home Assistant's
  AI Task) reads them and returns the items (cut, protein profile, weight). They're kept as the "next cook" draft;
  assigning an item to a probe sets that probe's protein and weight on the controller.
* The page reads everything through authenticated views (/api/smoker/journal, /api/smoker/photo/<name>).
* sensor.smoker_journal summarises recent entries (notes and ratings) so the AI advisor can learn from them.
"""

from __future__ import annotations

import hmac
import json
import logging
import math
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORE_KEY = "smoker_journal"
STORE_VERSION = 1
MAX_ENTRIES = 200
MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BYTES = 4 * MAX_PHOTO_BYTES  # all the photos of one scan together
MAX_PIXELS = 40_000_000  # bigger than any phone photo; refused before it's decoded (a "decompression bomb")
SCAN_DIR = "smoker_scans"  # our own folder under the media directory
SCAN_NAME = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}-\d\.(jpg|png)")  # only files we wrote are ever tidied away
PROFILES = ["Auto", "Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish"]
DATA = "smoker_journal_data"
# "How was it?": what the food turned out like (cooking outcomes only; also shared, if sharing is on).
TAGS = ["juicy", "tender", "dry", "tough", "undercooked", "just right", "overcooked", "great bark", "soft bark",
        "good smoke", "too smoky", "too little smoke", "fat rendered", "fat not rendered"]

IDENTIFY_INSTRUCTIONS = """You are looking at photos of meat or fish packages that are about to be cooked on a smoker
(barcode stickers, butcher labels, packaging). Identify every distinct item.
For each item give one line in exactly this format:
NAME | PROFILE | WEIGHT_LB | BARCODE | NOTES
- NAME: short description, e.g. "Bone-in pork shoulder (Boston butt)".
- PROFILE: exactly one of: {profiles}. Use Auto if it fits none.
- WEIGHT_LB: net weight in pounds as a number (convert kg or oz); empty if you can't read it.
- BARCODE: the barcode digits if legible, else empty.
- NOTES: anything useful for cooking (e.g. "enhanced with solution", "prime grade", "bone-in"), or empty.
Read the printed label text (net weight, product name) rather than guessing from the barcode alone; store barcodes for
weighed meat (starting with 2) encode price or weight, not the product. One line per item, nothing else."""


def _num(v: Any, lo: float, hi: float) -> float | None:
    """A finite number within lo..hi, else None (the cook summary comes from a device: never trusted as is)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) and lo <= v <= hi else None


def from_smoker(hass: HomeAssistant, event: Event) -> bool:
    """The event came from the smoker controller (any ESPHome device can fire esphome.* events)."""
    from homeassistant.helpers import device_registry as dr

    from .watchdog import is_smoker_device

    device_id = event.data.get("device_id")
    device = dr.async_get(hass).async_get(device_id) if isinstance(device_id, str) else None
    return device is not None and is_smoker_device(device)


def _entity_slug(key: str) -> str:
    """food1 -> food_1 (the ids HA builds from "Food 1")."""
    m = re.fullmatch(r"([a-z]+)(\d+)", key or "")
    return f"{m.group(1)}_{m.group(2)}" if m else key


def parse_items(text: str) -> list[dict[str, Any]]:
    """Parse the AI's 'NAME | PROFILE | WEIGHT_LB | BARCODE | NOTES' lines."""
    items = []
    for line in (text or "").splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.strip().strip("-* ").split("|")]
        parts += [""] * (5 - len(parts))
        name, profile, weight, barcode, notes = parts[:5]
        if not name or name.upper() == "NAME":
            continue
        prof = next((p for p in PROFILES if p.lower() == profile.lower()), "Auto")
        try:
            w = float(re.sub(r"[^0-9.]", "", weight)) if weight else None
        except ValueError:
            w = None
        items.append({"id": uuid.uuid4().hex[:8], "name": name[:120], "profile": prof,
                      "weight_lb": round(w, 2) if w else None, "barcode": re.sub(r"\D", "", barcode)[:20],
                      "notes": notes[:200], "probe": None})
    return items[:12]


class Journal:
    """Persistent journal + next-cook draft."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.unsub = None
        self.store: Store = Store(hass, STORE_VERSION, STORE_KEY)
        self.data: dict[str, Any] = {"entries": [], "draft": {"items": [], "photos": []}}
        self.listeners: list = []  # called with each new entry (sharing offers it)
        self.photo_dir = Path(hass.config.path(".storage", "smoker_photos"))

    async def async_load(self) -> None:
        stored = await self.store.async_load()
        if isinstance(stored, dict):
            self.data.update(stored)
        self.data.setdefault("entries", [])
        self.data.setdefault("draft", {"items": [], "photos": []})
        self._publish()

    def _save(self) -> None:
        self.store.async_delay_save(lambda: self.data, 2)
        self._publish()

    @callback
    def _publish(self) -> None:
        """sensor.smoker_journal: count + compact recent entries for the AI advisor's prompt."""
        recent = []
        for e in self.data["entries"][-8:]:
            r = {k: e.get(k) for k in ("ended", "profile", "weight_kg", "pit_c", "stall_h", "total_h",
                                       "carryover_c", "rating", "tags", "notes")}
            # Notes shortened: Home Assistant drops a state whose attributes pass 16 KB (8 x 2,000-character notes
            # would), and the AI prompt doesn't need the whole of each.
            if isinstance(r.get("notes"), str) and len(r["notes"]) > 300:
                r["notes"] = r["notes"][:297] + "..."
            recent.append(r)
        self.hass.states.async_set("sensor.smoker_journal", len(self.data["entries"]),
                                   {"friendly_name": "Smoker journal", "icon": "mdi:notebook", "recent": recent,
                                    "draft_items": [i["name"] for i in self.data["draft"]["items"]]})

    # ---- entries ----
    @callback
    def handle_cook_complete(self, event: Event) -> None:
        if not from_smoker(self.hass, event):
            _LOGGER.debug("Ignored a cook summary that didn't come from the smoker controller")
            return
        try:
            s = json.loads(event.data.get("summary") or "{}")
        except (TypeError, ValueError):
            _LOGGER.warning("Unreadable cook summary: %.200s", event.data.get("summary"))
            return
        if not isinstance(s, dict):
            _LOGGER.warning("Unreadable cook summary: %.200s", event.data.get("summary"))
            return
        now = time.time()
        total_h = _num(s.get("total_h"), 0, 72) or 0.0
        probe = s.get("probe") if isinstance(s.get("probe"), str) and re.fullmatch(r"[a-z0-9_]{1,16}", s["probe"]) else None
        name = s.get("name")
        wrapped = s.get("wrapped")
        draft_items = self.data["draft"]["items"]
        mine = [i for i in draft_items if i.get("probe") == probe]
        if not mine and draft_items and all(not i.get("probe") for i in draft_items):
            mine = list(draft_items)  # nothing assigned: the draft was for this cook
        entry = {
            "id": uuid.uuid4().hex[:12],
            "started": now - total_h * 3600,
            "ended": now,
            "probe": probe,
            "probe_name": name[:40] if isinstance(name, str) else None,
            "profile": s.get("profile") if s.get("profile") in PROFILES else "Auto",
            "weight_kg": _num(s.get("weight_kg"), 0, 100),
            "wrapped": wrapped if isinstance(wrapped, bool) else None,
            "pit_c": _num(s.get("pit_c"), -50, 500),
            "target_c": _num(s.get("target_c"), -50, 300),
            "stall_h": _num(s.get("stall_h"), 0, 72),
            "total_h": total_h,
            "ambient_c": _num(s.get("ambient_c"), -60, 70),
            "items": mine,
            "photos": list(self.data["draft"].get("photos", [])) if mine else [],
            "notes": "",
            "rating": None,
            "tags": [],
        }
        self.data["entries"].append(entry)
        self.data["entries"] = self.data["entries"][-MAX_ENTRIES:]
        # Used items leave the draft; photos go with the first entry that takes items.
        ids = {i["id"] for i in mine}
        self.data["draft"]["items"] = [i for i in draft_items if i["id"] not in ids]
        if mine:
            self.data["draft"]["photos"] = []
        self._save()
        for cb in list(self.listeners):
            cb(entry, "new")

    def update_entry(self, entry_id: str, changes: dict[str, Any]) -> dict | None:
        for e in self.data["entries"]:
            if e["id"] == entry_id:
                rating = e.get("rating")
                if "rating" in changes:
                    r = changes["rating"]
                    try:
                        rating = None if r in (None, "") else max(1, min(5, int(r)))
                    except (TypeError, ValueError):
                        raise ValueError("rating must be 1-5") from None
                e["rating"] = rating
                if "notes" in changes:
                    e["notes"] = str(changes["notes"])[:2000]
                if "tags" in changes:
                    tags = changes["tags"] or []
                    if not isinstance(tags, list) or any(t not in TAGS for t in tags):
                        raise ValueError("unknown tag")
                    e["tags"] = [t for t in TAGS if t in tags]  # known order, no repeats
                e["feedback_at"] = time.time() if ("rating" in changes or "tags" in changes) else e.get("feedback_at")
                self._save()
                if "rating" in changes or "tags" in changes:
                    for cb in list(self.listeners):
                        cb(e, "feedback")
                return e
        return None

    def delete_entry(self, entry_id: str) -> bool:
        n = len(self.data["entries"])
        self.data["entries"] = [e for e in self.data["entries"] if e["id"] != entry_id]
        if len(self.data["entries"]) != n:
            self._save()
            return True
        return False

    # ---- draft ----
    def set_draft_items(self, items: list[dict]) -> None:
        keep = []
        for i in items[:12]:
            prof = i.get("profile") if i.get("profile") in PROFILES else "Auto"
            w = i.get("weight_lb")
            iid = str(i.get("id") or "")
            if not re.fullmatch(r"[0-9a-f]{1,12}", iid):
                iid = uuid.uuid4().hex[:8]  # ids end up in the page's markup: hex only
            probe = i.get("probe")
            keep.append({"id": iid, "name": str(i.get("name", ""))[:120],
                         "profile": prof, "weight_lb": float(w) if isinstance(w, (int, float)) and w > 0 else None,
                         "barcode": re.sub(r"\D", "", str(i.get("barcode", "")))[:20], "notes": str(i.get("notes", ""))[:200],
                         "probe": probe if isinstance(probe, str) and re.fullmatch(r"[a-z0-9_]{1,16}", probe) else None})
        self.data["draft"]["items"] = keep
        self._save()

    async def apply_item_to_probe(self, item: dict, context=None) -> None:
        """Set the probe's protein and weight on the controller from a draft item."""
        probe = item.get("probe")
        if not probe:
            return
        slug = _entity_slug(probe)
        sel, num = f"select.smoker_{slug}_protein", f"number.smoker_{slug}_weight"
        if self.hass.states.get(sel):
            await self.hass.services.async_call("select", "select_option", {"entity_id": sel, "option": item["profile"]},
                                                blocking=True, context=context)
        if item.get("weight_lb") and self.hass.states.get(num):
            st = self.hass.states.get(num)
            w = item["weight_lb"] if (st.attributes.get("unit_of_measurement") or "lb") == "lb" else item["weight_lb"] * 0.4536
            lo, hi = st.attributes.get("min"), st.attributes.get("max")
            if isinstance(hi, (int, float)):
                w = min(w, hi)
            if isinstance(lo, (int, float)):
                w = max(w, lo)
            await self.hass.services.async_call("number", "set_value", {"entity_id": num, "value": round(w, 1)},
                                                blocking=True, context=context)

    # ---- photos + AI ----
    async def pick_ai_entity(self, requested: str | None) -> str:
        """Which AI task reads the photos: the one asked for, the package's choice, HA's default, else any that can.

        Without an entity_id, ai_task.generate_data needs a default AI task set in Settings > AI, which many installs
        don't have ("No entity_id provided and no preferred entity set").
        """
        def can_read_photos(eid: str | None) -> bool:
            st = self.hass.states.get(eid) if eid else None
            return st is not None and bool(int(st.attributes.get("supported_features") or 0) & 2)  # SUPPORT_ATTACHMENTS

        if requested:  # only an AI task Home Assistant has (it's a query parameter from the page)
            if not re.fullmatch(r"ai_task\.[a-z0-9_]+", requested) or self.hass.states.get(requested) is None:
                raise ValueError(f"there's no AI task called {requested[:60]!r}")
            return requested
        from .package_install import _previous_choices

        def first_line() -> str:
            try:
                with open(self.hass.config.path("packages", "smoker.yaml"), encoding="utf-8") as f:
                    return f.readline()
            except OSError:
                return ""

        # The AI task the Smoker package was installed with.
        chosen = _previous_choices(await self.hass.async_add_executor_job(first_line)).get("ai_task")
        if can_read_photos(chosen):
            return chosen
        try:  # Home Assistant's own default (Settings > AI)
            from homeassistant.components.ai_task import DATA_PREFERENCES

            pref = getattr(self.hass.data.get(DATA_PREFERENCES), "gen_data_entity_id", None)
            if can_read_photos(pref):
                return pref
        except ImportError:
            pass
        able = sorted(s.entity_id for s in self.hass.states.async_all("ai_task") if can_read_photos(s.entity_id))
        if able:
            return able[0]
        raise ValueError("there's no AI in Home Assistant that can read photos. Add one (e.g. Google Generative AI "
                         "under Settings > Devices & services) and try again")

    async def identify(self, images: list[tuple[str, bytes]], ai_entity: str | None, context=None) -> list[dict]:
        if not images:
            raise ValueError("no photos")
        entity = await self.pick_ai_entity(ai_entity)  # before saving anything: say early if there's no AI
        media_dirs = self.hass.config.media_dirs or {}
        media_key = "local" if "local" in media_dirs else next(iter(media_dirs), None)
        if media_key is None:
            raise ValueError("Home Assistant has no media folder configured (needed to pass photos to the AI)")
        media_root = Path(media_dirs[media_key]) / SCAN_DIR
        stamp = time.strftime("%Y%m%d-%H%M%S")
        saved, attachments = [], []

        keep = set(self.data["draft"].get("photos", []))
        for e in self.data["entries"]:
            keep.update(e.get("photos", []))

        def write():
            media_root.mkdir(parents=True, exist_ok=True)
            self.photo_dir.mkdir(parents=True, exist_ok=True)
            # Tidy up: photos no draft or journal entry uses any more (older than 2 days, so a scan in progress stays).
            old = time.time() - 2 * 86400
            for folder in (media_root, self.photo_dir):
                for f in folder.glob("*.*"):
                    if SCAN_NAME.fullmatch(f.name) and f.name not in keep and f.stat().st_mtime < old:
                        f.unlink(missing_ok=True)
            # Re-encoded without EXIF first: a phone photo can carry where it was taken, and these are kept and sent
            # to the AI provider. Anything that isn't a picture is refused here.
            clean = []
            for ctype, body in images[:MAX_PHOTOS]:
                clean.append(strip_metadata(body, "png" if "png" in ctype else "jpg"))
            for n, (body, ext) in enumerate(clean):
                name = f"{stamp}-{uuid.uuid4().hex[:6]}-{n}.{ext}"
                (media_root / name).write_bytes(body)
                (self.photo_dir / name).write_bytes(body)
                saved.append(name)

        await self.hass.async_add_executor_job(write)
        for name in saved:
            attachments.append({"media_content_id": f"media-source://media_source/{media_key}/{SCAN_DIR}/{name}",
                                "media_content_type": "image/png" if name.endswith(".png") else "image/jpeg"})
        data: dict[str, Any] = {
            "task_name": "Smoker: identify what's being cooked",
            "instructions": IDENTIFY_INSTRUCTIONS.format(profiles=", ".join(PROFILES)),
            "attachments": attachments,
        }
        data["entity_id"] = entity
        resp = await self.hass.services.async_call("ai_task", "generate_data", data, blocking=True, return_response=True,
                                                   context=context)
        text = (resp or {}).get("data") if isinstance(resp, dict) else None
        items = parse_items(text if isinstance(text, str) else json.dumps(text))
        # Append to the draft (several scans before a cook add up).
        self.data["draft"]["items"] = (self.data["draft"]["items"] + items)[-12:]
        self.data["draft"]["photos"] = (self.data["draft"].get("photos", []) + saved)[-MAX_PHOTOS:]
        self._save()
        return items


def _journal(request: web.Request) -> Journal:
    return request.app["hass"].data[DATA]


class JournalView(HomeAssistantView):
    url = "/api/smoker/journal"
    name = "api:smoker:journal"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        return self.json(_journal(request).data)


class JournalEntryView(HomeAssistantView):
    url = "/api/smoker/journal/{entry_id}"
    name = "api:smoker:journal:entry"
    requires_auth = True

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return self.json_message("invalid JSON", 400)
        try:
            e = _journal(request).update_entry(entry_id, body if isinstance(body, dict) else {})
        except ValueError as err:
            return self.json_message(str(err), 400)
        return self.json(e) if e else self.json_message("not found", 404)

    async def delete(self, request: web.Request, entry_id: str) -> web.Response:
        if not request["hass_user"].is_admin:
            return self.json_message("admin only", 403)
        return self.json({"deleted": _journal(request).delete_entry(entry_id)})


class DraftView(HomeAssistantView):
    url = "/api/smoker/draft"
    name = "api:smoker:draft"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        j = _journal(request)
        try:
            body = await request.json()
        except ValueError:
            return self.json_message("invalid JSON", 400)
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list):
            return self.json_message("items must be a list", 400)
        old = {i["id"]: i.get("probe") for i in j.data["draft"]["items"]}
        j.set_draft_items(items)
        problems = []
        for i in j.data["draft"]["items"]:
            if i.get("probe") and old.get(i["id"]) != i["probe"]:
                try:
                    await j.apply_item_to_probe(i, self.context(request))  # newly assigned: set the probe's protein and weight
                except Exception as err:  # noqa: BLE001 - one bad item mustn't stop the rest
                    _LOGGER.warning("Couldn't set %s from %s: %s", i["probe"], i.get("name"), err)
                    problems.append(f"{i.get('name') or 'item'}: {err}")
        return self.json({**j.data["draft"], "problems": problems})


class IdentifyView(HomeAssistantView):
    url = "/api/smoker/identify"
    name = "api:smoker:identify"
    requires_auth = True

    busy: set[str] = set()  # users with a scan in progress: one at a time each (each one is an AI call)

    async def post(self, request: web.Request) -> web.Response:
        j = _journal(request)
        user = request["hass_user"].id
        if user in self.busy:
            return self.json_message("a scan is already being read: wait for it to finish", 429)
        self.busy.add(user)
        try:
            return await self._identify(request, j)
        finally:
            self.busy.discard(user)

    async def _identify(self, request: web.Request, j: Journal) -> web.Response:
        images: list[tuple[str, bytes]] = []
        total = 0
        try:
            reader = await request.multipart()
        except (AssertionError, ValueError, KeyError):
            return self.json_message("send the photos as multipart/form-data", 400)
        async for part in reader:
            if part.name != "photo" or len(images) >= MAX_PHOTOS:
                continue
            ctype = part.headers.get("Content-Type", "image/jpeg")
            if not ctype.startswith("image/"):
                continue
            body = bytearray()
            while chunk := await part.read_chunk(64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_PHOTO_BYTES:
                    return self.json_message("photo too large (max 8 MB)", 413)
                if total + len(body) > MAX_UPLOAD_BYTES:
                    return self.json_message(f"photos too large together (max {MAX_UPLOAD_BYTES // 2**20} MB)", 413)
            total += len(body)
            images.append((ctype, bytes(body)))
        try:
            items = await j.identify(images, request.query.get("ai_task") or None, self.context(request))
        except Exception as err:  # noqa: BLE001 - report AI/config problems to the page
            _LOGGER.warning("Identify failed: %s", err)
            return self.json_message(f"Couldn't identify: {err}", 400)
        return self.json({"items": items, "draft": j.data["draft"]})


GRILL_PHOTO_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def strip_metadata(body: bytes, ext: str) -> tuple[bytes, str]:
    """A photo without EXIF (a phone photo can carry where it was taken) and anything else but the pixels: the grill
    photo is served to the controller, label photos go to the AI provider. Re-encoded as JPEG (PNG keeps
    transparency); unreadable or absurdly large: refused rather than kept as is."""
    import io
    import warnings

    from PIL import Image, ImageOps

    # Opening only reads the header: the size is checked here, before anything is decoded. (Pillow's own
    # Image.MAX_IMAGE_PIXELS is left alone: it's shared with every other integration in Home Assistant.)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(body))
        w, h = img.size
    except Exception as err:  # noqa: BLE001
        raise ValueError("couldn't read that photo") from err
    if w * h > MAX_PIXELS:
        raise ValueError("that photo has too many pixels")
    try:
        img = ImageOps.exif_transpose(img)  # keep the way up the phone meant, then drop the EXIF
    except Exception as err:  # noqa: BLE001
        raise ValueError("couldn't read that photo") from err
    out = io.BytesIO()
    if ext == "png" or img.mode in ("RGBA", "LA", "P"):
        img.save(out, "PNG", optimize=True)
        return out.getvalue(), "png"
    img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue(), "jpg"


def _uploaded_grill_photo(hass) -> Path | None:
    for ext in ("jpg", "png", "webp"):
        f = Path(hass.config.path(".storage", "smoker_photos", f"grill.{ext}"))
        if f.is_file():
            return f
    return None


def _grill_photo_key(hass, new: bool = False) -> str:
    """The secret part of the grill photo's address (blocking). A new one with every upload, so an address handed out
    for an earlier photo stops working; made on first use for a photo uploaded before addresses had one."""
    f = Path(hass.config.path(".storage", "smoker_photos", "grill.key"))
    if not new:
        try:
            key = f.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-f]{32}", key):
                return key
        except OSError:
            pass
    key = secrets.token_hex(16)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(key, encoding="utf-8")
    return key


def _grill_photo_url(hass, photo: Path) -> str:
    """Where the controller and the page load the uploaded photo (blocking)."""
    return f"/api/smoker/grill_photo/image/{_grill_photo_key(hass)}?v={int(photo.stat().st_mtime)}"


class GrillPhotoView(HomeAssistantView):
    """The user's own grill photo, shown (with the live readings pinned on it) instead of the drawing.

    GET    -> {"url": ...}: a photo uploaded from the dashboard (Setup → Grill photo), at an address with a secret
              part (see GrillPhotoImageView), or one saved by hand as www/smoker/grill.(png|jpg|jpeg|webp); null if
              there's none.
    POST   -> upload one (multipart field "photo", JPEG/PNG/WebP, max 8 MB); replaces the previous one (admin).
    DELETE -> remove the uploaded one (admin).
    """

    url = "/api/smoker/grill_photo"
    name = "api:smoker:grill_photo"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]

        def find():
            up = _uploaded_grill_photo(hass)
            if up is not None:
                return _grill_photo_url(hass, up)
            for ext in ("png", "jpg", "jpeg", "webp"):
                f = Path(hass.config.path("www", "smoker", f"grill.{ext}"))
                if f.is_file():
                    return f"/local/smoker/grill.{ext}?v={int(f.stat().st_mtime)}"
            return None

        return self.json({"url": await hass.async_add_executor_job(find)})

    async def post(self, request: web.Request) -> web.Response:
        if not request["hass_user"].is_admin:
            return self.json_message("admin only", 403)
        hass = request.app["hass"]
        try:
            reader = await request.multipart()
        except (AssertionError, ValueError, KeyError):
            return self.json_message("send the photo as multipart/form-data", 400)
        body, ctype = None, ""
        async for part in reader:
            if part.name != "photo":
                continue
            ctype = (part.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in GRILL_PHOTO_EXT:
                return self.json_message("use a JPEG, PNG or WebP photo", 400)
            buf = bytearray()
            while chunk := await part.read_chunk(64 * 1024):
                buf.extend(chunk)
                if len(buf) > MAX_PHOTO_BYTES:
                    return self.json_message("photo too large (max 8 MB)", 413)
            body = bytes(buf)
            break
        if not body:
            return self.json_message("no photo", 400)
        ext = GRILL_PHOTO_EXT[ctype]

        def save():
            folder = Path(hass.config.path(".storage", "smoker_photos"))
            folder.mkdir(parents=True, exist_ok=True)
            data, out_ext = strip_metadata(body, ext)
            for old in folder.glob("grill.*"):
                old.unlink(missing_ok=True)
            f = folder / f"grill.{out_ext}"
            f.write_bytes(data)
            _grill_photo_key(hass, new=True)
            return _grill_photo_url(hass, f)

        try:
            url = await hass.async_add_executor_job(save)
        except ValueError as err:
            return self.json_message(str(err), 400)
        return self.json({"url": url})

    async def delete(self, request: web.Request) -> web.Response:
        if not request["hass_user"].is_admin:
            return self.json_message("admin only", 403)
        hass = request.app["hass"]

        def remove():
            up = _uploaded_grill_photo(hass)
            if up is not None:
                up.unlink(missing_ok=True)
            Path(hass.config.path(".storage", "smoker_photos", "grill.key")).unlink(missing_ok=True)

        await hass.async_add_executor_job(remove)
        return self.json({"url": None})


class GrillPhotoImageView(HomeAssistantView):
    """The uploaded grill photo itself. Not behind a login so the smoker controller's own page (another address on
    the network, which has no Home Assistant login) can show it too, but only at its address with the secret part:
    /api/smoker/grill_photo/image/<key>, which logged-in users get from GET /api/smoker/grill_photo and the page passes
    to the controller ("Grill photo URL"). (Not a Home Assistant signed path: those stop working at every restart,
    and the controller keeps the address.)"""

    url = "/api/smoker/grill_photo/image/{key}"
    name = "api:smoker:grill_photo_image"
    requires_auth = False

    async def get(self, request: web.Request, key: str) -> web.StreamResponse:
        hass = request.app["hass"]

        def find():
            f = _uploaded_grill_photo(hass)
            if f is None or not re.fullmatch(r"[0-9a-f]{32}", key):
                return None
            return f if hmac.compare_digest(_grill_photo_key(hass), key) else None

        f = await hass.async_add_executor_job(find)
        if f is None:
            return self.json_message("not found", 404)
        return web.FileResponse(f, headers={"Cache-Control": "private, max-age=86400"})


class PhotoView(HomeAssistantView):
    url = "/api/smoker/photo/{name}"
    name = "api:smoker:photo"
    requires_auth = True

    async def get(self, request: web.Request, name: str) -> web.StreamResponse:
        if not re.fullmatch(r"[0-9a-f-]+\.(jpg|png)", name):
            return self.json_message("not found", 404)
        path = _journal(request).photo_dir / name
        if not await request.app["hass"].async_add_executor_job(path.is_file):
            return self.json_message("not found", 404)
        return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


async def async_setup_journal(hass: HomeAssistant) -> Journal:
    if DATA in hass.data:  # reloaded: views are still registered, listen again
        j = hass.data[DATA]
        if getattr(j, "unsub", None) is None:
            j.unsub = hass.bus.async_listen("esphome.smoker_cook_complete", j.handle_cook_complete)
        j._publish()  # its sensor was removed with the entry
        return j
    j = Journal(hass)
    await j.async_load()
    hass.data[DATA] = j
    for view in (JournalView(), JournalEntryView(), DraftView(), IdentifyView(), PhotoView(), GrillPhotoView(), GrillPhotoImageView()):
        hass.http.register_view(view)
    j.unsub = hass.bus.async_listen("esphome.smoker_cook_complete", j.handle_cook_complete)
    return j


def async_unload_journal(hass: HomeAssistant) -> None:
    j = hass.data.get(DATA)
    if j and j.unsub:
        j.unsub()
        j.unsub = None
