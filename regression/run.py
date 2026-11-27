#!/usr/bin/env python3
"""Full regression run: every test suite in the repo, one stage at a time, into regression/out/<stage>.json.
Answers the project standard's commands (STANDARD.md section 3.3; regression/profile.yaml):

    python3 regression/run.py check               # ci + quality + core, quiet: before a pull request is marked ready
    python3 regression/run.py                     # every stage but walkthrough (live when HA_URL is set)
    python3 regression/run.py --with-walkthrough  # ... and the walkthrough's crawl, side by side
    python3 regression/run.py --stage page --stage ci
    python3 regression/run.py report [--walkthrough]   # this project's reports (report.py, walkthrough_report.py)
    python3 regression/run.py brief|log|summary|manual|schema|walkthrough-due ...   # the standard's standard.py

Environment (paths to the venvs the suites need; see README.md):
    ESPHOME_PYTHON  python of a venv with esphome, aioesphomeapi and aiohttp (firmware, sim, device stages)
    HA_PYTHON       python of a venv with pytest-homeassistant-custom-component (integration, package stages)
    HA_URL          Home Assistant base URL for the read-only live stage (never committed); auth comes from the
                    session's proxy, so no token is read or printed here
The system python3 needs playwright (page and device stages).

Each stage writes {stage, prefix, started, finished, environment, results:[{id, key, feature, check, status, detail,
evidence}]} (key = check: the standard's name for it); the walkthrough's to out/walkthrough-checks.json.
IDs are stable: regression/ids/<stage>.yaml maps each check's key to its ID, append-only (see README.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
IDS = HERE / "ids"
sys.path.insert(0, str(HERE))
from catalogue import load_catalogue, feature_for  # noqa: E402

PREFIX = {"ci": "CI", "quality": "QA", "core": "CORE", "firmware": "FW", "sim": "SIM", "device": "DEV", "page": "PAGE",
          "integration": "INT", "package": "PKG", "live": "LIVE", "manual": "MAN", "walkthrough": "WT"}
ORDER = ["ci", "quality", "core", "firmware", "sim", "device", "page", "integration", "package", "live", "manual", "walkthrough"]


def select_stages(stage=None, live=False, with_walkthrough=False):
    """--stage NAME (repeatable) runs those; otherwise every regression stage (live only with --live), and the
    walkthrough only with --with-walkthrough."""
    if stage:
        return [s for s in ORDER if s in stage]
    return [s for s in ORDER if (s != "live" or live) and (s != "walkthrough" or with_walkthrough)]


def result_file(stage):
    """out/<stage>.json; the walkthrough's checks in walkthrough-checks.json (walkthrough.json is its inventory)."""
    return "walkthrough-checks.json" if stage == "walkthrough" else f"{stage}.json"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- stable IDs
_LINE = re.compile(r'^([A-Z]+-\d{3,})\s*:\s*(".*")\s*$')
_HIGH = re.compile(r"^# highest issued:\s*[A-Z]+-(\d+)\s*$")


class Ids:
    """key -> ID for one stage. Append-only: a new key gets the next number, nothing is renumbered or reused."""

    def __init__(self, stage: str):
        self.stage, self.prefix = stage, PREFIX[stage]
        self.path = IDS / f"{stage}.yaml"
        self.map: dict[str, str] = {}
        self.high = 0
        self.seen: set[str] = set()
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if m := _HIGH.match(line):
                    self.high = max(self.high, int(m.group(1)))
                elif m := _LINE.match(line):
                    self.map[json.loads(m.group(2))] = m.group(1)
                    self.high = max(self.high, int(m.group(1).split("-")[1]))

    def get(self, key: str) -> str:
        self.seen.add(key)
        if key not in self.map:
            self.high += 1
            self.map[key] = f"{self.prefix}-{self.high:03d}"
        return self.map[key]

    def save(self):
        IDS.mkdir(exist_ok=True)
        lines = [f"# Stable check IDs for the {self.stage} stage (regression/run.py). Append-only: never renumber or reuse",
                 "# an ID. Renamed a check? Edit its key here to keep its ID. A key no longer produced shows as skipped.",
                 f"# highest issued: {self.prefix}-{self.high:03d}"]
        for k, v in sorted(self.map.items(), key=lambda kv: int(kv[1].split("-")[1])):
            lines.append(f"{v}: {json.dumps(k, ensure_ascii=False)}")
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- helpers
FROM_LOGS = False


def run_logged(stage, name, cmd, env=None, timeout=3600):
    """Run a suite and keep its output in out/logs; with --from-logs, re-read the last run's output instead."""
    p = OUT / "logs" / f"{stage}-{name}.log"
    if FROM_LOGS and p.is_file():
        text = p.read_text()
        rc = int((OUT / "logs" / f"{stage}-{name}.rc").read_text()) if (OUT / "logs" / f"{stage}-{name}.rc").is_file() else 0
        return rc, text, 0.0, str(p.relative_to(ROOT))
    rc, out, secs = run(cmd, env=env, timeout=timeout)
    ev = log(stage, name, out)
    (OUT / "logs" / f"{stage}-{name}.rc").write_text(str(rc))
    return rc, out, secs, ev


def run(cmd, cwd=ROOT, env=None, timeout=3600):
    e = dict(os.environ)
    e.update(env or {})
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr, time.time() - t0
    except subprocess.TimeoutExpired as ex:
        out = (ex.stdout or b"").decode() if isinstance(ex.stdout, bytes) else (ex.stdout or "")
        return 124, out + f"\n(timed out after {timeout}s)", time.time() - t0
    except FileNotFoundError as ex:
        return 127, str(ex), time.time() - t0


