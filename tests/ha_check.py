#!/usr/bin/env python3
"""Validate the Home Assistant side with Home Assistant's own config checker.

Builds a throwaway config dir with homeassistant/packages/smoker.yaml and the
custom_components/smoker integration, runs `hass --script check_config`, and
fails on any error in the package (automations, scripts, templates, helpers).
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG = """
homeassistant:
  name: Test
  unit_system: us_customary
  time_zone: America/Chicago
  packages: !include_dir_named packages
http:
frontend:
logbook:
history:
"""


def main():
    d = tempfile.mkdtemp(prefix="smoker-ha-")
    try:
        os.makedirs(os.path.join(d, "packages"))
        shutil.copy(os.path.join(ROOT, "homeassistant/packages/smoker.yaml"), os.path.join(d, "packages/smoker.yaml"))
        shutil.copytree(os.path.join(ROOT, "custom_components"), os.path.join(d, "custom_components"))
        with open(os.path.join(d, "configuration.yaml"), "w") as f:
            f.write(CONFIG)
        r = subprocess.run([sys.executable, "-m", "homeassistant", "--script", "check_config", "-c", d],
                           capture_output=True, text=True, timeout=600)
        out = r.stdout + r.stderr
        print(out[-6000:])
        errors = [l for l in out.splitlines() if l.startswith("ERROR:homeassistant.components") or "Invalid config" in l
                  or "Failed config" in l]
        for e in errors:
            print("ERROR LINE:", e)
        bad = r.returncode != 0 or bool(errors)
        # Integration imports cleanly (config flow + panel module).
        sys.path.insert(0, d)
        import importlib
        for m in ["custom_components.smoker", "custom_components.smoker.config_flow", "custom_components.smoker.panel"]:
            importlib.import_module(m)
        from custom_components.smoker.panel import build_page
        page = build_page()
        assert "hdHA" in page and "/*COMMON*/" not in page and "Smoker · live" in page, "page build"
        print("integration import + page build OK")
        if bad:
            print("HA config check FAILED")
            sys.exit(1)
        print("HA config check passed")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
