# Gravity 980 replacement controller: design plan

Status: **draft, before hardware measurements.** Items marked ⚠ depend on the measurements in
[§9](#9-measurement-session-grill-out).

## 1. Goals

| # | Requirement | How it's met |
|---|---|---|
| G1 | Replace the stock controller completely and keep the stock fan | ESP32-S3 board drives the stock fan directly (§4) |
| G2 | Pit control that works with no Wi-Fi or HA | PID loop runs on the ESP32; HA only changes setpoints |
| G3 | Extra probes for zone temperatures | 4 meat + 4 zone NTC channels, plus 2 thermocouple channels (§5) |
| G4 | Hopper fuel level (low priority) | Fuel-use estimate and burn-front probes first; ToF last (§6) |
| G5 | Logging and stall detection in HA | Native ESPHome API, HA recorder, derivative sensors (§8) |
| G6 | Phone control with a mobile-friendly UI, °C/°F configurable | HA Companion app dashboard as the main UI; on-device web UI as a fallback (§7) |
| G7 | Notifications | HA Companion actionable notifications; ntfy direct from the ESP for critical alarms (§7.3) |
| G9 | Probe-driven cook programs | Multi-step rules, e.g. "meat ≥ 165 °F for 30 min → pit 300 °F" (features.md, C-group) |
| G8 | Safe | Hardware fan-off default, lid interlock, overtemp/probe-fault cut-off, fuse (§4.4) |

## 2. Architecture

```
            ┌──────────────── Grill ────────────────┐
 12 V PSU ──┤  Fan (stock)  Lid/hopper sw  Probes   │
            └──────┬─────────────┬────────────┬─────┘
                   │             │            │
         ┌─────────▼─────────────▼────────────▼─────────┐
         │ ESP32-S3 controller board (ESPHome)          │
         │  • PID pit control, safety, alarms (local)   │
         │  • web_server fallback UI (LAN)              │
         │  • ntfy push for critical alarms (no HA)     │
         └──────────────┬───────────────────────────────┘
                        │ ESPHome native API (Wi-Fi)
         ┌──────────────▼───────────────────────────────┐
         │ Home Assistant                               │
         │  • recorder / history / long-term stats      │
         │  • stall detection, ETA, cook sessions       │
         │  • dashboards  • automations                 │
         └──────────────┬───────────────────────────────┘
                        │ Companion app (LAN, or remote via Nabu Casa / VPN)
                    📱 Phone: dashboard + notifications
```

**Firmware: ESPHome.** It gives native HA integration, OTA updates, the `climate: pid`
component (with autotune), ADS1115/MAX31856/MAX31865/VL53L1X drivers and a web server, all from YAML.
Custom C++ is only needed for the burn-front estimate, if at all.
A hand-written Arduino or ESP-IDF firmware would only make sense for a custom web app on the device.
HA's dashboard does that job better.

## 3. Hardware overview

Part-level shortlist with alternatives and prices: [hardware/BOM.md](../hardware/BOM.md).

| Block | Part (proposed) | Notes |
|---|---|---|
| MCU | Your ESP32-S3 board | Check module (PSRAM? which pins are free?). External antenna preferred: a steel grill body kills Wi-Fi |
| Power | Stock 12 V adapter → MP1584/LM2596 buck to 5 V → board's 3.3 V LDO | ⚠ adapter rating |
| Fan driver | Logic-level MOSFET (AO3400 / IRLZ44N), 1N5819 flyback, 10 kΩ gate pull-down | §4 |
| Fan health | INA226 current/voltage monitor on the 12 V fan feed | Works with any drive method; the tach is unreliable when the supply is chopped |
| Thermocouples | 2 × MAX31856 (SPI) | Pit (if the stock probe is a TC) and the charcoal chute/firebox |
| RTD (alternative) | MAX31865 | Only if the stock pit probe turns out to be a PT100/PT1000 ⚠ |
| NTC probes | 2 × ADS1115 (I²C, 0x48/0x49) = 8 channels | Ratiometric dividers, 0.1 % bias resistors (§5.2) |
| Hopper level | VL53L1X ToF (I²C) behind a heat-resistant window in the hopper lid | §6 |
| Lid/hopper switch | Stock switch → GPIO with RC filter and pull-up | Hardware interlock too (§4.4) |
| Local UI (optional) | 1.3" OLED (SH1106) and a rotary encoder | For when the phone isn't handy; phase 4 |
| Buzzer | 5 V active buzzer through an NPN transistor | |
| Connectors | 2.5 mm mono jacks (NTC probes), mini-K thermocouple jacks, GX12 for the fan/switch harness | ⚠ match the stock plugs where reusing |
| Protection | 3 A blade fuse on 12 V, reverse-polarity MOSFET or diode, TVS on 12 V | |

## 4. Fan control (keeping the stock fan)

### 4.1 Drive method ⚠
The stock fan is reported as a 12 V, 3-wire (tach) brushless fan. There's no PWM input, so speed is set
by modulating its supply. There are three options, picked after measurement:

1. **Low-frequency PWM** (≈ 20–50 Hz, low-side MOSFET). This is HeaterMeter's approach. Simple and robust,
   with slight ticking. It needs a minimum duty (≈ 15–25 %) to keep the motor spinning, plus a
   100 % kick-start pulse.
2. **High-frequency PWM** (25 kHz) with an LC filter. Quieter, and acts as a crude voltage control.
3. **Variable-voltage buck** (DAC/PWM-trimmed regulator). The smoothest and quietest, and the tach stays valid, but it needs more parts.

Plan: prototype with (1). Move to (3) only if noise or minimum-speed behaviour is a problem.

### 4.2 Control loop
- ESPHome `climate: pid` with the pit probe as the sensor. Output goes to the fan, with `min_power`/kick-start handled in a template output.
- **Lid-open logic:** a lid-open event stops the fan and freezes the PID integrator. After the lid closes there's a "recovery" period
  of N minutes with the derivative term ignored, so the loop doesn't overshoot (stock 980 owners report 50–80 °C spikes).
- **Ramp mode:** limit the setpoint slew during start-up to cut overshoot on lighting.
- Autotune via `climate.pid.autotune` on a first empty burn. The gains are stored in flash and adjustable from HA.

### 4.3 The rubber flap / airflow leakage
The 980's fan has a rubber anti-backdraft flap that is a known failure point. A leaky flap means the fire runs hot
even with the fan off, which the PID can't fix. Inspect it tomorrow ⚠. A servo-driven damper could come later.

### 4.4 Safety
- MOSFET gate pull-down: **the fan is off whenever the ESP is resetting, booting or crashed.**
- The lid switch is wired in series with the fan's low side as well as to a GPIO, so the interlock works even if the firmware hangs ⚠
  (matches stock behaviour; check the switch is NC).
- Firmware cut-offs: pit > configurable max (default 370 °C / 700 °F); pit probe open or shorted; pit probe reading
  stuck for > X min while the fan runs. Each sets the fan to 0 % and latches an alarm.
- ESPHome `safe_mode` and a hardware watchdog (on by default).
- Fuse on the 12 V input.

## 5. Temperature probes

### 5.1 Channel plan

| Ch | Sensor | Interface | Purpose |
|---|---|---|---|
| T1 | Stock pit probe ⚠ (TC or RTD) | MAX31856 / MAX31865 | Control input |
| T2 | K-type thermocouple in the charcoal chute | MAX31856 | Fire health ("fire out", flare-up) |
| N1–N4 | Meat probes (NTC, 2.5 mm) | ADS1115 #1 | Food |
| N5–N8 | Ambient/zone probes (NTC air probes on grate clips) | ADS1115 #2 | Left/right/top-rack zones, hopper wall |

The NTC food and air probes use ThermoWorks/Inkbird-compatible 2.5 mm jacks, so cheap off-the-shelf probes work.
Air probes rated to ~370 °C (700 °F) are widely available. The stock 980 meat probes can be reused if their curve
fits ⚠.

### 5.2 NTC measurement
- Ratiometric divider: the probe sits between 3.3 V and the ADS1115 input, with a 0.1 % bias resistor to GND. A spare channel or
  a fixed reference reads the supply, so supply drift cancels.
- Bias value ≈ the probe's resistance in the middle of its working range. 100 kΩ-class probes get ≈ 10 kΩ for meat (40–95 °C) and
  ≈ 1 kΩ for air (100–300 °C). Settle this per probe type after measuring.
- ESPHome `ntc` with a 3-point calibration (ice water, boiling water, and a reference thermometer at ~120 °C).
- An open or shorted channel reports "unplugged" rather than a bogus temperature, and HA hides it.

### 5.3 Zone use in HA
- Show a grill "heat map" card (left/right/top) and the left-vs-right spread.
- Optional: control on the average of the pit probe and a chosen zone probe (a "control at the grate" mode).

## 6. Hopper level (deprioritised: see §11)

The 980 hopper holds ~7 kg (16 lb) of briquettes, with the lid at the top and a hopper switch. There are two complementary methods:

1. **ToF distance (VL53L1X)** mounted on the inside of the hopper lid, looking down.
   - Narrow field of view (configurable ROI) suits a lumpy charcoal surface. Range up to ~4 m, so 60–70 cm is easy.
   - Risks: the sensor is rated to 85 °C, and ash or soot coats the window. Mitigations: a glass or polycarbonate window, a stand-off
     and a short shroud, plus a maintenance wipe. ⚠ Measure the hopper-lid temperature during a cook.
   - Reported as % full (calibrated empty/full distances) and kg remaining. It only reads when the lid is closed.
2. **Burn-front estimate:** 2–3 NTC air probes clipped to the **outside** of the hopper wall at different heights.
   The wall warms as the embers rise. This is robust to dust, and it shows whether charcoal is hanging up (bridging) in the chute.

HA derives the **burn rate** (kg/h) from the level history and fan duty, and from that **time to empty**. It sends a
"refill hopper" notification about 60 minutes before the hopper runs out.

## 7. Phone UI and notifications

### 7.1 Primary: HA Companion app
- A dedicated "Smoker" dashboard: big pit temp and setpoint (thermostat card), meat probe tiles with targets,
  zone temps, hopper gauge, fan %, cook timer, and history graphs. It's mobile-first (sections/tile cards).
- Remote access via Nabu Casa (confirmed).

### 7.2 Fallback: on-device web UI
- ESPHome `web_server` (v3) on the ESP, at `http://smoker.local`. It shows every entity and allows setpoint changes, and works with HA down.
  It's usable on a phone, but basic.
- Optional later: a custom single-page mobile UI served by the ESP, using `web_server` `js_url`/`css_url`, for a polished
  look without HA. **Recommendation:** skip it unless HA access is a problem; the HA dashboard covers this.

### 7.3 Notifications
| Event | Channel | Priority |
|---|---|---|
| Meat probe target reached / within 3 °C | HA → Companion | normal, actionable ("+5 °C", "dismiss") |
| Pit out of band > 10 min | HA → Companion | high |
| Stall started / ended | HA → Companion | normal |
| Hopper low / ETA < 60 min | HA → Companion | high |
| Lid left open > 2 min | HA → Companion | high |
| Fire out (pit falling with fan ≥ 90 % for 10 min) | HA → Companion **and** ESP → ntfy | critical |
| Overtemp / probe fault / fan fault | HA → Companion **and** ESP → ntfy | critical (bypasses Do Not Disturb) |
| Controller offline during an active cook | HA → Companion | high |

The ESP→ntfy path (ESPHome `http_request` to ntfy.sh or a self-hosted ntfy) means the critical alarms
still reach your phone if HA is down. It's optional; decide whether you want it.

## 8. HA side: logging, stall detection, cook sessions
- **Recorder** keeps everything; long-term statistics are on for all temperatures. InfluxDB/Grafana is optional.
- **Cook session:** an `input_boolean.smoker_cook_active` plus input_datetime start, set automatically when the pit passes 80 °C
  with the controller running. It's used to scope alarms and to annotate history.
- **Stall detection** (per meat probe): a `derivative` sensor (°C/h, 20 min window). The stall is flagged when the probe is between 63 and 80 °C, the rate is
  below 2 °C/h for 20 min, and the probe has risen at least 15 °C since the cook started. It clears when the rate goes above 5 °C/h. Duration is tracked.
- **ETA to target:** a linear fit over the last 30 min, suppressed during a stall.
- **Fire health:** pit and chute thermocouple trends against fan duty.

## 9. Measurement session (grill out)
Bring a multimeter, a phone camera, and an IR thermometer if you have one.

1. **Photos** of the stock controller: front, back, the board if it opens, every connector and harness label.
2. **Pit probe:** resistance across its connector at room temperature. A few Ω means a thermocouple, ~108 Ω a PT100, ~1.08 kΩ a PT1000.
   Also note the connector type and the probe's mounting point.
3. **Meat probes:** resistance at room temperature, and in a glass of ice water after 2 min. Plug type and diameter (2.5 or 3.5 mm?).
4. **Fan:** number of wires and colours; the label (V, A, part number). If possible, the DC voltage across the fan with the stock
   controller at low and full fan (low with a pulsing needle means PWM; a steady lower voltage means voltage control).
5. **Fan flap:** does it seal when the fan is off?
6. **Lid/hopper switch(es):** how many, and continuity with the lid open and closed (NC or NO). Do they sit inline with the fan wires?
7. **PSU label:** V, A, barrel jack size and polarity.
8. **Controller mounting:** enclosure dimensions, cable entry points, and how far it is from the firebox.
9. If you light it: IR temperatures of the hopper lid underside, the hopper wall at the top/middle/bottom, and the controller's mounting area.
10. Your **ESP32-S3 board:** exact model or a photo of both sides.

## 10. Build phases

| Phase | Scope | Exit criteria |
|---|---|---|
| 0 | Measurements (§9), finalise the drive method and probe front-ends | Probe types known, fan behaviour characterised |
| 1 | Bench prototype on breadboard: ESP32-S3 + fan driver + pit probe + lid switch; ESPHome PID, safety cut-offs, HA entities, web_server | Holds 110 °C ±5 °C on an empty burn, with no wires outside a temporary enclosure |
| 2 | Meat and zone probes (ADS1115s), calibration; HA dashboard, notifications, stall detection | A real cook, logged end to end, with phone alerts |
| 3 | Hopper level (ToF and burn-front), burn rate and time-to-empty | Refill alert fires within ±20 min of reality |
| 4 | Perfboard or PCB, weatherproof enclosure with panel connectors, optional OLED/encoder | Mounted in place of the stock controller |

## 11. Decisions so far
- **Board:** Lonely Binary ESP32-S3 N16R8 (PCB antenna; GPIO 35–37 reserved for the PSRAM).
- **Remote access:** Nabu Casa → the Companion app works away from home with no extra setup.
- **ntfy:** yes, as a direct ESP→phone path for critical alarms.
- **Local UI:** a "current temp" display is enough; a knob or buttons are a nice-to-have.
- **Units:** °C or °F, user-configurable (device setting, mirrored in HA).
- **Hopper ToF sensor:** moved to the back of the list (the hopper runs too hot); the burn-front and fuel-estimate methods come first.
- **Cook programs:** probe-driven, multi-step cook automation is wanted. See [features.md](features.md) for the feature list awaiting prioritisation.

## 12. Proposed repo layout
```
esphome/smoker.yaml                 # main device config
esphome/packages/*.yaml             # fan, probes, hopper, safety split into packages
homeassistant/packages/smoker.yaml  # helpers, derivative/stall sensors, automations
homeassistant/dashboards/smoker.yaml
hardware/                           # schematic (KiCad), BOM, wiring diagrams, photos
docs/                               # research, design, calibration logs
```