def log(stage, name, text):
    p = OUT / "logs" / f"{stage}-{name}.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return str(p.relative_to(ROOT))


def tail(text, n=8):
    return " | ".join(text.strip().splitlines()[-n:])[-600:]


def strip_value(msg: str) -> str:
    """The check's words without the values it printed, so IDs stay stable: a ' -> result' part, '(<number>…)' groups,
    a trailing '(…)', ': <value>', a long quoted value, a list or a dict go; short quoted inputs ('Food 1 is done') stay."""
    m = msg.strip()
    head = m.split(" -> ")[0]
    if " -> " in m and head.count("(") == head.count(")") and head.count("'") % 2 == 0 and head.count('"') % 2 == 0:
        return head.strip()
    for _ in range(4):
        before = m
        m = re.sub(r":?\s+[\[{].*[\]}]$", "", m)  # a trailing list or dict
        q = re.match(r"""^(.*?)\s+(['"])(.*)\2$""", m)  # a trailing quoted value: long, or a code/number
        if q and (len(q.group(3)) >= 30 or (" " not in q.group(3) and (len(q.group(3)) >= 16 or re.search(r"\d", q.group(3))))):
            m = q.group(1)
        m = re.sub(r"\s*\(\d[^()]*\)", "", m)  # (225.0 -> 230.0), (6 pins)
        if m.endswith(")"):  # a balanced trailing (...) group
            depth, i = 0, len(m) - 1
            while i >= 0:
                depth += {")": 1, "(": -1}.get(m[i], 0)
                if depth == 0:
                    break
                i -= 1
            if i > 0 and m[i - 1] == " ":
                m = m[:i].rstrip()
        m = re.sub(r":\s+['\"\[{(\d-].*$", "", m)
        if m == before:
            break
    return m.strip().rstrip(":,").strip()


def parse_ok_fail(text: str):
    """Lines '  ok   msg' / '  FAIL msg', with '-- section' / 'scenario N: …' headers. -> [(key, check, ok, raw)]."""
    out, section, count = [], "", {}
    for line in text.splitlines():
        if m := re.match(r"^-- (.+)$", line):
            section = m.group(1).strip()
            continue
        if m := re.match(r"^scenario (\S+):\s*(.*)$", line):
            section = f"scenario {m.group(1)}"
            continue
        if m := re.match(r"^\s+(ok|FAIL)\s+(.*)$", line):
            check = strip_value(m.group(2))
            key = f"{section} › {check}" if section else check
            count[key] = count.get(key, 0) + 1
            if count[key] > 1:
                key = f"{key} [{count[key]}]"
            out.append((key, (f"{section}: " if section else "") + check, m.group(1) == "ok", m.group(2).strip()))
    return out


class Stage:
    def __init__(self, name, catalogue):
        self.name, self.ids, self.cat = name, Ids(name), catalogue
        self.results, self.started, self.env = [], now(), {}

    def add(self, key, check, status, detail="", evidence=""):
        rid = self.ids.get(key)
        self.results.append({"id": rid, "key": check, "feature": feature_for(self.cat, self.name, rid, check),
                             "check": check, "status": status, "detail": detail, "evidence": evidence})

    def run_failed(self, detail, evidence=""):
        self.results.append({"id": f"{PREFIX[self.name]}-RUN", "key": "RUN", "feature": "the suite itself", "check": "stage ran to the end",
                             "status": "fail", "detail": detail, "evidence": evidence})

    def lines(self, text, evidence, rc, label):
        got = parse_ok_fail(text)
        for key, check, ok, raw in got:
            self.add(key, check, "pass" if ok else "fail", "" if ok else raw, evidence)
        fails = sum(not ok for *_, ok, _ in got)
        if rc != 0 and not fails:
            self.run_failed(f"{label} exited {rc} without a failed check: {tail(text)}", evidence)
        return got

    def missing_as_skip(self, prefix=""):
        """Checks issued before but not produced this run (renamed/removed, or the run stopped early)."""
        for key, rid in self.ids.map.items():
            if key not in self.ids.seen and key.startswith(prefix):
                self.results.append({"id": rid, "key": key, "feature": feature_for(self.cat, self.name, rid, key), "check": key,
                                     "status": "skip", "detail": "not produced by this run (removed, renamed or not reached)",
                                     "evidence": ""})

    def save(self):
        self.ids.save()
        OUT.mkdir(exist_ok=True)
        data = {"stage": self.name, "prefix": PREFIX[self.name], "started": self.started, "finished": now(),
                "environment": self.env, "results": self.results}
        (OUT / result_file(self.name)).write_text(json.dumps(data, indent=1, ensure_ascii=False))
        c = {s: sum(r["status"] == s for r in self.results) for s in ("pass", "fail", "manual", "skip")}
        print(f"  {self.name}: {c}", flush=True)


def kill_sims():
    subprocess.run(["pkill", "-f", "tools/fake_grill.py"], capture_output=True)
    subprocess.run(["pkill", "-f", "smoker-host-test(-[a-z])?/program"], capture_output=True)
    subprocess.run(["pkill", "-f", "tests/webui_bridge.py"], capture_output=True)
    time.sleep(1)


def esphome_bin(args):
    py = args.esphome_python
    return str(Path(py).parent / "esphome") if py else "esphome"


