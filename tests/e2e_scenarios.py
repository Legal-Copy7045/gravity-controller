#!/usr/bin/env python3
"""Failure-scenario tests: native firmware build <-> tools/fake_grill.py (with its control port).

1. Idle grill ignores the program's target: the program keeps running (no false "manual override" pause)
   and retries until the grill accepts it.
2. Grill goes silent while connected: the link is declared lost, then recovers.
3. Manual change of the pit target during a program: the program pauses.
4. Controller restart mid-cook: power-cut recovery resumes the program (and, with "Resume after a power cut" off, it
   comes back paused at the same step, as before).
6. The grill loses power mid-cook and comes back off with its targets reset: the controller turns it back on, sends
   the pit target again and the program carries on, with one notification.

    esphome compile tests/host-bridge.yaml && python3 tests/e2e_scenarios.py      (~5 minutes)
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time

from aioesphomeapi import APIClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROGRAM = os.path.join(HERE, ".esphome/build/smoker-host-test/.pioenvs/smoker-host-test/program")
CTRL = 13334
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


def grill(cmd):
    with socket.create_connection(("127.0.0.1", CTRL), timeout=5) as s:
        s.sendall((json.dumps(cmd) + "\n").encode())
        s.recv(64)


class Device:
    def __init__(self, prefdir, log):
        self.prefdir, self.log = prefdir, log
        self.proc = None
        self.cli = None
        self.states, self.names, self.by_id, self.svc = {}, {}, {}, {}

    async def start(self):
        env = dict(os.environ, ESPHOME_PREFDIR=self.prefdir)
        self.proc = subprocess.Popen([PROGRAM], stdout=self.log, stderr=subprocess.STDOUT, env=env)
        self.cli = APIClient("127.0.0.1", 6053, None)
        for _ in range(60):
            try:
                await self.cli.connect(login=True)
                break
            except Exception:
                await asyncio.sleep(0.5)
        ents, svcs = await self.cli.list_entities_services()
        self.names = {e.key: e.object_id for e in ents}
        self.by_id = {e.object_id: e for e in ents}
        self.svc = {s.name: s for s in svcs}
        self.states = {}
        self.cli.subscribe_states(lambda s: self.states.__setitem__(self.names.get(s.key, s.key), s))

    async def stop(self, sig=signal.SIGTERM):
        try:
            await self.cli.disconnect()
        except Exception:
            pass
        self.proc.send_signal(sig)
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def val(self, obj):
        s = self.states.get(obj)
        if s is None or getattr(s, "missing_state", False):
            return None
        return getattr(s, "state", None)

    async def wait(self, pred, timeout, what=""):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if pred():
                return True
            await asyncio.sleep(0.25)
        print(f"  (timed out: {what})", flush=True)
        return False

    async def action(self, name, **data):
        await self.cli.execute_service(self.svc[name], data)


async def main():
    prefdir = tempfile.mkdtemp(prefix="smoker-prefs-")
    glog = open(os.path.join(HERE, "e2e-scen-grill.log"), "w")
    dlog = open(os.path.join(HERE, "e2e-scen-device.log"), "w")
    g = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "tools/fake_grill.py"), "--port", "13333",
                          "--bind", "127.0.0.1", "--control-port", str(CTRL)], stdout=glog, stderr=subprocess.STDOUT)
    await asyncio.sleep(1)
    dev = Device(prefdir, dlog)
    try:
        await dev.start()
        v = dev.val
        check(await dev.wait(lambda: v("grill_connected") is True, 20, "connect"), "connected")

        print("scenario 1: idle grill ignores the program's target")
        grill({"idle": True})
        await dev.action("load_program", program="name: Idle test; pit 260 until after 10h")
        await asyncio.sleep(1)
        await dev.action("start_program")
        await asyncio.sleep(45)
        check(v("program_state") == "Running", f"program still running after 45 s (state {v('program_state')!r})")
        check(v("pit_target_reported") == 225.0, f"grill kept 225 while idle ({v('pit_target_reported')})")
        grill({"idle": False})
        check(await dev.wait(lambda: v("pit_target_reported") == 260.0, 90, "retry accepted"),
              f"retry reached the grill once it accepted writes ({v('pit_target_reported')})")
        check(v("program_state") == "Running", "program still running after the retry")

        print("scenario 2: grill goes silent while connected")
        grill({"silent": True})
        check(await dev.wait(lambda: v("grill_connected") is False, 30, "stale"), "silent link declared lost")
        check(v("pit_temperature") is None or v("pit_temperature") != v("pit_temperature"), "pit shows unknown while lost")
        grill({"silent": False})
        check(await dev.wait(lambda: v("grill_connected") is True, 40, "recover"), "link recovered")

        print("scenario 3: manual pit change during a program pauses it")
        dev.cli.number_command(dev.by_id["pit_target"].key, 300)
        check(await dev.wait(lambda: v("pit_target_reported") == 300.0, 10, "manual 300"), "manual change reached the grill")
        check(await dev.wait(lambda: v("program_state") == "Paused", 75, "paused"),
              f"program paused after the manual change (state {v('program_state')!r})")
        await dev.action("resume_program")
        check(await dev.wait(lambda: v("pit_target_reported") == 260.0, 15, "resume"), "resume re-applied 260")

        print("scenario 6: the grill loses power mid-cook and comes back off")
        check(await dev.wait(lambda: v("cook_active") is True, 120, "cook active"), "cook active before the cut")
        await asyncio.sleep(130)  # past a 2-minute save of the recovery record
        dlog.flush()
        before = len(open(os.path.join(HERE, "e2e-scen-device.log")).read())
        grill({"power_cut": 20, "back_on": False})
        check(await dev.wait(lambda: v("grill_connected") is False, 40, "cut"), "link lost in the cut")
        check(await dev.wait(lambda: v("grill_connected") is True, 90, "back"), "link back after the cut")
        check(await dev.wait(lambda: v("grill_on") is True, 90, "turned on"), "grill turned back on")
        check(await dev.wait(lambda: v("pit_target_reported") == 260.0, 60, "pit 260"),
              f"pit target sent again ({v('pit_target_reported')})")
        check(v("program_state") == "Running", f"program still running (state {v('program_state')!r})")

        def since_cut():
            dlog.flush()
            return open(os.path.join(HERE, "e2e-scen-device.log")).read()[before:]

        await dev.wait(lambda: "cook resumed" in since_cut(), 40, "recovery notice")
        log = since_cut()
        check(log.count("The grill lost power: cook resumed") == 1, "one 'grill lost power: cook resumed' notification")
        check("turned back on" in log, "the notification says the grill was turned back on")
        check("Program paused" not in log, "the rebooted grill's default target didn't pause the program")
        check(await dev.wait(lambda: "target id 0x02" in
                             open(os.path.join(HERE, "e2e-scen-grill.log")).read().split("power back")[-1], 30, "food"),
              "the food target was sent to the grill again")

        print("scenario 6b: the link drops, and meanwhile the grill is turned off at its button: left off")
        dlog.flush()
        before = len(open(os.path.join(HERE, "e2e-scen-device.log")).read())
        grill({"silent": True})
        check(await dev.wait(lambda: v("grill_connected") is False, 40, "lost"), "link lost")
        grill({"on": False})
        await asyncio.sleep(5)
        grill({"silent": False})
        check(await dev.wait(lambda: v("grill_connected") is True, 60, "back"), "link back")
        await asyncio.sleep(40)
        check(v("grill_on") is False, "a grill turned off at its button (settings kept) isn't turned back on")
        dlog.flush()
        log = open(os.path.join(HERE, "e2e-scen-device.log")).read()[before:]
        check("wasn't turned back on" in log, "a notification says it was left off")
        dev.cli.button_command(dev.by_id["turn_the_grill_on"].key)
        dev.cli.button_command(dev.by_id["turn_the_grill_on"].key)
        check(await dev.wait(lambda: v("grill_on") is True, 20, "on"), "grill on again (two presses)")
        check(await dev.wait(lambda: v("pit_target_reported") == 260.0, 90, "pit 260"), "program's target back")

        print("scenario 7: the grill is turned off with its button: not turned back on")
        dev.cli.button_command(dev.by_id["turn_the_grill_off"].key)
        dev.cli.button_command(dev.by_id["turn_the_grill_off"].key)
        check(await dev.wait(lambda: v("grill_on") is False, 20, "off"), "grill off by its button")
        await asyncio.sleep(15)
        grill({"power_cut": 5, "back_on": False})
        check(await dev.wait(lambda: v("grill_connected") is False, 40, "cut"), "link lost")
        check(await dev.wait(lambda: v("grill_connected") is True, 90, "back"), "link back")
        await asyncio.sleep(45)
        check(v("grill_on") is False, "a grill that was turned off stays off")
        dev.cli.button_command(dev.by_id["turn_the_grill_on"].key)
        dev.cli.button_command(dev.by_id["turn_the_grill_on"].key)
        check(await dev.wait(lambda: v("grill_on") is True, 20, "on"), "grill on again (two presses)")
        check(await dev.wait(lambda: v("pit_target_reported") == 260.0, 90, "pit 260"), "program's target back")

        print("scenario 8: the lid opens for a minute: its cost is measured, no fire alert")
        dlog.flush()
        before = len(open(os.path.join(HERE, "e2e-scen-device.log")).read())
        grill({"door": True, "pit_f": 230})
        check(await dev.wait(lambda: v("lid") is True, 15, "lid open"), "lid reported open")
        await asyncio.sleep(60)
        grill({"door": False, "pit_f": 240})
        await asyncio.sleep(60)
        grill({"pit_f": 259})  # back near the 260 target
        check(await dev.wait(lambda: bool(v("last_lid_opening")), 120, "lid cost"),
              f"the lid opening was measured ({v('last_lid_opening')!r})")
        dlog.flush()
        log = open(os.path.join(HERE, "e2e-scen-device.log")).read()[before:]
        check("Fire may be out" not in log and "fire may be dying" not in log.lower(), "no fire alert for a lid opening")

        print("scenario 9: the pit runs away: a critical alert")
        grill({"pit_f": None})
        grill({"pit_f": 420})
        check(await dev.wait(lambda: "Pit temperature running away" in open(os.path.join(HERE, "e2e-scen-device.log")).read(),
                             300, "runaway"), "a 'running away' alert within 5 min")
        grill({"pit_f": 259})  # settled again near the 260 target
        check(await dev.wait(lambda: bool(v("pit_stability")), 900, "stability"),
              f"pit stability reported ({v('pit_stability')!r})")
        grill({"pit_f": None})

        print("scenario 5: food reaches its target, then the probe is pulled: one 'done' alert")
        grill({"food1_f": 205})
        check(await dev.wait(lambda: (v("food_1_phase") or "").startswith("Done"), 150, "done"),
              f"food 1 phase Done ({v('food_1_phase')!r})")
        grill({"food1_f": 75})
        await asyncio.sleep(75)
        dlog.flush()
        n = open(os.path.join(HERE, "e2e-scen-device.log")).read().count("Food 1 is done")
        check(n == 1, f"exactly one 'done' notification ({n})")

        print("scenario 4: controller restart mid-cook: the cook resumes")
        grill({"food1_f": 150})
        if v("program_state") != "Running":
            await dev.action("resume_program")
            check(await dev.wait(lambda: v("program_state") == "Running", 20, "running"), "program running before the restart")
        check(await dev.wait(lambda: v("cook_active") is True, 120, "cook active"), "cook active before the restart")
        await asyncio.sleep(130)  # a recovery record saved
        await dev.stop()
        await asyncio.sleep(5)
        await dev.start()
        check(await dev.wait(lambda: v("program_state") == "Running", 60, "resumed"),
              f"program resumed after the restart (state {v('program_state')!r}, status {v('program_status')!r})")
        check(v("cook_active") is True, "still the same cook")
        dlog.flush()
        check(await dev.wait(lambda: "Power cut: cook resumed" in open(os.path.join(HERE, "e2e-scen-device.log")).read(),
                             60, "notice"), "a 'Power cut: cook resumed' notification")

        print("scenario 4b: restart with \"Resume after a power cut\" off: paused, as before")
        dev.cli.switch_command(dev.by_id["resume_after_a_power_cut"].key, False)
        await asyncio.sleep(3)
        await dev.stop()
        await asyncio.sleep(2)
        await dev.start()
        check(await dev.wait(lambda: v("program_state") == "Paused", 30, "restored"),
              f"program restored paused (state {v('program_state')!r}, status {v('program_status')!r})")
        check("restored" in (v("program_status") or ""), f"status says restored: {v('program_status')!r}")
        await dev.stop()
    finally:
        if dev.proc and dev.proc.poll() is None:
            dev.proc.kill()
        g.terminate()
        glog.close()
        dlog.close()
    log = open(os.path.join(HERE, "e2e-scen-grill.log")).read()
    check("DANGEROUS" not in log, "no dangerous command ids sent")


if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print(f"\n{len(failures)} scenario check(s) FAILED")
        sys.exit(1)
    print("\nscenarios passed")
