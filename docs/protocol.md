# Stock controller protocol (Gravity 980)

Summary of what the bridge implements. Credit: [grzbiet/cg980app](https://github.com/grzbiet/cg980app) (MIT), from
analysis of the official app and live testing. Items marked ⚠ are unverified on a real grill yet (see first-run.md). Seen something new? Open an issue with the
*Grill data* template.

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
| 14 | bit 4 (`0x10`) on flag | first read as "fan on"; it clears when the grill is turned off and sets when it's turned on. The *Fan* and *Grill on* entities both show it |
| 15 | bit 0 door/lid open, bit 4 fan turbo | |
| 16–19 | fan mode / speed (Akorn) | not used on the 980 |

Over BLE the same payload arrives wrapped: `00 19 <len> 00 <payload>`. Wi-Fi info arrives as type `0x07`:
`07 <status> <signal> .. .. <ssid_len> <ssid> <bssid×6> <ip×4> <mask×4> <gw×4>`.

TCP frames have no header; the bridge locks onto the stride (16 or 20) by checking byte 4/5 at successive
boundaries and resyncs on errors (see `components/gravity980/protocol.cpp`, unit-tested).

## Commands

`FF <id> <hi> <lo>` over TCP; over BLE the same four bytes prefixed with `00 19 04 00` (*Control over Bluetooth*, on
by default, confirmed on a 980).

| id | Meaning | Range | Status |
|---|---|---|---|
| `0x00` | Pit target | 200–700 °F | works (TCP or BLE) **only while the grill is cooking** (idle: silently ignored) |
| `0x02` | Food 1 target | 50–350 °F | same |
| `0x03` | Food 2 target | 50–350 °F | same |
| `0x04` flags | four hex digits: `F` = leave alone, `0`/`1` = set | one flag at a time | **confirmed on a 980** (November 2026), see below |
| `0x05` pairing code | hex digits | — | shows a pairing code on the grill's display (`FF 05 46 55` shows 4655), as the app does when pairing. It does **not** silence the alarm. Not used by the bridge |
| `0x01` timer | — | — | **never sent** |
| `0x06` fan speed | — | — | ignored by the 980 |

### 0x04: Turbo and power

The value of command `0x04` holds four flags, one hex digit each: `F` leaves a flag alone, `0` or `1` sets it. Found
in the Char-Griller app's code (v2.0.8) and confirmed on a 980:

| Bytes | Does | Notes |
|---|---|---|
| `FF 04 FF 1F` | Turbo on | the grill's turbo flag (status byte 15 bit 4) follows within 3 s |
| `FF 04 FF 0F` | Turbo off | |
| `FF 04 0F FF` | Power off | as the app sends |
| `FF 04 1F FF` | Power on | the app never sends it; works while the grill is in standby with its Bluetooth awake |

The bridge sends only one flag at a time, as the app does. A value that sets several flags at once (like `00 00`)
crashed the grill's Wi-Fi side in early tests (panel `0040`, re-provisioning needed), so the `test_command` action
refuses it. Power needs two presses within 10 s, enforced by the controller (*Turn the grill on/off* buttons; *Grill
power* shows what's armed).

**Superseded:** earlier versions of this page said no remote turbo command was known and that `0x04`/`0x05` are never
sent. Before the app's code was read, a search over Bluetooth (23 Nov 2026: `0x06` with eight values, ids
`0x07`-`0x1F` with value 1) found nothing, and the bridge's **Boost** (raise the pit target by 100 °F for up to 15
minutes) was added to stand in for turbo. Boost is still there, in Advanced. The `test_command` action and the
*Command tests* switch remain for research: one command at a time, never the setpoint ids `0x00`/`0x02`/`0x03` (use the
target entities, which check the range), and `0x04` only with a single flag.

### Capturing the app's commands (developer build)

Capture mode is **not in the released firmware**: it's the developer config `firmware/dev-capture.yaml` (CI still
builds it), which you build yourself in the ESPHome dashboard. The controller poses as the grill for the app and records
what it writes, for checking commands like Power and Turbo (now known, above). It is off unless you turn it on (the controller never advertises as a grill otherwise), turns itself off after
10 minutes, and never sends anything it captures to the real grill: its own Bluetooth link to the grill is paused while it runs.

1. Switch the real grill **off**, so the app finds the controller instead.
2. Turn on **Capture the app's commands** (on a controller running the developer build: device page Setup → *Find the
   app's commands*, or the config switch in Home Assistant). It needs the device page's PIN when one is set, like every other switch.
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