# ---------------------------------------------------------------- stages
def stage_ci(st, args):
    """Release tooling and repo rules: versions, brand, privacy guard, package copy, shared blocks, workflow hygiene."""
    for key, cmd in [("versions agree (VERSION, manifest, firmware, CHANGELOG)", ["python3", ".github/scripts/check_versions.py"]),
                     ("brand files in sync", ["python3", "tools/brand_sync.py", "--check"]),
                     ("privacy guard (commits and files)", ["python3", ".github/scripts/privacy_guard.py"]),
                     ("release notes build from CHANGELOG", ["python3", ".github/scripts/release_notes.py",
                                                             (ROOT / "VERSION").read_text().strip()]),
                     ("regression tooling tests (stage selection, walkthrough checks, both reports)",
                      ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "regression/tests"])]:
        rc, out, _ = run(cmd)
        st.add(key, key, "pass" if rc == 0 else "fail", "" if rc == 0 else tail(out), log("ci", key.split()[0], out))
    a, b = ROOT / "homeassistant/packages/smoker.yaml", ROOT / "custom_components/smoker/package/smoker.yaml"
    same = a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)
    st.add("package copy identical", "the integration's bundled package equals homeassistant/packages/smoker.yaml",
           "pass" if same else "fail", "" if same else "copy differs")
    page = (ROOT / "custom_components/smoker/frontend/page.html").read_text(encoding="utf-8")
    ui = (ROOT / "firmware/device-ui/ui.js").read_text(encoding="utf-8")
    for name in re.findall(r"// ==== BEGIN (.+?) \(shared block\) ====", page):
        b_, e_ = f"// ==== BEGIN {name} (shared block) ====", f"// ==== END {name} (shared block) ===="
        blk = [s[s.index(b_):s.index(e_)] if b_ in s and e_ in s else None for s in (page, ui)]
        ok = blk[0] is not None and blk[0] == blk[1]
        st.add(f"shared block {name}", f"shared block '{name}' identical in both dashboards", "pass" if ok else "fail",
               "" if ok else "differs or missing in ui.js")
    wf = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    uses = [u for f in sorted((ROOT / ".github/workflows").glob("*.yml"))
            for u in re.findall(r"uses:\s*(\S+)", f.read_text(encoding="utf-8"))]
    unpinned = [u for u in uses if not re.search(r"@[0-9a-f]{40}$", u) and not u.startswith("./")]
    st.add("actions pinned", "every GitHub Action pinned to a full commit SHA", "fail" if unpinned else "pass", ", ".join(unpinned))
    st.add("default permissions", "workflow sets top-level permissions", "pass" if re.search(r"^permissions:", wf, re.M) else "fail")
    sign_env = "release-signing" in wf and "OTA_SIGNING_KEY" in wf
    st.add("signing key in protected environment", "the OTA signing key is read only in the release-signing environment",
           "pass" if sign_env else "fail")
    st.add("no pull_request_target", "no pull_request_target trigger (untrusted code with secrets)",
           "fail" if "pull_request_target" in wf else "pass")
    tracked = run(["git", "ls-files"])[1].split()
    bad = [f for f in tracked if f.endswith((".pem", ".key")) or Path(f).name in ("secrets.yaml", "signing_key.pem")]
    st.add("no keys or secrets tracked", "no key or secrets file is in git", "fail" if bad else "pass", ", ".join(bad))
    ign = (ROOT / ".gitignore").read_text()
    st.add("regression out ignored", "regression/out/ is git-ignored", "pass" if "regression/out/" in ign else "fail")


def stage_core(st, args):
    rc, out, secs, ev = run_logged("core", "test_core", ["make", "-C", "tests"], timeout=1800)
    section, fails, seen = None, {}, []
    for line in out.splitlines():
        if line.startswith(("make", "./", "g++", "c++", "cc ")) or not line.strip():
            continue
        if line.startswith("  FAIL") and section:
            fails.setdefault(section, []).append(line.strip())
            continue
        if line.startswith(" ") or "check(s) FAILED" in line or line.strip() == "all tests passed":
            continue
        s = re.sub(r"\s+ok$", "", line.strip())
        if s not in seen:
            seen.append(s)
        section = s
    for s in seen:
        st.add(s, f"core tests: {s}", "fail" if s in fails else "pass", "; ".join(fails.get(s, [])), ev)
    st.env["seconds"] = round(secs)
    if rc != 0 and not fails:
        st.run_failed(f"make -C tests exited {rc}: {tail(out)}", ev)
    elif rc == 0 and "all tests passed" not in out:
        st.run_failed("no 'all tests passed' line", ev)
    st.missing_as_skip()


