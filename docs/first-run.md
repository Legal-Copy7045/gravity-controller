# First run with the grill

What to do in the first session, in order. Nothing here changes the grill: the bridge only reads unless you change a
target, and it never sends the commands known to upset the stock controller.

## 0. Before going outside

- Flash the board ([install.md](install.md)) and add it to Home Assistant within 15 minutes of plugging it in (or
  [use it without Home Assistant](standalone.md)).
- On the device page (Setup → *This controller*) turn on **Log raw grill data** (useful for the next steps), and open the controller's log: the
  [web installer](https://legal-copy7045.github.io/gravity-controller/)'s **Logs & console** with a laptop on USB, or
  the ESPHome dashboard's *Logs* if you build it yourself (the controller's page doesn't show the log).
- Open the controller's page, `http://gravity980.local` (on a phone, Android especially, use the board's IP instead:
  `.local` names often don't resolve there). It starts in **Basic**; switch to **Advanced** for everything else.

## 1. Power on the grill, check Bluetooth

The bridge looks for a device advertising `Gravity980-…` and connects automatically.

- Logs should show `Found grill 'Gravity980-XXXX'`, `BLE connected`, `BLE subscribed to status notifications`.
- **Grill link** shows `bluetooth` and **Pit temperature** updates about once a second.
- If nothing is found: run `pip install bleak` then `python3 tools/ble_probe.py scan` on a laptop next to the grill
  and note the name and address; set `name_prefix` or `mac_address` under `gravity980: bluetooth:` if it differs
  (ESPHome dashboard build).
- Unrecognised notifications are logged as `Unrecognised BLE notification: …`. Please
  [open an issue](https://github.com/Legal-Copy7045/gravity-controller/issues/new/choose) (template: *Grill data*)
  with those lines: they are what the protocol work needs next.

## 2. Wi-Fi

The stock controller's Wi-Fi is set up with the Char-Griller app (2.4 GHz only). **Turn Bridge enabled off first**
(device page): the grill takes one connection at a time, and the bridge is holding it over Bluetooth. Turn it back
on when the app is done. Find the grill's IP in the device log (`Grill reports Wi-Fi status …, IP …`) or your
router. Then:

```bash
nc <grill-ip> 3333 | xxd
```

should print 16 (or 20) bytes about every second. Close `nc` (the grill accepts one client), set **Grill IP address**
on the device page, and **Grill link** switches to `wifi`.

## 3. Check the numbers

| Check | Expect |
|---|---|
| Pit temperature vs the grill's display | equal (°F) |
| Plug a meat probe in / out | Food 1/2 temperature appears / goes unknown |
| Open the lid | **Lid** = open (and the fan stops) |
| Start a cook on the panel at 225 °F | **Pit target (reported)** = 225 |
| Dashboard → Pit target **+** | grill display changes to 230 within a few seconds |
| Turbo (dashboard or page) | the grill's turbo indicator comes on within a few seconds |
| Raw status frame (a diagnostic entity, disabled by default: enable it in Home Assistant) | changes as values change; if anything looks wrong, [open an issue](https://github.com/Legal-Copy7045/gravity-controller/issues/new/choose) (template: *Grill data*) with a few lines |

If the target change is ignored, the grill is probably idle: it only accepts targets while cooking (start the cook
on its panel). Targets go over Wi-Fi or Bluetooth (see [Control over Bluetooth](#control-over-bluetooth)).

**Turning the grill on or off** from the page or the dashboard takes two taps within 10 s: the first arms it (the
button turns red and says *Tap again*), the second does it. The controller enforces this, so a single press from
Home Assistant or an automation does nothing. Turning on works while the grill is in standby with its Bluetooth
awake.

## 4. Measurements for phase 2 (developers)

Only if you want to help with the replacement controller: see
[design.md §13](design.md#13-first-run-measurements-for-phase-2).

## 5. A first cook

Set **Food 1 protein** and **weight** before the probe goes in, and give the probe a **target** (on the grill's
panel; or, after starting the cook on the panel, **Food 1 target** on the dashboard). Without a target there's no
finish time and the cook isn't saved to the history. Flip **Food 1 wrapped** when you wrap. Everything is
logged; when the probe reaches its target the controller saves the cook to its history and the next cook's estimate
starts from it.

## Control over Bluetooth

The app (dashboards, programs, voice, notification buttons) changes the grill's pit and food targets through the
controller: over Wi-Fi when the grill is on Wi-Fi, otherwise over Bluetooth. **Control over Bluetooth** is on by
default and has been confirmed working on a Gravity 980. Remember the grill only takes new targets while it's cooking
(start the cook on its panel). What's sent: pit and food targets (within the grill's 200–700 °F range), Turbo, and turning the grill on or off
(two presses within 10 s), the same commands as over Wi-Fi; each target write is checked against what the grill
reports back. Turn the switch off
(device page → Configuration) to make the Bluetooth link read-only.

## Set up the grill's Wi-Fi from Home Assistant

The controller can do what the Char-Griller app does over Bluetooth, so you don't need the app (turn its Bluetooth
off, or close it: the grill takes one Bluetooth connection, and the controller holds it). With the grill connected
over Bluetooth, on the controller's device page (Configuration) or the dashboard's Setup → Connection:

- **Grill Wi-Fi: join saved network** — asks the grill to join the network it already knows. Try this first: the
  Char-Griller app sends this every time it connects, and the grill may not join on its own.
- **Grill Wi-Fi: scan** — the grill lists the networks it can see in **Grill Wi-Fi networks** (2.4 GHz only).
- **A new network:** on the controller's own page (`http://gravity980.local` → Setup → *Set up the grill's Wi-Fi*),
  pick the network from the scan or type its name, enter the password and press **Set up**. The password goes to the
  controller only (never to Home Assistant, which would record it) and is cleared as soon as it's sent to the grill.
  The controller only sends it to a grill it already knows: one it has been talking to since before its last
  restart, or for at least 10 minutes (or the address set in `bluetooth: mac_address`). A brand-new grill: leave it
  connected for about 12 minutes first. That stops a look-alike Bluetooth device from collecting your Wi-Fi password.

**Grill Wi-Fi** then shows the result ("On &lt;network&gt;, IP …"), and the controller switches to Wi-Fi by itself
(with *Grill IP address* empty it uses the address the grill reports right after that setup, if it's a private
address on the controller's own network). Bluetooth stays as the fallback.

## The grill's Wi-Fi (UniFi and mesh networks)

You don't need it: Bluetooth carries both readings and control. If you'd like the grill on Wi-Fi anyway (longer
range than Bluetooth, the Char-Griller app away from home), these UniFi settings commonly stop small 2.4 GHz
controllers joining. The easiest fix is a dedicated IoT network for them:

- 2.4 GHz only (no band steering), 20 MHz channel width, channel 1, 6 or 11.
- Security WPA2 (not WPA3, not WPA2/WPA3 transition); PMF *optional* or off.
- Off: *Fast roaming (802.11r)*, *BSS transition*, *Minimum data rate control*, *Multicast enhancement*,
  *Proxy ARP*, *Client device isolation*; and if UniFi's *Optimize network* (or *IoT auto-detect*) is pushing settings,
  set them by hand.
- Give the grill a fixed IP (DHCP reservation), then enter it in **Grill IP address**.

The smoker controller itself is an ESP32 and copes with most of these, but the same IoT network suits it too.

### Still won't join?

Once the controller is connected to the grill over Bluetooth, the **Grill Wi-Fi** entity (device page, Diagnostic)
shows what the grill itself reports, and the bridge picks up the grill's IP automatically when *Grill IP address* is
empty:

| Grill Wi-Fi says | Meaning | Try |
|---|---|---|
| *No network set up* | The Char-Griller app's setup never reached the grill | Turn **Bridge enabled** off (the grill takes one Bluetooth connection), close other phones' Char-Griller apps, stand next to the grill, set it up again, then turn the bridge back on |
| *Trying &lt;network&gt;, no IP yet* | It has the details but can't join or get an address | Check the password (plain letters/numbers), that an AP near the grill broadcasts the network, and UniFi's client/event log for the grill (Wi-Fi address `88:4A:18:…`, usually 2 below its Bluetooth address) for authentication or DHCP failures |
| *On &lt;network&gt;, IP …* | Joined | If *Grill link* still isn't `wifi`, something blocks TCP port 3333 between the controller and the grill (isolation, VLAN firewall) |

The 980's Wi-Fi (an Opulinks module) is known to be temperamental and some owners report it dropping within seconds
while Bluetooth stays up. Bluetooth alone is enough for this project: readings and control both work over it.

