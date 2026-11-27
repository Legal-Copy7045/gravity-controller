#!/usr/bin/env python3
"""Which slow CI jobs this run needs (the `changes` job in build.yml). Writes firmware=/dashboards= to GITHUB_OUTPUT.

- pull_request: by the files the pull request changes (BASE...HEAD):
    firmware   -> firmware-build + firmware-tests (the ESP32 build, the simulated grill, the device page);
    dashboards -> home-assistant + integration (the package, the integration, the Home Assistant dashboard).
  Files that are neither (docs, the regression suite, which CI doesn't run, the notes) start neither; the quick checks always run.
- push to the default branch: everything when VERSION has no release tag yet (this push releases), nothing slow
  otherwise (the weekly run covers it).
- schedule / workflow_dispatch: everything.

Run it locally: EVENT=pull_request BASE=origin/main HEAD=HEAD python3 .github/scripts/changes.py
"""
import os
import re
import subprocess
import sys

# Only the dashboards, the integration and the package (and their tests): no firmware rebuild for these.
DASH_ONLY = re.compile(r"^(custom_components/|homeassistant/|tests/integration/|tests/ha_[a-z_]+\.py$|"
                       r"tests/render_page\.py$|tests/requirements-integration\.txt$|"
                       r"\.github/requirements/(ha-tests|integration-[a-z]+)\.(in|txt)$)")
# Only the controller (no Home Assistant code reads these): no Home Assistant jobs.
FW_ONLY = re.compile(r"^(components/|firmware/(?!device-ui/)|tests/[^/]*\.(cpp|h|yaml)$|tests/Makefile$|"
                     r"tests/(e2e|e2e_scenarios|webui_e2e|webui_bridge|fake_grill)[a-z_]*\.py$|"
                     r"\.github/requirements/(firmware|firmware-tests|build-tools|sign)\.(in|txt)$)")
# Neither: words and logs.
NEITHER = re.compile(r"^(docs/|regression/|\.claude/|[^/]+\.md$|LICENSE)")


def decide(files):
    fw = dash = False
    for f in files:
        if NEITHER.match(f):
            continue
        if DASH_ONLY.match(f):
            dash = True
        elif FW_ONLY.match(f):
            fw = True
        else:  # shared (device-ui, brand, VERSION, workflows, tools, regression/...): both
            fw = dash = True
    return fw, dash


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def main():
    event = os.environ.get("EVENT", "")
    if event == "pull_request":
        r = git("diff", "--name-only", f"{os.environ['BASE']}...{os.environ.get('HEAD') or 'HEAD'}")
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            fw = dash = True  # can't tell: test everything
        else:
            files = [f for f in r.stdout.splitlines() if f]
            fw, dash = decide(files)
            print(f"{len(files)} file(s) changed")
    elif event == "push":
        with open("VERSION") as fh:
            version = fh.read().strip()
        tagged = git("ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/v{version}").returncode == 0
        fw = dash = not tagged
        print(f"v{version} {'already released: quick checks only' if tagged else 'not released yet: full build and release'}")
    else:
        fw = dash = True
    print(f"firmware={str(fw).lower()} dashboards={str(dash).lower()}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as out:
        out.write(f"firmware={str(fw).lower()}\ndashboards={str(dash).lower()}\n")


if __name__ == "__main__":
    main()