def stage_firmware(st, args):
    es = esphome_bin(args)
    st.env["esphome"] = run([es, "version"])[1].strip()
    for f in ["firmware/gravity980-bridge.yaml", "tests/configs/no-ha.yaml", "tests/host-bridge.yaml"]:
        key = f"config valid: {f}"
        tmpkey = None
        if f.endswith("gravity980-bridge.yaml") and not (ROOT / "firmware/signing_key.pem").exists():
            tmpkey = ROOT / "firmware/signing_key.pem"  # throwaway key, removed after: the real one never lives here
            run([str(Path(es).parent / "espsecure"), "generate-signing-key", "--version", "2", "--scheme", "rsa3072", str(tmpkey)])
        try:
            rc, out, _ = run([es, "config", f], timeout=600)
            st.add(key, key, "pass" if rc == 0 else "fail", "" if rc == 0 else tail(out), log("firmware", Path(f).stem + "-config", out))
            if args.compile:
                key = f"compiles: {f}"
                if f.endswith("no-ha.yaml"):
                    st.add(key, key, "skip", "config only (same code as the bridge without Home Assistant)")
                else:
                    rc, out, secs = run([es, "compile", f], timeout=3600)
                    size = re.findall(r"(Flash|RAM):.*?(\d+\.\d+%)", out)
                    st.add(key, key, "pass" if rc == 0 else "fail",
                           (", ".join(f"{a} {b}" for a, b in size) + f", {secs:.0f} s") if rc == 0 else tail(out),
                           log("firmware", Path(f).stem + "-compile", out))
        finally:
            if tmpkey and tmpkey.exists():
                tmpkey.unlink()
    if not args.compile:
        for f in ["firmware/gravity980-bridge.yaml", "tests/host-bridge.yaml"]:
            k = f"compiles: {f}"
            st.add(k, k, "skip", "run with --compile")
    base = (ROOT / "firmware/base.yaml").read_text() + (ROOT / "firmware/gravity980-bridge.yaml").read_text()
    for key, pat in [("signed OTA verification on", r"signed_ota_verification:"),
                     ("OTA downgrade protection on", r"enable_ota_downgrade_protection:\s*true"),
                     ("safe mode confirms a new image only after it has run", r"boot_is_good_after:"),
                     ("local only switch defaults off", r"id:\s*local_only[\s\S]{0,400}restore_mode:\s*RESTORE_DEFAULT_OFF"),
                     ("automatic updates switch present", r"id:\s*auto_update"),
                     ("power-cut resume switch present", r"resume_after_power_cut"),
                     ("local only: update checks go nowhere", r"set_source_url\(\"http://127\.0\.0\.1/local-only\"\)"),
                     ("Home Assistant keeps the Clear PIN and Factory reset buttons (convenience, 1.4.2)",
                      r"name: Clear the device page PIN\s+icon:[\s\S]*name: Factory reset\s+icon:"),
                     ("no firmware upload over the network (web_server ota off, no esphome OTA port)",
                      r"ota: false"),
                     ("Bluetooth Wi-Fi setup needs the BOOT button", r"improv_ble:\s*\n(\s*#.*\n)*\s*authorizer: boot_button")]:
        ok = re.search(pat, base) is not None
        st.add(key, f"firmware config: {key}", "pass" if ok else "fail", "" if ok else f"pattern {pat!r} not found")


# The simulated grill runs side by side: the end-to-end test and each scenario group on a copy of the test build with
# its own ports (tests/host-bridge.yaml substitutions), so none waits for another. The device page test uses the plain
# build's ports and runs at the same time (main()).
SIM_PARTS = [  # (name, script, group, test name, api port, grill port, control port)
    ("e2e", "tests/e2e.py", None, "smoker-host-test-e", 6453, 13733, 13734),
    ("scenarios-A", "tests/e2e_scenarios.py", "A", "smoker-host-test-a", 6153, 13433, 13434),
    ("scenarios-B", "tests/e2e_scenarios.py", "B", "smoker-host-test-b", 6253, 13533, 13534),
    ("scenarios-C", "tests/e2e_scenarios.py", "C", "smoker-host-test-c", 6353, 13633, 13634),
]


def compile_host_variant(args, test_name=None, api=None, grill=None):
    """The test build (or a copy with its own name and ports); cached after the first time."""
    cmd = [esphome_bin(args)]
    if test_name:
        cmd += ["-s", "test_name", test_name, "-s", "api_port", str(api), "-s", "grill_port", str(grill)]
    rc, out, _ = run(cmd + ["compile", "tests/host-bridge.yaml"], timeout=1800)
    if rc != 0:
        raise RuntimeError(f"test build {test_name or 'smoker-host-test'} didn't compile: {tail(out)}")


def stage_sim(st, args):
    from concurrent.futures import ThreadPoolExecutor
    py = args.esphome_python or sys.executable
    if not FROM_LOGS:
        for _, _, _, tn, api, grill, _ in SIM_PARTS:
            compile_host_variant(args, tn, api, grill)

    def one(part):
        name, script, group, tn, api, grill, ctrl = part
        env = {"SMOKER_TEST_NAME": tn, "SMOKER_API_PORT": str(api), "SMOKER_GRILL_PORT": str(grill),
               "SMOKER_CTRL_PORT": str(ctrl)}
        if group:
            env["SCENARIO_GROUP"] = group
        return part, run_logged("sim", name, [py, script], env=env, timeout=5400)

    with ThreadPoolExecutor(len(SIM_PARTS)) as ex:
        results = list(ex.map(one, SIM_PARTS))
    # The scenario groups' results under one "scenarios" name (their IDs don't depend on how they were run).
    for label, parts in (("e2e", [r for r in results if r[0][0] == "e2e"]),
                         ("scenarios", [r for r in results if r[0][0].startswith("scenarios")])):
        for (name, script, *_), (rc, out, secs, ev) in parts:
            got = parse_ok_fail(out)
            for key, check, ok, raw in got:
                k = f"{label} › {key}"
                if k in st.ids.seen:  # (each group's own "connected" check)
                    k = f"{label} › {name[-1]} › {key}"
                st.add(k, f"{label}: {check}", "pass" if ok else "fail", "" if ok else raw, ev)
            if rc != 0 and not any(not ok for *_, ok, _ in got):
                st.run_failed(f"{script} ({name}) exited {rc}: {tail(out)}", ev)
            st.env[f"{name}_seconds"] = round(secs)
    st.missing_as_skip()


def stage_device(st, args):
    env = {"ESPHOME_PYTHON": args.esphome_python} if args.esphome_python else {}
    if not FROM_LOGS and not Path(ROOT / "tests/.esphome/build/smoker-host-test/.pioenvs/smoker-host-test/program").exists():
        compile_host_variant(args)
    rc, out, secs, ev = run_logged("device", "webui", ["python3", "tests/webui_e2e.py"], env=env, timeout=3600)
    st.lines(out, ev, rc, "tests/webui_e2e.py")
    st.env["seconds"] = round(secs)
    st.missing_as_skip()


