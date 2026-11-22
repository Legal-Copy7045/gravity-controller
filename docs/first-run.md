# First run with the grill

What to do in the first session, in order. Nothing here changes the grill: the bridge only reads unless you change a
target, and it never sends the commands known to upset the stock controller.

## 0. Before going outside

- Flash the board ([install.md](install.md)) and add it to Home Assistant.
- On the device page turn on **Log raw grill data** (useful for the next steps), and open the device's logs
  (ESPHome dashboard → *Logs*, or `http://gravity980.local` → logs; on a phone use the board's IP instead, `.local` names often don't resolve there).

## 1. Power on the grill, check Bluetooth

The bridge looks for a device advertising `Gravity980-…` and connects automatically.

- Logs should show `Found grill 'Gravity980-XXXX'`, `BLE connected`, `BLE subscribed to status notifications`.
- **Grill link** shows `bluetooth` and **Pit temperature** updates about once a second.
- If nothing is found: run `pip install bleak` then `python3 tools/ble_probe.py scan` on a laptop next to the grill
  and note the name and address; set `name_prefix` or `mac_address` under `gravity980: bluetooth:` if it differs
  (ESPHome dashboard build).
- Unrecognised notifications are logged as `Unrecognised BLE notification: …` — save those lines: they are what
  the protocol work needs next.

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
| Raw status frame | changes as values change; send me a few lines if anything looks wrong |

If the target change is ignored, the grill is probably idle: it only accepts targets while cooking. Over Bluetooth
the bridge doesn't send targets at all yet (`bluetooth: writes: false`); that's the next thing to try once reading
works — note whether the Char-Griller app can change the target over Bluetooth with Wi-Fi off.

## 4. Fan's third wire and other measurements (for phase 2)

With the grill unplugged: see [design.md §9](design.md#9-measurement-session-grill-out). Most useful: pit-probe
resistance, meat-probe resistance at room temperature and in ice water, fan wire count / label / third-wire voltage
while running, lid switch NC or NO.

## 5. A first cook

Set **Food 1 protein** and **weight** before the probe goes in, and give the probe a **target** (on the grill's
panel; or, after starting the cook on the panel, **Food 1 target** on the dashboard). Without a target there's no
finish time and the cook isn't saved to the history. Flip **Food 1 wrapped** when you wrap. Everything is
logged; when the probe reaches its target the controller saves the cook to its history and the next cook's estimate
starts from it.
