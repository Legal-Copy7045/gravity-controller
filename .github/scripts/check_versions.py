#!/usr/bin/env python3
"""Check every part of the project carries the version in VERSION.

Usage: check_versions.py [tag]   (tag like v0.1.0 must match VERSION too)
"""

import json
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[2]


def yaml_version(path: str) -> str:
    m = re.search(r'^\s*project_version:\s*"?([^"\s]+)"?', (REPO / path).read_text(), re.M)
    return m.group(1) if m else "missing"


def main() -> None:
    expected = (REPO / "VERSION").read_text().strip()
    found = {
        "custom_components/smoker/manifest.json": json.loads(
            (REPO / "custom_components/smoker/manifest.json").read_text()
        )["version"],
        "firmware/core.yaml": yaml_version("firmware/core.yaml"),
    }
    changelog = (REPO / "CHANGELOG.md").read_text()
    found["CHANGELOG.md"] = expected if f"## [{expected}]" in changelog else "no section"
    if len(sys.argv) > 1 and sys.argv[1]:
        found["git tag"] = sys.argv[1].removeprefix("refs/tags/").removeprefix("v")
    bad = {k: v for k, v in found.items() if v != expected}
    for k, v in found.items():
        print(f"{'OK ' if v == expected else 'BAD'} {k}: {v}")
    if bad:
        sys.exit(f"Version mismatch: VERSION is {expected}")


if __name__ == "__main__":
    main()