# The render test reports failures only; each named check passes when no failure message matches it.
PAGE_CHECKS = [
    ("shared blocks match the controller page", r"^the shared blocks"),
    ("no JavaScript errors", r"^JS errors \["),
    ("no horizontal overflow (desktop and phone)", r"^horizontal overflow|^phone editor: overflow"),
    ("status strip and control row", r"^status strip|^control row|^not-connected strip|^both links at the top"),
    ("pit temperature, grill drawing and photo mode", r"^pit temp missing|^grill drawing|^photo mode|^photo upload|^grill photo card"),
    ("food cards, probe sources and pull-at", r"^probe cards|^food card|^probe sources|^Food 3's source|^unplugged Food|^pull-at|^recommendations|^experimental"),
    ("header: lid, held steady, program state", r"^header:"),
    ("Cook section: what's cooking, when, build the cook", r"^what's cooking|^when:|^build the cook|^the old Pit & program|^food repeated|^section order|^idle order|^coming up"),
    ("program editor (steps, text, presets, errors, Load)", r"^editor:|^program editor|^program card|^typed program text|^phone editor: (?!overflow)"),
    ("keep (hold a food temperature) and Turbo steps in the editor", r"^keep/turbo"),
    ("simple form fills a cook", r"^simple form"),
    ("Plan with AI", r"^AI plan box|^Plan with AI"),
    ("cook plan on the chart and card", r"^cook plan"),
    ("this cook vs your best", r"^this cook vs your best"),
    ("serve together scheduler", r"^serve together"),
    ("cook replay (curves, events, scrubber, play, compare)", r"^replay|^JS errors in the header/Cook"),
    ("cook picture and share image", r"^the cook's picture|^Share image"),
    ("cook summary card", r"^cook summary"),
    ("journal, how was it, sharing", r"^journal entry|^how was it|^sharing|^shim refused the share"),
    ("chart", r"^chart not drawn"),
    ("charcoal stock, bought a bag, fuel refill", r"^charcoal|^bought a bag|^fuel refill"),
    ("maintenance card", r"^maintenance card"),
    ("scans (labels, items)", r"^scan inputs|^scanned item"),
    ("section bar and chips", r"^section bar"),
    ("Basic / Advanced mode", r"^basic mode|^advanced mode"),
    ("Setup page (opens, focus, back)", r"^setup page"),
    ("connection card, grill Wi-Fi, signal, diagnostics", r"^connection card|^grill wi-fi|^signal rows|^diagnostics"),
    ("Automatic updates toggle", r"^no Automatic updates"),
    ("restart needs a second tap", r"^restart"),
    ("timer", r"^timer start"),
    ("top card pit target, + and -", r"^top card pit target|^pit \+ did not"),
    ("Turbo button", r"^Turbo didn't"),
    ("power off needs a second tap", r"^power off"),
    ("works without the integration's API or the package", r"^without the integration API|^no-package cards"),
    ("shim allows only smoker entities (no lock, no other switches, no /api/config)", r"^shim allowed|^shim api allowed"),
]


def stage_page(st, args):
    rc, out, secs, ev = run_logged("page", "render", ["python3", "tests/render_page.py", str(OUT / "screens")], timeout=1800)
    fails = [re.sub(r"^(light|dark)/(desktop|phone): ", "", ln[5:].strip()) for ln in out.splitlines() if ln.startswith("FAIL ")]
    raw = [ln[5:].strip() for ln in out.splitlines() if ln.startswith("FAIL ")]
    crashed = rc != 0 and not fails
    used = set()
    for name, pat in PAGE_CHECKS:
        hits = [raw[i] for i, f in enumerate(fails) if re.search(pat, f)]
        used |= {i for i, f in enumerate(fails) if re.search(pat, f)}
        status = "skip" if crashed else ("fail" if hits else "pass")
        st.add(name, f"HA dashboard: {name}", status, "; ".join(hits)[:800] if hits else ("render test crashed" if crashed else ""), ev)
    other = [raw[i] for i in range(len(fails)) if i not in used]
    st.add("other render checks", "HA dashboard: every other render check", "skip" if crashed else ("fail" if other else "pass"),
           "; ".join(other)[:800], ev)
    if crashed:
        st.run_failed(f"render_page.py exited {rc}: {tail(out)}", ev)
    st.env["seconds"] = round(secs)


def stage_integration(st, args):
    py = args.ha_python or sys.executable
    xml = OUT / "integration-junit.xml"
    rc, out, secs = run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/integration", f"--junitxml={xml}"], timeout=1800)
    ev = log("integration", "pytest", out)
    n = 0
    if xml.is_file():
        for tc in ET.parse(xml).getroot().iter("testcase"):
            n += 1
            key = f"{tc.get('classname')}::{tc.get('name')}"
            bad = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            sk = tc.find("skipped")
            status = "fail" if bad is not None else "skip" if sk is not None else "pass"
            detail = (bad.get("message") or "")[:500] if bad is not None else (sk.get("message") or "") if sk is not None else ""
            check = tc.get("name").replace("test_", "", 1).replace("_", " ")
            st.add(key, f"{tc.get('classname').split('.')[-1]}: {check}", status, detail, ev)
    if n == 0 or (rc != 0 and not any(r["status"] == "fail" for r in st.results)):
        st.run_failed(f"pytest exited {rc}: {tail(out)}", ev)
    st.env["seconds"] = round(secs)
    st.missing_as_skip()


