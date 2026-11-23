#!/usr/bin/env python3
"""Simulated Char-Griller Gravity 980 stock controller (TCP :3333).

Streams 16-byte status frames once a second and accepts the 4-byte setpoint
commands `FF <id> <hi> <lo>`, like the real controller. Useful for testing the
bridge and Home Assistant setup without the grill.

    python3 tools/fake_grill.py                 # real time
    python3 tools/fake_grill.py --speed 60      # 1 s = 1 simulated minute
    python3 tools/fake_grill.py --idle          # ignore writes, like an idle grill
    python3 tools/fake_grill.py --control-port 13334   # tests change behaviour at runtime:
        echo '{"idle": true}' | nc 127.0.0.1 13334     # also "silent" (connected, no frames), "food1_f": 150, "drop": true

The pit follows its setpoint with some lag; food probes warm with a two-node
heat model with an evaporative stall (same model as tests/test_core.cpp).
"""

import argparse
import math
import socket
import struct
import sys
import threading
import time

ABSENT = 1000
NO_TARGET = 4096


class Grill:
    def __init__(self, args):
        self.args = args
        self.pit_f = 70.0
        self.pit_c = (70.0 - 32) * 5 / 9
        self.targets = {0: 225, 2: 203, 3: NO_TARGET}
        self.food = [dict(core=40.0, surf=40.0, moist=1.0, present=True), dict(core=0, surf=0, moist=0, present=False)]
        self.door = False
        self.lock = threading.Lock()
        self.sim_h = 0.0
        self.silent = False
        self.drop = False

    def step(self, dt_h):
        with self.lock:
            sp = self.targets[0] if self.targets[0] != NO_TARGET else 70
            sp_c = (sp - 32) * 5 / 9 + self.args.pit_bias
            # Pit: first-order approach to setpoint (+ steady bias); the displayed value adds a slow wobble.
            self.pit_c += (sp_c - self.pit_c) * min(1.0, dt_h * 2.0)
            self.pit_f = self.pit_c * 9 / 5 + 32 + 3 * math.sin(self.sim_h * 3)
            pit_c = self.pit_c
            for f in self.food:
                if not f["present"]:
                    continue
                e = 0
                if f["moist"] > 0 and f["surf"] > 63:
                    act = min(1, (f["surf"] - 63) / 8)
                    e = 100 * act * math.sqrt(f["moist"])
                    f["moist"] = max(0, f["moist"] - 0.18 * act * dt_h)
                ds = 1.2 * (pit_c - f["surf"]) - e - 0.48 * (f["surf"] - f["core"])
                dc = 0.64 * (f["surf"] - f["core"])
                f["surf"] += ds * dt_h
                f["core"] += dc * dt_h
            self.sim_h += dt_h

    def frame(self):
        with self.lock:
            def c2f(c):
                return int(round(c * 9 / 5 + 32))

            f1 = c2f(self.food[0]["core"]) if self.food[0]["present"] else ABSENT
            f2 = c2f(self.food[1]["core"]) if self.food[1]["present"] else ABSENT
            fan = 0x10 if self.pit_f < self.targets[0] - 2 else 0
            flags = 0x01 if self.door else 0
            return struct.pack(
                ">HHBBHHHHBB",
                int(round(self.pit_f)), self.targets[0], 0x10, 0, f1, self.targets[2], f2, self.targets[3], fan, flags,
            )

    def command(self, data):
        if len(data) != 4 or data[0] != 0xFF:
            print(f"  ignoring unknown command {data.hex(' ')}")
            return
        cid, val = data[1], (data[2] << 8) | data[3]
        if cid in (0x01, 0x04, 0x05):
            print(f"  !!! DANGEROUS command id {cid:#04x} received - the real grill may crash its Wi-Fi")
            return
        if self.args.idle:
            print(f"  idle: dropping command {data.hex(' ')}")
            return
        if cid in self.targets:
            with self.lock:
                self.targets[cid] = val
            print(f"  set target id {cid:#04x} = {val} F")
        else:
            print(f"  unknown command id {cid:#04x} value {val}")


def control(g, port):
    """Line-based JSON control socket for tests."""
    import json

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(4)
    while True:
        c, _ = srv.accept()
        with c:
            data = b""
            while not data.endswith(b"\n"):
                d = c.recv(1024)
                if not d:
                    break
                data += d
            try:
                cmd = json.loads(data.decode() or "{}")
            except ValueError:
                c.sendall(b"bad json\n")
                continue
            with g.lock:
                if "idle" in cmd:
                    g.args.idle = bool(cmd["idle"])
                if "silent" in cmd:
                    g.silent = bool(cmd["silent"])
                if "drop" in cmd:
                    g.drop = True
                if "food1_f" in cmd:
                    g.food[0]["core"] = g.food[0]["surf"] = (float(cmd["food1_f"]) - 32) * 5 / 9
            print(f"  control: {cmd}")
            c.sendall(b"ok\n")


def serve(args):
    g = Grill(args)
    stop = threading.Event()
    if args.control_port:
        threading.Thread(target=control, args=(g, args.control_port), daemon=True).start()

    def sim():
        last = time.monotonic()
        while not stop.is_set():
            now = time.monotonic()
            g.step((now - last) * args.speed / 3600)
            last = now
            time.sleep(0.1)

    threading.Thread(target=sim, daemon=True).start()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.bind, args.port))
    srv.listen(1)
    print(f"Fake Gravity 980 on {args.bind}:{args.port} (speed x{args.speed}{', idle' if args.idle else ''})")
    try:
        while True:
            conn, addr = srv.accept()
            print(f"client {addr} connected")
            conn.settimeout(0.05)
            buf = b""
            next_frame = 0.0
            try:
                while True:
                    now = time.monotonic()
                    if g.drop:
                        g.drop = False
                        break
                    if now >= next_frame and not g.silent:
                        conn.sendall(g.frame())
                        next_frame = now + 1.0
                        if args.verbose:
                            print(f"  t={g.sim_h:5.2f}h pit={g.pit_f:5.1f}F food1={g.food[0]['core']*9/5+32:5.1f}F")
                    try:
                        d = conn.recv(64)
                        if not d:
                            break
                        buf += d
                        while len(buf) >= 4:
                            g.command(buf[:4])
                            buf = buf[4:]
                    except socket.timeout:
                        pass
            except (ConnectionResetError, BrokenPipeError):
                pass
            print("client disconnected")
            conn.close()
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=3333)
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed multiplier")
    ap.add_argument("--idle", action="store_true", help="drop setpoint writes like an idle grill")
    ap.add_argument("--pit-bias", type=float, default=0.0, help="steady pit offset in C (negative = cold day)")
    ap.add_argument("--control-port", type=int, default=0, help="JSON control socket for tests")
    ap.add_argument("-v", "--verbose", action="store_true")
    serve(ap.parse_args())
