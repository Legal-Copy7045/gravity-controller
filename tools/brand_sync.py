#!/usr/bin/env python3
"""Copy brand/ (mark, favicon, line icons) into the pages that inline them, so they never drift apart.

    python3 tools/brand_sync.py          # update the pages
    python3 tools/brand_sync.py --check  # CI: fail if a page is out of date

Targets: the Home Assistant dashboard (custom_components/smoker/frontend/page.html), the controller's own page
(firmware/device-ui/ui.js), the web installer (web/index.html), and the integration's own icon
(custom_components/smoker/brand/icon.png, icon@2x.png: what Home Assistant shows for the integration).
"""

import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "brand"


def strip_comments(s):
    return re.sub(r"\s*<!--.*?-->", "", s, flags=re.S)


def one_line(s):
    return re.sub(r">\s+<", "><", re.sub(r"\s+", " ", s)).strip()


def mark(cls="mark", prefix="mk-"):
    """The mark as an inline, decorative SVG (ids prefixed so several copies can share a page)."""
    s = one_line(strip_comments((B / "mark.svg").read_text()))
    s = s.replace('role="img" aria-label="Smoker"', f'class="{cls}" aria-hidden="true"')
    for i in ("tile", "flame"):
        s = s.replace(f'id="{i}"', f'id="{prefix}{i}"').replace(f"url(#{i})", f"url(#{prefix}{i})")
    return s


def favicon_uri():
    return "data:image/svg+xml," + urllib.parse.quote(one_line((B / "favicon.svg").read_text()))


def sprite():
    return one_line(strip_comments((B / "icons.svg").read_text()))


def sync_dashboard(s):
    s = re.sub(r'<link rel="icon" href="data:image/svg\+xml,[^"]*">', f'<link rel="icon" href="{favicon_uri()}">', s, count=1)
    s = re.sub(r"(<!-- brand/icons\.svg \(Smoker line icons\) -->\n)<svg .*?</svg>\n(?=<!--|<div)",
               lambda m: m.group(1) + sprite() + "\n", s, count=1, flags=re.S)
    s = re.sub(r'<svg class="mark" .*?</svg>', lambda m: mark(), s, count=1, flags=re.S)
    return s


def sync_device(s):
    s = re.sub(r"^const FAVICON = '.*?';$", lambda m: f"const FAVICON = '{favicon_uri()}';", s, count=1, flags=re.M)
    s = re.sub(r"^const MARK = '.*?';$", lambda m: "const MARK = '%s';" % mark().replace("'", "\\'"), s, count=1, flags=re.M)
    s = re.sub(r"^const ICONS = `.*?`;$", lambda m: "const ICONS = `%s`;" % sprite().replace("`", ""), s, count=1,
               flags=re.M | re.S)
    return s


def sync_installer(s):
    s = re.sub(r'<link rel="icon" href="data:image/svg\+xml,[^"]*">', f'<link rel="icon" href="{favicon_uri()}">', s, count=1)
    s = re.sub(r'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" class="mark" aria-hidden="true">.*?</svg>'
               r'|<svg class="mark" .*?</svg>', lambda m: mark(prefix="in-"), s, count=1, flags=re.S)
    return s


TARGETS = [
    (ROOT / "custom_components/smoker/frontend/page.html", sync_dashboard),
    (ROOT / "firmware/device-ui/ui.js", sync_device),
    (ROOT / "web/index.html", sync_installer),
]


# Copied as they are: the integration's icon (Home Assistant reads custom_components/<domain>/brand/).
COPIES = [(B / "icon.png", ROOT / "custom_components/smoker/brand/icon.png"),
          (B / "icon@2x.png", ROOT / "custom_components/smoker/brand/icon@2x.png")]


def main():
    check = "--check" in sys.argv
    stale = []
    for src, dst in COPIES:
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            stale.append(dst.relative_to(ROOT))
            if not check:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(src.read_bytes())
    for path, fn in TARGETS:
        old = path.read_text(encoding="utf-8")
        new = fn(old)
        if new != old:
            stale.append(path.relative_to(ROOT))
            if not check:
                path.write_text(new, encoding="utf-8")
    if check and stale:
        print("brand/ changed but these pages weren't updated (run tools/brand_sync.py):", *stale, sep="\n  ")
        sys.exit(1)
    print(("out of date: " if check else "updated: ") + (", ".join(map(str, stale)) or "nothing"))


if __name__ == "__main__":
    main()