def stage_package(st, args):
    py = args.ha_python or sys.executable
    rc, out, _ = run([py, "tests/ha_check.py"], timeout=900)
    ev = log("package", "ha_check", out)
    st.add("ha_check: integration import + page build", "integration imports and the page builds",
           "pass" if "integration import + page build OK" in out else "fail", "" if rc == 0 else tail(out), ev)
    st.add("ha_check: HA config check with the package", "Home Assistant's config check passes with the package",
           "pass" if rc == 0 and "HA config check passed" in out else "fail", "" if rc == 0 else tail(out), ev)
    rc, out, _, ev = run_logged("package", "ha_templates", [py, "tests/ha_templates.py"], timeout=900)
    st.lines(out, ev, rc, "tests/ha_templates.py")
    st.missing_as_skip(prefix="")


def _get(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"Content-Type": "application/json"},
                                 data=b"{}" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def stage_live(st, args):
    """Read-only checks against the owner's Home Assistant (HA_URL). Finds the smoker's entities by their platform
    attributes, never by an id written here. Nothing is switched, pressed or set."""
    base = (args.ha_url or "").rstrip("/")
    version = (ROOT / "VERSION").read_text().strip()
    keys = ["integration installed at this version", "controller firmware at this version", "no update pending",
            "configuration check valid", "controller connected to Home Assistant", "local only is off (the default)",
            "automatic updates state reported", "latest GitHub release is this version"]
    if not base:
        for k in keys:
            st.add(k, k, "skip", "HA_URL not set")
        return
    try:
        states = _get(f"{base}/api/states")
    except Exception as ex:  # noqa: BLE001
        for k in keys:
            st.add(k, k, "skip", f"Home Assistant not reachable: {type(ex).__name__}")
        return
    ups = [s for s in states if s["entity_id"].startswith("update.") and "smoker" in s["entity_id"]]
    integ = [s for s in ups if "gravity" in s["entity_id"] or (s["attributes"].get("title") or "").lower().startswith("smoker")]
    fw = [s for s in ups if "firmware" in s["entity_id"]]
    iv = integ[0]["attributes"].get("installed_version", "") if integ else ""
    st.add(keys[0], keys[0], "pass" if iv.lstrip("v") == version else "fail", f"installed {iv or 'not found'}, repo {version}")
    fv = fw[0]["attributes"].get("installed_version", "") if fw else ""
    st.add(keys[1], keys[1], "pass" if fv.lstrip("v") == version else "fail", f"installed {fv or 'not found'}")
    pend = [s["attributes"].get("friendly_name") for s in ups if s["state"] == "on"]
    st.add(keys[2], keys[2], "fail" if pend else "pass", ", ".join(map(str, pend)))
    try:
        cc = _get(f"{base}/api/config/core/check_config", "POST")
        st.add(keys[3], keys[3], "pass" if cc.get("result") == "valid" else "fail", str(cc.get("errors") or "")[:300])
    except Exception as ex:  # noqa: BLE001
        st.add(keys[3], keys[3], "skip", type(ex).__name__)
    sm = {s["entity_id"]: s for s in states if ".smoker_" in s["entity_id"]}
    conn = [s for e, s in sm.items() if e.startswith("text_sensor.") or e.endswith("_connectivity")]
    avail = [s for s in sm.values() if s["state"] not in ("unavailable", "unknown")]
    st.add(keys[4], keys[4], "pass" if len(avail) > 10 else "fail",
           f"{len(avail)} of {len(sm)} smoker entities available" + (f"; connectivity {conn[0]['state']}" if conn else ""))
    lo = [s for e, s in sm.items() if e.startswith("switch.") and "local_only" in e]
    st.add(keys[5], keys[5], "pass" if lo and lo[0]["state"] == "off" else "fail" if lo else "skip",
           lo[0]["state"] if lo else "switch not found")
    au = [s for e, s in sm.items() if e.startswith("switch.") and "automatic_update" in e]
    st.add(keys[6], keys[6], "pass" if au and au[0]["state"] in ("on", "off") else "skip", au[0]["state"] if au else "switch not found")
    try:
        rel = _get("https://api.github.com/repos/Legal-Copy7045/gravity-controller/releases/latest")
        tag = rel.get("tag_name", "")
        names = [a["name"] for a in rel.get("assets", [])]
        st.add(keys[7], keys[7], "pass" if tag.lstrip("v") == version else "fail", f"{tag}: {', '.join(names)[:300]}")
    except Exception as ex:  # noqa: BLE001
        st.add(keys[7], keys[7], "skip", f"GitHub API not reachable: {type(ex).__name__}")


def _tool(args, name):
    """A tool from PATH, or next to the given Python (a venv), or None."""
    for py in (args.quality_python, args.esphome_python, sys.executable):
        if py and (Path(py).parent / name).exists():
            return str(Path(py).parent / name)
    return shutil.which(name)


