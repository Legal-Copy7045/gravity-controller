#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a version (used as release notes)."""

from pathlib import Path
import re
import sys

text = (Path(__file__).resolve().parents[2] / "CHANGELOG.md").read_text()
version = sys.argv[1].removeprefix("v")
m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
if not m:
    sys.exit(f"No CHANGELOG section for {version}")
print(m.group(1).strip())
