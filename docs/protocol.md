# Stock controller protocol (Gravity 980)

Summary of what the bridge implements. Credit: [grzbiet/cg980app](https://github.com/grzbiet/cg980app) (MIT), from
analysis of the official app and live testing. Items marked ⚠ are unverified on a real grill yet (see first-run.md).

## Transports

- **BLE**: advertises `Gravity980-XXXX` (OUI 88:4A:18, Opulinks chip). GATT service `0xAAAA`; write `0xBBB0`
  (write without response), notify `0xBBB1`. The device sends notifications as soon as a client connects; the bridge
  also enables them via the CCCD.
- **Wi-Fi**: TCP port **3333**, no authentication, **one client at a time**. A status frame is streamed on connect and
  about once a second. (Set up by the Char-Griller app; 2.4 GHz only.)

## Status frame (16 bytes on the 980; 20 on newer firmware / Auto Akorn ⚠)

Big-endian uint16, °F.

| Bytes | Field | Notes |
|---|---|---|
| 0–1 | Pit (probe 1) temperature | `1000` = not connected |
| 2–3 | Pit target | `4096` = no target |
| 4 | Alarm | `0x10` silent, `0x00` firing |
| 5 | reserved | always `0` (used to find frame boundaries) |
| 6–7 / 8–9 | Food 1 temperature / target | |
| 10–11 / 12–13 | Food 2 temperature / target | |
| 14 | bit 4 (`0x10`) fan on | |
| 15 | bit 0 door/lid open, bit 4 fan turbo | |
| 16–19 | fan mode / speed (Akorn) | not used on the 980 |

Over BLE the same payload arrives wrapped: `00 19 <len> 00 <payload>`. Wi-Fi info arrives as type `0x07`:
`07 <status> <signal> .. .. <ssid_len> <ssid> <bssid×6> <ip×4> <mask×4> <gw×4>`.

TCP frames have no header; the bridge locks onto the stride (16 or 20) by checking byte 4/5 at successive
boundaries and resyncs on errors (see `components/gravity980/protocol.cpp`, unit-tested).

## Commands

`FF <id> <hi> <lo>` over TCP (BLE: prefixed `00 19 04 00` ⚠ not enabled by default).

| id | Meaning | Range | Status |
|---|---|---|---|
| `0x00` | Pit target | 200–700 °F | works over TCP **only while the grill is cooking** (idle: silently ignored) |
| `0x02` | Food 1 target | 50–350 °F | same |
| `0x03` | Food 2 target | 50–350 °F | same |
| `0x01` timer, `0x04` power | — | — | **never sent**: the simple form crashed the controller's Wi-Fi (panel `0040`, re-provisioning needed) |
| `0x05` silence | — | — | **never sent**: flashes `0000`, acts like stop |
| `0x06` fan speed | — | — | ignored by the 980 |

The bridge confirms every target change against the next status frames and reverts the HA entity (with a log
warning) if the grill didn't take it.