def stage_quality(st, args):
    """Code quality and supply chain: Python lint (real errors), a static security scan of the integration and tools,
    a vulnerability audit of every pinned requirements file, the C++ with warnings on, and the pages' JavaScript.
    Judged against docs/security.md: findings are leads, the threat model decides what matters."""
    py_dirs = ["custom_components", "tests", "tools", "regression", ".github/scripts"]
    ruff = _tool(args, "ruff")
    if ruff:
        rc, out, _ = run([ruff, "check", "--select", "E9,F63,F7,F82,F401,F811,F841", "--output-format", "concise", "--no-cache"] + py_dirs)
        n = sum(1 for ln in out.splitlines() if ln.count(":") >= 3)
        st.add("ruff: no Python errors", "ruff: no Python errors (syntax, undefined names, unused imports/variables)",
               "pass" if rc == 0 else "fail", "" if rc == 0 else f"{n} issue(s): {tail(out, 12)}", log("quality", "ruff", out))
    else:
        st.add("ruff: no Python errors", "ruff: no Python errors", "skip", "ruff not installed")
    bandit = _tool(args, "bandit")
    if bandit:
        rc, out, _ = run([bandit, "-r", "custom_components/smoker", "tools", "-f", "json", "-q", "--severity-level", "medium"])
        try:
            res = json.loads(out[out.index("{"):]).get("results", [])
        except ValueError:
            res = None
        if res is None:
            st.add("bandit: no high-severity issues", "bandit: no high-severity issues", "fail", tail(out), log("quality", "bandit", out))
        else:
            fmt = lambda r: f"{r['test_id']} {r['filename']}:{r['line_number']} {r['issue_text']}"  # noqa: E731
            high = [fmt(r) for r in res if r["issue_severity"] == "HIGH"]
            med = [fmt(r) for r in res if r["issue_severity"] == "MEDIUM"]
            ev = log("quality", "bandit", out)
            st.add("bandit: no high-severity issues", "bandit (static security scan): no high-severity issues",
                   "fail" if high else "pass", "; ".join(high[:8]), ev)
            st.add("bandit: medium-severity issues listed", "bandit: medium-severity issues (listed for the review)",
                   "pass", f"{len(med)}: " + "; ".join(med[:8]) if med else "none", ev)
    else:
        st.add("bandit: no high-severity issues", "bandit: no high-severity issues", "skip", "bandit not installed")
    audit = _tool(args, "pip-audit")
    reqs = sorted(str(p.relative_to(ROOT)) for p in list((ROOT / ".github/requirements").glob("*.txt")) + list((ROOT / "tests").glob("requirements*.txt")))
    for r in reqs:
        key = f"dependency audit: {r}"
        if not audit:
            st.add(key, key, "skip", "pip-audit not installed")
            continue
        rc, out, _ = run([audit, "--no-deps", "--disable-pip", "--progress-spinner", "off", "-r", r], timeout=600)
        ev = log("quality", "pip-audit-" + Path(r).stem, out)
        if "No known vulnerabilities found" in out:
            st.add(key, key + ": no known vulnerabilities", "pass", "", ev)
        elif rc != 0 and ("Found" in out and "vulnerabilit" in out):
            st.add(key, key + ": no known vulnerabilities", "fail", tail(out, 12), ev)
        else:
            st.add(key, key + ": no known vulnerabilities", "skip", "couldn't check (offline?): " + tail(out, 3), ev)
    srcs = ["tests/test_core.cpp"] + [str(p.relative_to(ROOT)) for p in (ROOT / "components").glob("*/*.cpp")
                                      if p.parent.name in ("gravity980",) or p.name in ("predictor.cpp", "program.cpp", "fuel.cpp", "history.cpp", "pin_auth.cpp")]
    rc, out, _ = run(["g++", "-std=c++17", "-fsyntax-only", "-Wall", "-Wextra"] + [s for s in srcs if "gravity980" not in s])
    warns = [ln for ln in out.splitlines() if "warning:" in ln]
    st.add("C++ (host-testable code) has no compiler warnings", "C++ (the host-tested controller logic) builds with no warnings (-Wall -Wextra)",
           "pass" if rc == 0 and not warns else "fail", "" if rc == 0 and not warns else f"{len(warns)} warning(s): " + "; ".join(warns[:6]),
           log("quality", "cpp-warnings", out))
    for f in ["firmware/device-ui/ui.js", "custom_components/smoker/frontend/common.js", "custom_components/smoker/frontend/shim.js",
              "custom_components/smoker/frontend/panel.js"]:
        rc, out, _ = run(["node", "--check", f])
        st.add(f"JavaScript parses: {f}", f"JavaScript parses: {f}", "pass" if rc == 0 else "fail", "" if rc == 0 else tail(out))


def stage_walkthrough(st, args):
    """The walkthrough's automated crawl (regression/walkthrough.py): both dashboards, desktop and phone, Basic and
    Advanced and the Setup page; UX checks per view. Its own ports and its own copy of the test build."""
    import walkthrough as wt
    name, api, grill = wt.DEVICE_BUILD
    if not FROM_LOGS:
        compile_host_variant(args, name, api, grill)
    inv, results, problems = wt.crawl(args.esphome_python)
    ev = "regression/out/walkthrough/inventory.json"
    for key, check, ok, detail in results:
        st.add(key, check, "pass" if ok else "fail", "" if ok else detail, ev)
    for pr in problems:
        st.run_failed(pr, ev)
    st.env["views"] = len(inv["views"])
    (OUT / "walkthrough.json").write_text(json.dumps(standard_inventory(inv), indent=1, ensure_ascii=False))
    st.missing_as_skip()


def standard_inventory(inv):
    """The crawl in the standard's shape (role -> desktop|phone -> menu and pages) for standard.py's log and briefs.
    One role: the owner (a locked page is reached only as far as the PIN test goes). The full crawl stays in
    out/walkthrough/inventory.json."""
    out = {"owner": {}}
    for v in inv["views"]:
        w = out["owner"].setdefault(v["width"], {"menu": [], "pages": []})
        where = f"{'controller page' if v['page'] == 'device' else 'Home Assistant dashboard'} ({v['mode']})"
        w["menu"].append({"page": where, "items": [n["label"] for n in v.get("nav", [])]})
        for sc in v.get("screens", []) + (v.get("setup_page") or {}).get("screens", []):
            w["pages"].append({"page": where, "section": sc.get("heading") or sc.get("sect", ""),
                               "screenshot": f"walkthrough/{sc['screenshot']}" if sc.get("screenshot") else "",
                               "buttons": sc.get("buttons", []), "fields": sc.get("fields", [])})
    return out


