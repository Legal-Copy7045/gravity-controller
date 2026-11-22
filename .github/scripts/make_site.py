#!/usr/bin/env python3
"""Assemble the GitHub Pages site: web installer page, firmware and manifest.

Usage: make_site.py <output dir> <esphome build dir> <device yaml>

firmware/manifest.json serves two purposes:
  * ESP Web Tools reads `builds[].parts` to flash a new board from the browser.
  * ESPHome's http_request update platform reads `version` and `builds[].ota`
    to offer over-the-air updates in Home Assistant (the device checks every 6 h).
(Adapted from the Magic-bHAnds project's make_site.py.)
"""

import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import urllib.request

REPO = Path(__file__).resolve().parents[2]
# ESP Web Tools is published with the site rather than loaded from a CDN, so the
# page that flashes boards (and sees the Wi-Fi password) runs only checked code.
# To upgrade: change both values; the integrity is npm's "dist.integrity".
ESP_WEB_TOOLS_VERSION = "10.4.0"
ESP_WEB_TOOLS_INTEGRITY = (
    "sha512-3pwkeFFm5Fj7UQo8SJNYK5RXrtNCpq6X9QoI6bMT4GBZWgrJqjn0YvM9ihG74BtMoSFYXfmDtkehuxe50PTMPQ=="
)
RELEASES = "https://github.com/Legal-Copy7045/gravity-controller/releases"
TITLE, SLUG = "Gravity 980 Smoker Bridge", "gravity980-bridge"


def project_version(yaml_path: Path) -> str:
    m = re.search(r'^\s*project_version:\s*"?([^"\s]+)"?', yaml_path.read_text(), re.M)
    if not m:
        sys.exit(f"project_version substitution not found in {yaml_path}")
    return m.group(1)


def vendor_esp_web_tools(out: Path) -> None:
    url = f"https://registry.npmjs.org/esp-web-tools/-/esp-web-tools-{ESP_WEB_TOOLS_VERSION}.tgz"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    algo, _, expected = ESP_WEB_TOOLS_INTEGRITY.partition("-")
    actual = base64.b64encode(hashlib.new(algo, data).digest()).decode()
    if actual != expected:
        sys.exit(f"esp-web-tools {ESP_WEB_TOOLS_VERSION}: hash mismatch ({algo}-{actual})")
    dest = out / "esp-web-tools"
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if not member.isfile():
                continue
            if name.startswith("package/dist/web/") and "/" not in name.removeprefix("package/dist/web/"):
                target = dest / Path(name).name
            elif name == "package/LICENSE":
                target = dest / "LICENSE"
            else:
                continue
            target.write_bytes(tar.extractfile(member).read())
    if not (dest / "install-button.js").is_file():
        sys.exit("esp-web-tools: install-button.js missing from the package")


def main() -> None:
    out, build_dir, yaml_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    version = project_version(yaml_path)
    factory, ota = build_dir / "firmware.factory.bin", build_dir / "firmware.ota.bin"
    for f in (factory, ota):
        if not f.is_file():
            sys.exit(f"missing build output: {f}")
    fw = out / "firmware"
    fw.mkdir(parents=True, exist_ok=True)
    shutil.copy(factory, fw / f"{SLUG}.factory.bin")
    shutil.copy(ota, fw / f"{SLUG}.ota.bin")
    manifest = {
        "name": TITLE,
        "version": version,
        "home_assistant_domain": "esphome",
        "new_install_prompt_erase": True,
        "builds": [
            {
                "chipFamily": "ESP32-S3",
                "parts": [{"path": f"{SLUG}.factory.bin", "offset": 0}],
                "ota": {
                    "path": f"{SLUG}.ota.bin",
                    "md5": hashlib.md5(ota.read_bytes()).hexdigest(),
                    "summary": f"{TITLE} {version}",
                    "release_url": f"{RELEASES}/tag/v{version}",
                },
            }
        ],
    }
    (fw / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    page = (REPO / "web" / "index.html").read_text().replace("{{VERSION}}", version)
    (out / "index.html").write_text(page)
    if "--no-vendor" not in sys.argv:
        vendor_esp_web_tools(out)
    (out / ".nojekyll").write_text("")
    print(f"{TITLE} {version} -> {out}")


if __name__ == "__main__":
    main()
