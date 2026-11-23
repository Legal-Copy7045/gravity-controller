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

**Turbo** (the panel's fan button) shows as byte 15 bit 4 in the status frame. That was confirmed on a real 980 in
November 2026: four presses, and nothing else in the frame changed. No remote command for it is known yet. The
`test_command` action and the *Command tests* switch exist to look for one, one command at a time (never ids
`0x01`/`0x04`/`0x05`, and never the setpoint ids `0x00`/`0x02`/`0x03`: use the target entities, which check the range).
Tested on 23 Nov 2026 over Bluetooth, with a cook started on the panel (pit target writes were accepted): `0x06`
with values 0, 1, 2, 0x10, 100, 255, 0x0100 and 0x1000, and ids `0x07`-`0x1F` with value 1. None changed turbo, the
fan or any other byte of the status frame, and none upset the grill. The bridge's **Boost** raises the pit target
instead (see the changelog for 0.2.46).

### Capturing the app's commands

To find the bytes the official Char-Griller app sends for **Power** (switch the grill off) and **Turbo**, the
controller can pose as the grill for the app and record what it writes. It is off unless you turn it on (the
controller never advertises as a grill otherwise), turns itself off after 10 minutes, and never sends anything it
captures to the real grill: its own Bluetooth link to the grill is paused while it runs.

1. Switch the real grill **off**, so the app finds the controller instead.
2. Turn on **Capture the app's commands** (device page: Setup → *Find the app's commands*; or the config switch in
   Home Assistant). It needs the device page's PIN when one is set, like every other switch.
3. Open the Char-Griller app and add or connect the grill it finds: **Gravity980-XXXX** (the last 4 hex digits of the
   controller's Bluetooth address). The app sees a grill that is switched on and running: pit 65 °F, target 200 °F,
   fan on (a real frame from a 980 that was on; the bridge's last status instead if its grill was on), sent every 2 s
   as `00 19 10 00` + the 16-byte frame. Target changes from the app show up in it. Anything else, a Power press
   included, leaves it looking on, so you can press it again.
4. Press **Power** a couple of times, a few seconds apart, then **Turbo** the same way.
5. Read the list on the card (newest first: time since the start, the bytes, a guess where the command is known), or
   the *Captured app commands* sensor, or the log (tag `CAPTURE`). Then turn capture off.

What is kept: the last 64 writes and events (connect, disconnect, notifications on/off), each write's characteristic,
length and bytes (only the first 4 of anything over 16 bytes). A Wi-Fi credentials message (type `0x01`) is recorded as
*(Wi-Fi credentials: not recorded)* with its first 2 bytes only: the password is never stored or logged. One phone
at a time. The list is at `GET /local/capture` (behind the PIN when one is set) and *Clear* empties it.

The bridge confirms every target change against the next status frames and reverts the HA entity (with a log
warning) if the grill didn't take it.

## Trust

Nothing here is authenticated: anything in Bluetooth range can advertise as a Gravity 980, and anything on the network
can listen on port 3333. The bridge therefore (`components/gravity980/protocol.h`, unit-tested):

- **Chooses the grill carefully.** With no `bluetooth: mac_address`, the first grill heard is used and is
  **remembered** (in flash) once it has delivered valid status for 2 minutes. Once one is remembered, another device
  takes over only if it advertises as `Gravity980-…` (not `BLEWIFI APP` or just the `0xAAAA` service), the remembered
  one has been silent for 10 minutes (counted from boot if it hasn't been heard since), the link is idle and no grill
  Wi-Fi setup is under way. *Forget grill* clears the remembered address.
- **Sends the Wi-Fi password only to a trusted grill**: the address set in the YAML, or the remembered grill
  (remembered before this boot, or at least 10 minutes ago), which has delivered status on this connection, with a
  Bluetooth signal of at least −75 dBm when known. Otherwise the *Grill Wi-Fi* text says why nothing was sent; when it
  is sent, it names the receiving device (last 3 bytes of its Bluetooth address). A join waiting for its scan is
  cancelled if the Bluetooth link drops.
- **Uses a reported grill IP only when it asked for it.** A `0x07` Wi-Fi info notification sets the Wi-Fi address
  (when *Grill IP address* is empty) only within 30 s of the bridge's own join request or credential send, only for a
  private (RFC 1918) address on the bridge's own subnet, and is forgotten when a different Bluetooth device connects.
- **Cross-checks the two links.** When Wi-Fi and Bluetooth both deliver and disagree (pit more than 15 °F apart, or any
  target different) for 30 s, the Wi-Fi link is dropped with a log warning: a reported IP is then not used again until
  a restart, and a configured *Grill IP address* is retried after 10 minutes.
- **Bounds what it accepts.** Wi-Fi scan results (`0x10`) count only while a scan runs, at most 32 networks, SSIDs of
  at most 32 bytes; the TCP reader takes at most 1 KiB per main-loop pass.