def stage_manual(st, args):
    """manual.yaml; a result recorded for this version (run.py manual KEY pass|fail, in manual-log.yaml) counts."""
    import yaml
    logp = HERE / "manual-log.yaml"
    done = (yaml.safe_load(logp.read_text()) or {}) if logp.is_file() else {}
    version = (ROOT / "VERSION").read_text().strip()
    for item in yaml.safe_load((HERE / "manual.yaml").read_text()) or []:
        rec = done.get(item["key"]) or {}
        if rec.get("version") == version:
            st.add(item["key"], item["check"], rec.get("result", "manual"), rec.get("note", ""), f"manual-log {rec.get('date', '')}")
        else:
            st.add(item["key"], item["check"], "manual", item.get("steps", ""), item.get("last", ""))


STAGES = {"ci": stage_ci, "quality": stage_quality, "core": stage_core, "firmware": stage_firmware, "sim": stage_sim, "device": stage_device,
          "page": stage_page, "integration": stage_integration, "package": stage_package, "live": stage_live,
          "manual": stage_manual, "walkthrough": stage_walkthrough}


TOOLING = {"brief", "log", "summary", "manual", "schema", "walkthrough-due"}


def main():
    if len(sys.argv) > 1 and sys.argv[1] in TOOLING:  # the standard's shared tooling (regression/standard.py)
        import standard
        for f in OUT.glob("*.json"):  # (results written before the standard's "key" field: add it)
            try:
                data = json.loads(f.read_text())
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("results"), list) and any("key" not in r for r in data["results"]):
                for r in data["results"]:
                    r.setdefault("key", "RUN" if r.get("id", "").endswith("-RUN") else r.get("check", ""))
                f.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        return standard.main(sys.argv[1:])
    if len(sys.argv) > 1 and sys.argv[1] == "report":  # this project's reports (richer than the standard's)
        script = "walkthrough_report.py" if "--walkthrough" in sys.argv[2:] else "report.py"
        return subprocess.run([sys.executable, str(HERE / script)], check=False).returncode
    check = len(sys.argv) > 1 and sys.argv[1] == "check"
    if check:
        sys.argv.pop(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", action="append", choices=ORDER)
    ap.add_argument("--compile", action="store_true", default=True, help="compile the firmware (the default; cached after the first run)")
    ap.add_argument("--no-compile", dest="compile", action="store_false", help="skip the firmware compiles")
    ap.add_argument("--live", action="store_true", help="run the read-only live checks (the default when HA_URL is set)")
    ap.add_argument("--with-walkthrough", action="store_true", help="also run the walkthrough's crawl (its own ports)")
    ap.add_argument("--quality-python", default=os.environ.get("QUALITY_PYTHON"), help="a venv with bandit and pip-audit")
    ap.add_argument("--esphome-python", default=os.environ.get("ESPHOME_PYTHON"))
    ap.add_argument("--ha-python", default=os.environ.get("HA_PYTHON"))
    ap.add_argument("--ha-url", default=os.environ.get("HA_URL"))
    ap.add_argument("--from-logs", action="store_true", help="re-read the last run's suite output (re-parse, no re-run)")
    args = ap.parse_args()
    global FROM_LOGS
    FROM_LOGS = args.from_logs
    if check:  # the quick stages, before a pull request is marked ready
        args.stage = ["ci", "quality", "core"]
    stages = select_stages(args.stage, args.live or bool(args.ha_url), args.with_walkthrough)
    OUT.mkdir(exist_ok=True)
    catalogue = load_catalogue()
    import threading

    def run_stage(name):
        print(f"[{dt.datetime.now():%H:%M:%S}] {name} started", flush=True)
        st = Stage(name, catalogue)
        try:
            STAGES[name](st, args)
        except Exception as ex:  # noqa: BLE001  a broken stage is a result, not a crash
            st.run_failed(f"{type(ex).__name__}: {ex}")
        st.save()
        print(f"{name} done", flush=True)  # (/full-check waits for "walkthrough done")

    def lane(names):
        for n in names:
            if n in stages:
                run_stage(n)

    if not FROM_LOGS:
        kill_sims()  # (stale ones from an earlier run hold the ports)
    # Lanes at once: the quick stages that need no ports; the firmware compile, then the simulated grill (its parts
    # side by side); the device page test (the plain test build's ports); the walkthrough's crawl (its own build and
    # ports). Live checks last.
    t0 = time.time()
    lanes = [["ci", "quality", "core", "page", "integration", "package", "manual"], ["firmware", "sim"], ["device"], ["walkthrough"]]
    if "device" in stages and "firmware" in stages and args.compile:
        lanes = [lanes[0], ["firmware", "sim", "device"], lanes[3]]  # (the device test needs the build the compile replaces)
    threads = [threading.Thread(target=lane, args=(names,)) for names in lanes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lane(["live"])
    print(f"done in {round((time.time() - t0) / 60, 1)} min", flush=True)
    shutil.rmtree(Path(tempfile.gettempdir()) / "smoker-regress", ignore_errors=True)
    failing = []
    for name in stages:
        p = OUT / result_file(name)
        if p.is_file():
            failing += [r["id"] for r in json.loads(p.read_text()).get("results", []) if r["status"] == "fail"]
    if failing:
        print("failing: " + ", ".join(failing[:30]) + (f" (+{len(failing) - 30})" if len(failing) > 30 else ""))
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
