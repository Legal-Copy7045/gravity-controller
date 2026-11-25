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


# The scenarios in three groups that can run on their own (CI runs them side by side): A 0-7, B 8, 9, 5, 4, 4b,
# C 10-13. SCENARIO_GROUP=A|B|C, or all of them in order (the default).
GROUP = os.environ.get("SCENARIO_GROUP", "all").upper()
# The test build saves the power-cut recovery record every 12 s (test_timing_scale 0.1 in tests/host-bridge.yaml, 2 min
# on a real controller): a wait for "a record saved" needs only a little longer than that.
SAVE_WAIT = 20


def want(g):
    return GROUP in ("ALL", g)


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

        if want("A"):
            print("scenario 0: programs the controller refuses (keep at a pit temperature; Turbo left on)")
            await dev.action("load_program", program="name: Bad keep; keep food1 400")
            check(await dev.wait(lambda: "food temperature" in (v("program_error") or ""), 10, "keep range"),
                  f"keep 400 refused ({v('program_error')!r})")
            await dev.action("load_program", program="name: Bad turbo; pit 300 turbo on until food1 >= 160")
            check(await dev.wait(lambda: "Turbo would stay on" in (v("program_error") or ""), 10, "turbo"),
                  f"Turbo left on at the end refused ({v('program_error')!r})")
            await dev.action("load_program", program="name: Sear; pit 700 turbo on until food1 >= 128; hold 200 turbo off")
            check(await dev.wait(lambda: not (v("program_error") or ""), 10, "ok"), f"a sear that turns Turbo off loads ({v('program_error')!r})")

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
            await asyncio.sleep(SAVE_WAIT)  # past a 2-minute save of the recovery record
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

        if want("B"):
            if GROUP == "B":  # run alone: a program running and a cook underway first
                await dev.action("load_program", program="name: Idle test; pit 260 until after 10h")
                await asyncio.sleep(1)
                await dev.action("start_program")
                grill({"pit_f": 259})
                check(await dev.wait(lambda: v("cook_active") is True, 120, "cook active"), "setup: a cook underway")
                grill({"pit_f": None})
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
                                 900, "runaway"), "a 'running away' alert (after the 10-min quiet window and 5 min confirmation)")
            grill({"pit_f": 259})  # settled again near the 260 target
            check(await dev.wait(lambda: bool(v("pit_stability")), 900, "stability"),
                  f"pit stability reported ({v('pit_stability')!r})")
            grill({"pit_f": None})

            print("scenario 5: food reaches its target, then the probe is pulled: one 'done' alert")
            grill({"food1_f": 205})
            # (Done, or already Resting: on a slow machine the phase can move on between two looks)
            check(await dev.wait(lambda: (v("food_1_phase") or "").startswith(("Done", "Resting"))
                                 or "Food 1 is done" in open(os.path.join(HERE, "e2e-scen-device.log")).read(), 240, "done"),
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
            await asyncio.sleep(SAVE_WAIT)  # a recovery record saved
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

        if want("C"):
            if GROUP == "C":  # run alone: a cook underway, "Resume after a power cut" off (as scenario 4b leaves it)
                await dev.action("load_program", program="name: Idle test; pit 260 until after 10h")
                await asyncio.sleep(1)
                await dev.action("start_program")
                check(await dev.wait(lambda: v("cook_active") is True, 120, "cook active"), "setup: a cook underway")
                dev.cli.switch_command(dev.by_id["resume_after_a_power_cut"].key, False)
                await asyncio.sleep(3)
            print("scenario 10: a sear restored paused after a restart turns its Turbo off; a keep program keeps going")
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_program", program="name: Sear test; pit 300 turbo on until after 5h; hold 225 turbo off")
            await asyncio.sleep(1)
            await dev.action("start_program")
            check(await dev.wait(lambda: v("turbo") is True, 20, "turbo on"), "the sear turned Turbo on")
            await asyncio.sleep(3)
            await dev.stop()
            await asyncio.sleep(2)
            await dev.start()  # (Resume after a power cut is still off: restored paused)
            check(await dev.wait(lambda: v("program_state") == "Paused", 30, "restored"), "sear restored paused")
            check(await dev.wait(lambda: v("turbo") is False, 60, "turbo off"),
                  f"Turbo turned off for the paused sear (it was left on at the grill before 1.4.1; turbo {v('turbo')!r})")
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_program", program="name: Keep test; keep food1 at 140")
            await asyncio.sleep(1)
            await dev.action("start_program")
            check(await dev.wait(lambda: v("program_state") == "Finished", 20, "keeping"), "a keep program runs (finished on its keep step)")
            # With "Resume after a power cut" on, the cook is resumed after a restart, and the keep with it.
            dev.cli.switch_command(dev.by_id["resume_after_a_power_cut"].key, True)
            await asyncio.sleep(SAVE_WAIT)  # (a recovery record saved during the cook)
            await dev.stop()
            await asyncio.sleep(2)
            await dev.start()
            check(await dev.wait(lambda: v("program_state") == "Finished", 30, "still keeping"),
                  f"the keep program is still there after a restart (state {v('program_state')!r}; it was lost before 1.4.1)")
            dlog.flush()
            check(await dev.wait(lambda: "goes on keeping the food" in open(os.path.join(HERE, "e2e-scen-device.log")).read(),
                                 90, "notice"), "a notice says it goes on keeping the food")
            # With it off, the cook isn't resumed: the keep ends too (1.4.3 brought it back to move the pit later).
            dev.cli.switch_command(dev.by_id["resume_after_a_power_cut"].key, False)
            await asyncio.sleep(3)
            await dev.stop()
            await asyncio.sleep(2)
            await dev.start()
            check(await dev.wait(lambda: v("program_state") == "Idle", 60, "keep ended"),
                  f"a cook that isn't resumed ends its keep (state {v('program_state')!r})")

            print("scenario 11: Resume turns a sear's Turbo back on; the AI plan check (links, Turbo-only steps)")
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_program", program="name: Sear 2; pit 300 turbo on until after 5h; hold 225 turbo off")
            await asyncio.sleep(1)
            await dev.action("start_program")
            check(await dev.wait(lambda: v("turbo") is True, 20, "turbo on"), "the sear turned Turbo on")
            await dev.action("pause_program")
            check(await dev.wait(lambda: v("turbo") is False, 20, "turbo off"), "pause turned Turbo off")
            await dev.action("resume_program")
            check(await dev.wait(lambda: v("turbo") is True, 20, "turbo on again"),
                  f"resume turned Turbo back on (before 1.4.3 it stayed off; turbo {v('turbo')!r})")
            await dev.action("stop_program")
            check(await dev.wait(lambda: v("turbo") is False, 20, "turbo off"), "stop turned Turbo off")

            def fit(prog):
                dlog.flush()
                before = open(os.path.join(HERE, "e2e-scen-device.log")).read().count("FIT ok=")
                return before
            async def fit_result(prog):
                n = fit(prog)
                await dev.action("fit_program", program=prog)
                ok = await dev.wait(lambda: open(os.path.join(HERE, "e2e-scen-device.log")).read().count("FIT ok=") > n, 10, "fit")
                dlog.flush()
                lines = [ln for ln in open(os.path.join(HERE, "e2e-scen-device.log")).read().splitlines() if "FIT ok=" in ln]
                return lines[-1] if ok and lines else ""
            r = await fit_result('pit 250 until food1 >= 160 notify "see https://example.test/x"; hold 200')
            check("ok=0" in r and "link" in r, f"an AI plan with a link is refused ({r[-120:]!r})")
            r = await fit_result("pit 225 until food1 >= 115; turbo off until food1 >= 195; hold 200")
            check("ok=1" in r and "pit 225 until food1 >= 195" in r, f"a `turbo off until` step waits at the same pit ({r[-160:]!r})")
            r = await fit_result("pit 225 until food1 >= 115; turbo on until pit >= 300; turbo off until food1 >= 195; hold 200")
            check("ok=1" in r and "pit 225 until food1 >= 195" in r,
                  f"a `turbo off until` step after a sear goes back to the program's own pit ({r[-200:]!r})")
            r = await fit_result("pit 225 until food1 >= 115; turbo on until pit >= 300; turbo off; hold 200")
            check("ok=1" in r and "turbo" not in r.split("note=")[0].lower() and "Turbo left out" in r,
                  f"Turbo taken out of an AI plan leaves a program the controller can read ({r[-160:]!r})")
            # Home Assistant's Plan with AI loads through the same check (its unit, its AI max pit).
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_ai_program", program="name: AI hot; pit 600 until after 5h; hold 225")
            dlog.flush()
            check(await dev.wait(lambda: "AI program adjusted before loading" in open(os.path.join(HERE, "e2e-scen-device.log")).read()
                                 and not (v("program_error") or ""), 10, "ai load"),
                  f"an AI plan from Home Assistant is capped at the AI max pit and loaded ({v('program_error')!r})")
            await dev.action("load_ai_program", program='pit 250 notify "see www.example.test"')
            check(await dev.wait(lambda: "couldn't be loaded" in (v("program_error") or ""), 10, "ai refused"),
                  f"an AI plan from Home Assistant with a link is refused ({v('program_error')!r})")

            print("scenario 12: your Start while power-cut recovery reconnects wins (recovery doesn't put the old step back)")
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_program", program="name: Old; pit 260 until after 1m; pit 270 until after 10h")
            await asyncio.sleep(1)
            await dev.action("start_program")
            dev.cli.switch_command(dev.by_id["resume_after_a_power_cut"].key, True)
            check(await dev.wait(lambda: (v("program_status") or "").startswith("Step 2/2"), 150, "step 2"),
                  f"the old program reached step 2 ({v('program_status')!r})")
            await asyncio.sleep(SAVE_WAIT)  # (a recovery record saved)
            grill({"silent": True})  # the grill's link stays down after the restart: recovery waits for it
            await dev.stop()
            await asyncio.sleep(2)
            await dev.start()
            await asyncio.sleep(5)
            # (The old program came back paused: a new one only loads after Stop, as on the page.)
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_program", program="name: New; pit 240 until after 10h; pit 250 until after 1h")
            await asyncio.sleep(1)
            await dev.action("start_program")
            check(await dev.wait(lambda: (v("program_status") or "").startswith("Step 1/2"), 20, "new program"),
                  f"the new program runs ({v('program_status')!r})")
            grill({"silent": False})
            check(await dev.wait(lambda: v("grill_connected") is True, 60, "link back"), "the grill's link is back")
            await asyncio.sleep(90)  # (recovery has done its targets step by now)
            check((v("program_status") or "").startswith("Step 1/2") and "240" in (v("program_status") or ""),
                  f"recovery left your program alone ({v('program_status')!r}; before 1.4.4 it put the old step back)")

            print("scenario 13: a keep-warm program ends with the cook")
            await dev.action("stop_program")
            await asyncio.sleep(1)
            await dev.action("load_program", program="name: Keep end; keep food1 at 140")
            await asyncio.sleep(1)
            await dev.action("start_program")
            check(await dev.wait(lambda: v("program_state") == "Finished", 20, "keeping"), "the keep program runs")
            grill({"pit_f": 80})  # the fire is out: the pit reads cold
            check(await dev.wait(lambda: v("cook_active") is False, 300, "cook ended"), "the cook session ends")
            check(await dev.wait(lambda: v("program_state") == "Idle", 30, "keep ended"),
                  f"the keep program ended with it ({v('program_state')!r})")
            grill({"pit_f": None})
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
