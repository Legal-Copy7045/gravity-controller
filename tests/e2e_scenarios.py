#!/usr/bin/env python3
"""Failure-scenario tests: native firmware build <-> tools/fake_grill.py (with its control port).

1. Idle grill ignores the program's target: the program keeps running (no false "manual override" pause)
   and retries until the grill accepts it.
2. Grill goes silent while connected: the link is declared lost, then recovers.
3. Manual change of the pit target during a program: the program pauses.
4. Controller restart mid-program: the program comes back paused at the same step.

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

        print("scenario 5: food reaches its target, then the probe is pulled: one 'done' alert")
        grill({"food1_f": 205})
        check(await dev.wait(lambda: (v("food_1_phase") or "").startswith("Done"), 150, "done"),
              f"food 1 phase Done ({v('food_1_phase')!r})")
        grill({"food1_f": 75})
        await asyncio.sleep(75)
        dlog.flush()
        n = open(os.path.join(HERE, "e2e-scen-device.log")).read().count("Food 1 is done")
        check(n == 1, f"exactly one 'done' notification ({n})")

        print("scenario 4: controller restart mid-program")
        await asyncio.sleep(2)
        await dev.stop()
        await asyncio.sleep(2)
        await dev.start()
        check(await dev.wait(lambda: v("program_state") == "Paused", 20, "restored"),
              f"program restored paused after restart (state {v('program_state')!r}, status {v('program_status')!r})")
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
