"""The feature catalogue: regression/catalogue/*.yaml.

Each entry:
    - feature: "Power-cut recovery: resumes the cook and powers the grill back on"
      since: 1.4.0
      docs: docs/features.md#power-cut-recovery
      checks: [SIM-031, CORE-004]        # IDs from regression/ids/*.yaml (optional)
      match: ["sim:scenarios: scenario 4", "core:.*recovery"]   # regexes over "<stage>:<check>" (optional)

A check belongs to the first feature that lists its ID or whose `match` finds it. A feature with neither, or whose
checks never ran, shows as uncovered / not run in the report.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def load_catalogue():
    out = []
    for p in sorted((HERE / "catalogue").glob("*.yaml")):
        for item in yaml.safe_load(p.read_text(encoding="utf-8")) or []:
            item["area"] = p.stem
            item["_re"] = [re.compile(m, re.I) for m in item.get("match") or []]
            out.append(item)
    return out


def claims(item, stage, rid, check):
    return rid in (item.get("checks") or []) or any(r.search(f"{stage}:{check}") for r in item["_re"])


def feature_for(cat, stage, rid, check):
    for item in cat:
        if claims(item, stage, rid, check):
            return item["feature"]
    return ""
