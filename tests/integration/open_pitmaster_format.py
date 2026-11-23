"""The Open Pitmaster record rules: a copy of validate() from github.com/Legal-Copy7045/open-pitmaster build/build.py
(the service applies the same rules). Keep in step with tests/fixtures/open_pitmaster_examples.json, a copy of that
repository's format/examples.json."""

import re

CUTS = ["Pork shoulder", "Brisket", "Ribs", "Beef roast", "Poultry", "Sausage", "Fish", "Auto"]
SEASONS = ["winter", "spring", "summer", "autumn"]
TAGS = ["juicy", "tender", "dry", "tough", "undercooked", "just right", "overcooked", "great bark", "soft bark", "good smoke", "too smoky", "too little smoke", "fat rendered", "fat not rendered"]
FIELDS = ["v", "id", "grill", "release", "season", "cut", "weight_lb", "wrapped", "pit_f", "target_f", "stall_h",
          "total_h", "outside_f", "rating", "tags"]
MIN_N = 3  # a group needs this many cooks before its averages are published


def _num(v, lo, hi, step, null=True):
    if v is None:
        return null
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        return False
    return abs(round(v / step) * step - v) < 1e-6


def validate(r) -> str | None:
    """None if the record is exactly the format, else why not."""
    if not isinstance(r, dict):
        return "record must be an object"
    for k in r:
        if k not in FIELDS:
            return f"unexpected field {k}"
    checks = {
        "v": r.get("v") == 1,
        "id": isinstance(r.get("id"), str) and re.fullmatch(r"[0-9a-f]{32}", r["id"]) is not None,
        "grill": r.get("grill") == "gravity980",
        "release": isinstance(r.get("release"), str) and re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,4}", r["release"]) is not None,
        "season": r.get("season") in SEASONS,
        "cut": r.get("cut") in CUTS,
        "weight_lb": _num(r.get("weight_lb"), 0.5, 25, 0.5),
        "wrapped": r.get("wrapped") is None or isinstance(r.get("wrapped"), bool),
        "pit_f": _num(r.get("pit_f"), 200, 700, 5),
        "target_f": _num(r.get("target_f"), 100, 250, 1),
        "stall_h": _num(r.get("stall_h"), 0, 24, 0.1),
        "total_h": _num(r.get("total_h"), 0.5, 36, 0.1, null=False),
        "outside_f": _num(r.get("outside_f"), -10, 110, 5),
        "tags": isinstance(r.get("tags"), list) and all(t in TAGS for t in r["tags"]) and len(set(r["tags"])) == len(r["tags"]),
        "rating": r.get("rating") is None or (isinstance(r.get("rating"), int) and not isinstance(r.get("rating"), bool) and 1 <= r["rating"] <= 5),
    }
    for k in FIELDS:
        if k not in r:
            return f"missing field {k}"
        if not checks[k]:
            return f"bad value for {k}"
    if r["stall_h"] is not None and r["stall_h"] > r["total_h"]:
        return "stall longer than the cook"
    return None


