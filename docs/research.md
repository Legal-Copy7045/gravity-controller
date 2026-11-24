# Gravity 980 local controller: research notes

Early research, kept for the record. What's built today and what's future: [features.md](features.md).

Goal: local, cloud-free control and monitoring of a **Char-Griller Gravity Fed 980** using an
**ESP32-S3**, integrated with Home Assistant for logging, alarms and stall detection.

> Assumption: "Gravity 980" means the Char-Griller model. Masterbuilt's Gravity series is the
> 560/800/1050/XT, with a different controller (its own ESP32 board).

## 1. What already exists

| Project | What it does | Useful for us |
|---|---|---|
| [mantellian/chargriller-980-controller](https://github.com/mantellian/chargriller-980-controller) (MIT, alpha, docs dated Dec 2024) | Full replacement controller: ESP32-WROOM + ESPHome, drives the stock fan, reads the pit probe, has displays, an encoder and HA entities | Fan driver circuit, door-switch handling and pin plan. Its hand-rolled PID has scaling bugs (see 4.3), and it reads no meat probes |
| [grzbiet/cg980app](https://github.com/grzbiet/cg980app) (MIT, Python, small) | Talks to the **stock** controller: BLE only for Wi-Fi provisioning, then plain TCP on port **3333** | Documented protocol: all 3 probes, setpoints, door and fan-on state, with no hardware changes |

I found nothing for HeaterMeter or other off-the-shelf firmware that targets the 980.

## 2. The stock controller (from cg980app's reverse engineering)

- Radio: Opulinks BLE+Wi-Fi chip (OUI `88:4A:18`), advertised as `Gravity980-XX:XX`.
- BLE GATT service `0xAAAA`. Writes go to `0xBBB0` and notifications come from `0xBBB1`. Used to provision and activate Wi-Fi.
- **TCP `:3333`**: no auth, one client at a time. It streams a status frame about once a second. All values are big-endian uint16 in °F:

| Bytes | Field | Sentinel |
|---|---|---|
| 0-1 / 2-3 | Pit current / pit setpoint | 1000 = probe absent, 4096 = no target |
| 4 | Alarm (`0x10` silent, `0x00` firing) | |
| 6-7 / 8-9 | Meat probe 1 current / target | as above |
| 10-11 / 12-13 | Meat probe 2 current / target | as above |
| 14 | Fan on (bit `0x10`) | |
| 15 | bit0 door open, bit4 fan turbo | |

- Writes use `FF <id> <hi> <lo>`. Id `0x00` sets the pit target (200-700 °F), and `0x02`/`0x03` set the meat probe targets. These work only while the grill is in its "active" power state.
- **Do not send** id `0x01` (timer). The author reports it, and `0x04`/`0x05` sent carelessly, crashed the Wi-Fi side and forced re-provisioning (panel code 0040). Since then `0x04` turned out to be the grill's flags (turbo, power: one flag at a time is safe) and `0x05` shows a pairing code; see [protocol.md](protocol.md).
- The 980 ignores fan-speed writes, so you cannot run your own PID through the stock controller.

## 3. Stock electrical hardware (partly unverified)

| Part | What sources say | Confidence |
|---|---|---|
| PSU | 12 V DC adapter (part 801130, shared with Auto Akorn) | medium |
| Fan | 12 V axial, 3-wire with tach, 1-3 A (part CG900768 / 900738) | medium. The tach wire is unconfirmed |
| Pit probe | **Conflict**: mantellian says K-type thermocouple. Parts sellers say "RTD heat sensor" | **measure it** |
| Meat probes | 2 jacks, probably NTC thermistors (2.5 mm plugs are typical); Beta/R25 unknown | **measure it** |
| Hopper/door switch | Kills the fan when open. Sources disagree on NC vs NO. Known to fail from ash | **measure it** |
| Controller harness | "Controller connector wire" CG801125 | pinout unknown |

## 4. Options

### Option A: Bridge the stock controller (no hardware changes)
The ESP32-S3 runs ESPHome with a small external component that keeps a TCP connection to
`<grill-ip>:3333`. It parses frames and exposes sensors, setpoint `number`s and door/fan/alarm
`binary_sensor`s to HA.
- + No wiring changes. The stock safety and fan logic stay. A solid start for logs and stall alarms.
- − Stock fan algorithm only, plus the stock controller's reported reliability problems. The grill must be on Wi-Fi.
- Alternative: skip the ESP and write an HA custom integration that talks to TCP 3333 directly. Putting it on the ESP keeps the HA side generic.

### Option B: Replace the controller with the ESP32-S3 (full control)
Reuse the stock **fan, pit probe, meat probes, door switch and 12 V PSU**, and replace only the controller board.
- Fan: low-side logic-level MOSFET (e.g. AO3400 / IRLZ44N module) with 25 kHz PWM, a flyback diode, a fuse and tach input (if present) for fan-fail detection, which is simpler than mantellian's INA219.
- Pit probe: MAX31856 (thermocouple) **or** MAX31865 (PT100/PT1000 RTD), depending on what measurement shows.
- Meat probes: NTC in a divider into an **ADS1115** (the ESP32 ADC is too noisy and non-linear for this). Use ESPHome's `ntc` platform with a 3-point calibration (ice water, boiling water, mid-point).
- Control: ESPHome's built-in **`climate: pid`**, with its `autotune` and deadband features, instead of hand-rolled PID. Add a lid-open hold: freeze the integrator and stop the fan.
- Safety: overtemp shutdown, probe-fault failsafe (fan off), and API/Wi-Fi loss keeps cooking locally. A hardware fuse.
- UI: optional small display/encoder later. HA plus the ESPHome web server cover most needs.

### Option C: Hybrid
Run A first, logging stock behaviour and building the HA dashboards and stall logic. Then swap to B.
The HA entity names stay the same, so dashboards and automations carry over.

**Decision:** Option A, the bridge, is what's built today (Wi-Fi + Bluetooth, no wiring). Option B, a controller
of its own that keeps the stock fan, is future work: it needs the probes, fan and lid switch measured first. See
[design.md](design.md) and [features.md](features.md).

## 5. Home Assistant features (either option)
- **Logging:** the recorder plus InfluxDB/Grafana or HA history graphs, with a "cook session" helper to tag runs.
- **Alarms:** pit outside setpoint ±X for N minutes, meat target reached, probe disconnected, lid left open,
  fan fail (Option B), "fire out" (pit falling while the fan is at 100%), and hopper low (inferred).
- **Stall detection:** a `derivative` sensor on each meat probe (°/h over a 15-20 min window).
  The stall is flagged when the meat is between 65 and 80 °C (150-175 °F) and the rate falls below about 2 °C/h for more than 20 minutes.
  It clears when the rate rises above about 5 °C/h. Optionally send a "wrap now?" notification and estimate time-to-done.
- **Notifications:** mobile app actionable notifications (e.g. "raise pit to 135 °C").

## 6. Measurements needed before buying Option B parts
1. Pit probe resistance at room temperature: a few Ω means a thermocouple, ~108 Ω a PT100, ~1.08 kΩ a PT1000.
   Also note the connector type.
2. Meat probe resistance at room temperature and in ice water. This gives the NTC R25/Beta (≈100 kΩ or 50 kΩ is typical). Also note the plug size.
3. Fan: wire count and colours, voltage at full speed, current draw. Check whether the stock controller PWMs the fan.
4. Door switch: continuity with the lid open and closed (NC vs NO).
5. PSU label: voltage and amps. Barrel jack size.
6. For Option A, check whether the grill is on your LAN and port 3333 answers:
   `nc <grill-ip> 3333 | xxd` should print a frame about every second.
7. ESP32-S3 board model: dev kit, PSRAM, USB-C. Most S3 boards are fine. Avoid GPIO 26-32 (flash/PSRAM) and the
   strapping pins 0, 3, 45 and 46.
