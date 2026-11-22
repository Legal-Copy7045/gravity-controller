#!/usr/bin/env python3
"""Bluetooth investigation tool for the Gravity 980 stock controller (run on a laptop).

  pip install bleak
  python3 tools/ble_probe.py scan                 # list nearby BLE devices (Gravity980 highlighted)
  python3 tools/ble_probe.py dump  <address>      # connect, list every service/characteristic/descriptor
  python3 tools/ble_probe.py watch <address> [-o log.csv] [--minutes 10]
        # subscribe to every notify/indicate characteristic, decode status frames, log raw hex

It never writes to the grill (no commands are sent), so it is safe to run while
the grill is cooking. macOS shows a UUID instead of a MAC address: use that.
"""

import argparse
import asyncio
import csv
import datetime as dt
import sys

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("pip install bleak")

SERVICE = "0000aaaa-0000-1000-8000-00805f9b34fb"


def decode_status(b: bytes) -> str:
    """Decode a 16/20-byte status payload (or a BLE heartbeat '00 19 len 00 <payload>')."""
    if len(b) >= 4 and b[0] == 0x00 and b[1] == 0x19:
        b = b[4:4 + b[2]]
    if len(b) < 16 or b[4] not in (0x00, 0x10) or b[5] != 0:
        return ""
    be = lambda o: (b[o] << 8) | b[o + 1]  # noqa: E731
    t = lambda v: "--" if v == 1000 else str(v)  # noqa: E731
    s = lambda v: "-" if v == 4096 else str(v)  # noqa: E731
    return (f"pit {t(be(0))}/{s(be(2))}F food1 {t(be(6))}/{s(be(8))}F food2 {t(be(10))}/{s(be(12))}F "
            f"alarm={'ON' if b[4] == 0 else 'off'} fan={'on' if b[14] & 0x10 else 'off'} "
            f"door={'OPEN' if b[15] & 1 else 'closed'} turbo={'on' if b[15] & 0x10 else 'off'}"
            + (f" extra={b[16:].hex(' ')}" if len(b) > 16 else ""))


async def scan(args):
    devs = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
    for addr, (d, adv) in sorted(devs.items(), key=lambda kv: -(kv[1][1].rssi or -999)):
        name = d.name or adv.local_name or ""
        mark = "  <== grill?" if any(k in name for k in ("Gravity", "BLEWIFI", "Akorn")) or SERVICE in adv.service_uuids else ""
        print(f"{addr}  rssi={adv.rssi:4}  {name!r}  services={adv.service_uuids}  mfr={ {k: v.hex() for k, v in adv.manufacturer_data.items()} }{mark}")


async def dump(args):
    async with BleakClient(args.address, timeout=20) as c:
        print(f"connected, MTU {c.mtu_size}")
        for svc in c.services:
            print(f"service {svc.uuid}  {svc.description}")
            for ch in svc.characteristics:
                print(f"  char {ch.uuid} handle={ch.handle} props={','.join(ch.properties)}  {ch.description}")
                if "read" in ch.properties:
                    try:
                        v = await c.read_gatt_char(ch)
                        print(f"     read: {v.hex(' ')}  {v!r}")
                    except Exception as e:  # noqa: BLE001
                        print(f"     read failed: {e}")
                for d in ch.descriptors:
                    print(f"    desc {d.uuid} handle={d.handle}")


async def watch(args):
    out = open(args.output, "a", newline="") if args.output else None
    w = csv.writer(out) if out else None
    async with BleakClient(args.address, timeout=20) as c:
        print(f"connected, MTU {c.mtu_size}; Ctrl+C to stop")

        def handler(ch):
            def cb(_, data: bytearray):
                ts = dt.datetime.now().isoformat(timespec="milliseconds")
                dec = decode_status(bytes(data))
                print(f"{ts} {ch.uuid[4:8]} ({len(data):3}) {data.hex(' ')}  {dec}")
                if w:
                    w.writerow([ts, ch.uuid, data.hex(), dec])
                    out.flush()
            return cb

        n = 0
        for svc in c.services:
            for ch in svc.characteristics:
                if "notify" in ch.properties or "indicate" in ch.properties:
                    await c.start_notify(ch, handler(ch))
                    print(f"subscribed {ch.uuid}")
                    n += 1
        if not n:
            print("no notify characteristics found")
        await asyncio.sleep(args.minutes * 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--seconds", type=float, default=8)
    d = sub.add_parser("dump")
    d.add_argument("address")
    wt = sub.add_parser("watch")
    wt.add_argument("address")
    wt.add_argument("-o", "--output")
    wt.add_argument("--minutes", type=float, default=10)
    args = ap.parse_args()
    asyncio.run({"scan": scan, "dump": dump, "watch": watch}[args.cmd](args))


if __name__ == "__main__":
    main()
