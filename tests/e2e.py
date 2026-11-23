#!/usr/bin/env python3
"""End-to-end test: native ESPHome build of the bridge <-> tools/fake_grill.py.

Starts the fake grill (accelerated time), starts the host-built firmware, then
talks to the firmware over the ESPHome native API like Home Assistant does:
checks live sensors, sets the pit target through the number entity, loads and
starts a cook program, and verifies the grill received the commands.

    esphome compile tests/host-bridge.yaml
    python3 tests/e2e.py
"""

import asyncio
import os
import subprocess
import sys
import time

from aioesphomeapi import APIClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROGRAM = os.path.join(HERE, ".esphome/build/smoker-host-test/.pioenvs/smoker-host-test/program")

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


async def wait_for(pred, timeout, what):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        await asyncio.sleep(0.25)
    print(f"  (timed out waiting for {what})")
    return False


async def main():
    grill_log = open(os.path.join(HERE, "e2e-grill.log"), "w")
    dev_log = open(os.path.join(HERE, "e2e-device.log"), "w")
    grill = subprocess.Popen(
        [sys.executable, "-u", os.path.join(ROOT, "tools/fake_grill.py"), "--port", "13333", "--bind", "127.0.0.1",
         "--speed", "120"],
        stdout=grill_log, stderr=subprocess.STDOUT)
    await asyncio.sleep(1)
    import tempfile
    env = dict(os.environ, ESPHOME_PREFDIR=tempfile.mkdtemp(prefix="smoker-e2e-prefs-"))  # fresh saved state
    dev = subprocess.Popen([PROGRAM], stdout=dev_log, stderr=subprocess.STDOUT, env=env)
    states = {}
    names = {}
    try:
        cli = APIClient("127.0.0.1", 6053, None)
        for _ in range(40):
            try:
                await cli.connect(login=True)
                break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            check(False, "connect to device API")
            return
        entities, services = await cli.list_entities_services()
        for e in entities:
            names[e.key] = e.object_id
        by_id = {e.object_id: e for e in entities}
        svc = {s.name: s for s in services}
        print(f"  device exposes {len(entities)} entities, {len(services)} actions")

        def on_state(s):
            states[names.get(s.key, s.key)] = s

        cli.subscribe_states(on_state)

        def val(obj):
            s = states.get(obj)
            if s is None or getattr(s, "missing_state", False):
                return None
            return getattr(s, "state", None)

        check(await wait_for(lambda: val("grill_connected") is True, 20, "grill connected"), "bridge connects to grill")
        check(await wait_for(lambda: isinstance(val("pit_temperature"), float) and val("pit_temperature") == val("pit_temperature"), 10, "pit temp"),
              f"pit temperature published ({val('pit_temperature')})")
        check(await wait_for(lambda: isinstance(val("food_1_temperature"), float) and val("food_1_temperature") == val("food_1_temperature"), 15, "food temp"),
              f"food 1 temperature published ({val('food_1_temperature')})")
        check(await wait_for(lambda: val("grill_link_status") == "Connected over Wi-Fi", 5, "link status"),
              f"link status says connected ({val('grill_link_status')!r})")
        check(val("pit_target_reported") == 225.0, f"pit target reported 225 ({val('pit_target_reported')})")

        # Set the pit target through the number entity (as the HA UI would).
        cli.number_command(by_id["pit_target"].key, 250)
        check(await wait_for(lambda: val("pit_target_reported") == 250.0, 10, "target 250"), "pit target set to 250 via API")

        # Protocol research: test commands only while "Command tests" is on, never the dangerous ids, 15 s apart.
        await cli.execute_service(svc["test_command"], {"command_id": 6, "value": 1})
        check(await wait_for(lambda: (val("command_test") or "").startswith("refused FF 06 00 01: command tests are off"), 5, "refused"),
              f"test command refused while tests are off ({val('command_test')!r})")
        cli.switch_command(by_id["command_tests"].key, True)
        check(await wait_for(lambda: val("command_tests") is True, 5, "tests on"), "command tests switch on")
        await cli.execute_service(svc["test_command"], {"command_id": 4, "value": 0})
        check(await wait_for(lambda: "never sent" in (val("command_test") or ""), 5, "0x04 refused"), f"id 0x04 refused ({val('command_test')!r})")
        await cli.execute_service(svc["test_command"], {"command_id": 6, "value": 1})
        check(await wait_for(lambda: val("command_test") == "sent FF 06 00 01", 5, "sent"), f"test command sent ({val('command_test')!r})")
        await cli.execute_service(svc["test_command"], {"command_id": 7, "value": 0})
        check(await wait_for(lambda: "wait 15 s" in (val("command_test") or ""), 5, "rate limit"), f"15 s between test commands ({val('command_test')!r})")
        cli.switch_command(by_id["command_tests"].key, False)
        check(await wait_for(lambda: val("command_tests") is False, 5, "tests off"), "command tests switch off")
        await asyncio.sleep(1)
        with open(os.path.join(HERE, "e2e-grill.log"), encoding="utf-8", errors="replace") as fh:
            check("unknown command id 0x06 value 1" in fh.read(), "the grill received FF 06 00 01")

        # Out-of-range is refused locally and never reaches the grill.
        cli.number_command(by_id["pit_target"].key, 100)
        await asyncio.sleep(3)
        check(val("pit_target_reported") == 250.0, "out-of-range target refused")

        # Program: syntax error is reported.
        await cli.execute_service(svc["load_program"], {"program": "pit 250 until food9 >= 160"})
        check(await wait_for(lambda: "food9" in (val("program_error") or ""), 5, "program error"),
              f"program error reported: {val('program_error')!r}")
        # Valid program: step 1 sets pit 260, advances when food1 >= 100 F (quick with the fast sim).
        await cli.execute_service(svc["load_program"], {"program": "name: Test; pit 260 until food1 >= 110; pit 275 until food1 >= 203; hold 200 notify \"done\""})
        check(await wait_for(lambda: (val("program_error") or "") == "" and "Ready" in (val("program_status") or ""), 5, "program loaded"),
              f"program loaded ({val('program_status')!r}, error {val('program_error')!r})")
        # A program outside the grill's 200-700 F range is refused.
        await cli.execute_service(svc["load_program"], {"program": "pit 250 until after 1h; hold 160"})
        check(await wait_for(lambda: "outside the grill" in (val("program_error") or ""), 5, "range error"),
              f"hold below 200 F refused: {val('program_error')!r}")
        await cli.execute_service(svc["load_program"], {"program": "name: Test; pit 260 until food1 >= 110; pit 275 until food1 >= 203; hold 200 notify \"done\""})
        await asyncio.sleep(1)
        await cli.execute_service(svc["start_program"], {})
        check(await wait_for(lambda: val("pit_target_reported") == 260.0, 10, "program pit 260"), "program step 1 set pit to 260")
        check(await wait_for(lambda: val("pit_target_reported") == 275.0, 90, "program pit 275"),
              f"program advanced to step 2 when food1 >= 110 (food1 {val('food_1_temperature')})")
        print(f"  status: {val('program_status')}")
        check("Step 2/3" in (val("program_status") or ""), "program status shows step 2/3")

        # Predictor produces an estimate once it has data (accelerated sim: ~2 sim-min per s).
        ok = await wait_for(lambda: isinstance(val("food_1_estimated_total"), float) and val("food_1_estimated_total") == val("food_1_estimated_total"), 70, "estimate")
        check(ok, f"estimated total published ({val('food_1_estimated_total')} min), phase {val('food_1_phase')!r}")

        # Fuel gauge: started 3/4 full, later topped back up to 1/2.
        await cli.execute_service(svc["fuel_level"], {"percent": 75.0})
        check(await wait_for(lambda: val("charcoal_level") == 75.0, 5, "fuel 75"), f"charcoal level 75 % ({val('charcoal_level')})")
        await cli.execute_service(svc["fuel_refilled"], {"percent": 50.0})
        check(await wait_for(lambda: val("charcoal_level") == 50.0, 5, "fuel 50"), f"topped up to 50 % ({val('charcoal_level')})")
        # Hours left once the pit is hotter than outside (updated every minute).
        check(await wait_for(lambda: isinstance(val("charcoal_hours_left"), float) and val("charcoal_hours_left") > 0, 75, "hours"),
              f"charcoal hours left estimated ({val('charcoal_hours_left')} h, empty at {val('charcoal_empty_at')!r})")
        # A fresh controller has no history: its estimates say they're experimental.
        check((val("food_1_estimate_basis") or "").startswith("Experimental"), f"estimate basis {val('food_1_estimate_basis')!r}")
        check((val("charcoal_estimate_basis") or "").startswith("Experimental"), f"charcoal basis {val('charcoal_estimate_basis')!r}")
        # Forecast is accepted (lists of floats over the API).
        await cli.execute_service(svc["set_forecast"], {"minutes": [0.0, 60.0, 120.0], "temps": [50.0, 45.0, 40.0]})
        await asyncio.sleep(1)
        check(dev.poll() is None, "device still running after a forecast")
        check(val("food_1_pull_at") is not None, f"pull-at recommendation published ({val('food_1_pull_at')})")

        # Probe sources: the slot target follows to the grill probe it reads.
        check(await wait_for(lambda: val("food_1_target") is not None, 5, "slot target"), f"food 1 target ({val('food_1_target')})")
        cli.number_command(by_id["food_1_target"].key, 195)
        check(await wait_for(lambda: val("grill_probe_1_target_reported") == 195.0, 10, "grill target 195"),
              f"slot target synced to the grill probe ({val('grill_probe_1_target_reported')})")
        # Quick changes (the page's +/- buttons) end at the last value, not a bounced-back older one.
        cli.number_command(by_id["food_1_target"].key, 197)
        await asyncio.sleep(0.5)
        cli.number_command(by_id["food_1_target"].key, 199)
        await asyncio.sleep(12)
        check(val("food_1_target") == 199.0 and val("grill_probe_1_target_reported") == 199.0,
              f"quick target changes settle on the last one (slot {val('food_1_target')}, grill {val('grill_probe_1_target_reported')})")
        # A slot with one fixed °C source shows it in the controller's unit (60 °C = 140 °F).
        check(await wait_for(lambda: val("food_2_temperature") == 135.5, 10, "food 2 135.5"),
              f"single-source slot in °C converted ({val('food_2_temperature')})")
        # Switch Food 1 to the other source.
        opts = list(getattr(by_id.get("food_1_probe"), "options", []) or [])
        check(opts == ["Grill probe 1", "Spare"], f"source options {opts}")
        cli.select_command(by_id["food_1_probe"].key, "Spare")
        check(await wait_for(lambda: val("food_1_probe") == "Spare", 10, "select state"), f"source select state ({val('food_1_probe')})")
        check(await wait_for(lambda: val("food_1_temperature") == 135.5, 10, "food 1 from spare"),
              f"food 1 now reads the spare probe ({val('food_1_temperature')})")

        # Grill disappears -> link lost and values unknown.
        grill.terminate()
        grill.wait()
        check(await wait_for(lambda: val("grill_connected") is False, 25, "link lost"), "link loss detected")
        check(await wait_for(lambda: "Trying the grill over Wi-Fi" in (val("grill_link_status") or ""), 10, "status"),
              f"link status says what it's doing ({val('grill_link_status')!r})")
        # The grill comes back: the bridge reconnects by itself.
        grill = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "tools/fake_grill.py"), "--port", "13333", "--bind", "127.0.0.1",
             "--speed", "120"], stdout=grill_log, stderr=subprocess.STDOUT)
        check(await wait_for(lambda: val("grill_connected") is True, 30, "link back"), "link recovers when the grill returns")
        grill.terminate()
        grill.wait()
        await cli.disconnect()
    finally:
        dev.terminate()
        try:
            dev.wait(5)
        except subprocess.TimeoutExpired:
            dev.kill()
        if grill.poll() is None:
            grill.terminate()
        grill_log.close()
        dev_log.close()
    with open(os.path.join(HERE, "e2e-grill.log")) as f:
        g = f.read()
    check("DANGEROUS" not in g, "no dangerous command ids sent to the grill")


if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print(f"\n{len(failures)} e2e check(s) FAILED")
        sys.exit(1)
    print("\ne2e passed")
