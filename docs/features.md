# Feature list (for prioritisation)

Each feature has an ID so priorities can be assigned (e.g. Must / Should / Later).
The **Dep** column lists hard dependencies.

## P: Pit control and safety

| ID | Feature | Dep |
|---|---|---|
| P1 | Pit temperature control (PID) driving the stock fan, setpoint from HA, phone, web UI or knob | |
| P2 | Fan kick-start and minimum duty (keeps a 3-wire fan spinning at low speed) | P1 |
| P3 | Lid-open handling: fan stops, PID frozen, recovery period after closing (avoids the 980's overshoot spikes) | P1 |
| P4 | Start-up / ignition mode: full fan until lit, then a setpoint ramp to limit overshoot | P1 |
| P5 | Shutdown / burn-out mode: fan off, alarms quiet, logs closed | P1 |
| P6 | Safety cut-offs: overtemp, pit probe open/short, frozen reading; fan off at boot/crash (hardware); lid interlock (hardware) | |
| P7 | Fan health monitoring (current sense): dead, unplugged or seized fan | P1 |
| P8 | PID autotune, with gains stored on the device and editable in HA | P1 |
| P9 | Selectable control source: pit probe, a zone probe, or the average of several | P1, T3 |

## T: Temperature inputs

| ID | Feature | Dep |
|---|---|---|
| T1 | Stock pit probe | |
| T2 | 4 wired food probes (2.5 mm NTC) | |
| T3 | Up to 4 wired zone/ambient probes (left, right, top rack, etc.) | |
| T4 | Charcoal chute thermocouple (fire health, flare-up detection) | |
| T5 | **External probes as inputs**: wireless probes you already own (via their HA integration, or directly over BLE where supported) usable in alerts and cook programs | ⚠ which probes do you have? |
| T6 | Per-probe calibration, offsets and naming ("Brisket point", "Left grate") | |
| T7 | °C / °F configurable, applied everywhere (device display, web UI, HA, notifications) | |

## C: Cook programs and automation

| ID | Feature | Dep |
|---|---|---|
| C1 | Per-probe targets with alerts (done, approaching, too hot) | T2 |
| C2 | **Cook programs**: ordered steps of *trigger → actions*. Triggers: probe ≥/≤ T, held for N min; elapsed time; clock time; stall started/ended; step entered. Actions: set pit temp, notify, buzzer, hold/keep-warm, shutdown, go to step | P1, T2 |
| C3 | Program library: save, edit and pick programs from the phone (e.g. pork butt, brisket, ribs), with a step-by-step "now on step 3 of 5" view | C2 |
| C4 | Programs run **on the controller**, so they continue if Wi-Fi/HA drops (wired probes only; external probes pause their triggers when unavailable) | C2 |
| C5 | Keep-warm / hold: when the food is done, drop the pit to a hold temp | C2 |
| C6 | Manual override at any time: changing the setpoint pauses the program, with a "resume program" option | C2 |
| C7 | Ad-hoc HA automations/blueprints using controller entities (anything HA can do) | P1 |

Example (your case) as a C2 program:
```
Step 1  pit 250 °F          until  probe "Pork" ≥ 165 °F for 30 min
Step 2  pit 300 °F          until  probe "Pork" ≥ 200 °F
Step 3  pit 160 °F (hold)   notify "Pork done – resting"
```

## A: Analytics and logging

| ID | Feature | Dep |
|---|---|---|
| A1 | Cook session logging (automatic start/stop, history graphs per cook) | |
| A2 | Stall detection per food probe (start, end, duration) | T2 |
| A3 | ETA to target per food probe (suppressed during a stall) | T2 |
| A4 | Fire-out detection (pit falling while the fan is high; chute TC dropping) | P1, (T4) |
| A5 | Fuel-use estimate from fan duty and time → "about X h of charcoal left" (no hopper sensor) | P1 |
| A6 | Hopper burn-front probes on the hopper wall (measured level, no optics) | T3 channels |
| A7 | Hopper ToF level sensor (**back of the list**: heat) | |
| A8 | Cook history export (CSV) and per-cook notes/annotations | A1 |

## U: User interface

| ID | Feature | Dep |
|---|---|---|
| U1 | HA mobile dashboard via the Companion app (Nabu Casa remote access): pit, probes, zones, program status, graphs | |
| U2 | On-device web UI at `smoker.local` (works without HA, LAN only) | |
| U3 | On-device display: current pit temp (plus setpoint/probes if a larger OLED) | |
| U4 | Knob or buttons on the device for the setpoint and alarm silence | U3 |
| U5 | Device buzzer for alarms, with silence from the phone or a button | |

## N: Notifications

| ID | Feature | Dep |
|---|---|---|
| N1 | HA Companion notifications: probe done, stall, out-of-band pit, lid open, program step changes | U1 |
| N2 | Actionable notifications ("+25 °F", "Skip to next step", "Silence") | N1 |
| N3 | ntfy direct from the controller for critical alarms (fire out, overtemp, probe/fan fault, controller lost HA) | |
| N4 | Quiet hours and per-alert enable/disable | N1 |

## H: Hardware and platform

| ID | Feature | Dep |
|---|---|---|
| H1 | Breadboard prototype (fan, pit probe, lid switch) | measurements |
| H2 | Perfboard/PCB, weatherproof enclosure, panel connectors | H1 |
| H3 | OTA firmware updates and a Wi-Fi fallback hotspot | |
| H4 | External antenna if Wi-Fi is weak on the grill | test |
| H5 | Motorised damper on the fan intake (tighter control at low temps) | P1 |

## X: Further ideas (added later)

| ID | Feature | Dep |
|---|---|---|
| X1 | "Ready by" planner: enter a serve time and the cook plan, get a "light the grill by" time and reminders | A3, C2 |
| X2 | Rest timer and carry-over: once off the grill, track the rest with a probe still in, and alert at the rest target | T2 |
| X3 | Probe sanity checks: a probe that suddenly jumps to pit temperature (it slipped out of the meat) or reads implausibly; alert instead of acting on it | T2, C2 |
| X4 | Grease-fire / flare-up detection: fast pit or chute rise with the lid closed and the fan low → critical alert | T4 |
| X5 | Power-loss / reboot recovery: resume the program and setpoint after a brown-out or crash, if the pit is still hot | C2 |
| X6 | Weather compensation: use HA weather (ambient, wind) as a feed-forward term, plus rain alerts during a cook | P1 |
| X7 | Fuel profiles (briquettes vs lump) with separate PID gains and fuel-burn rates | P8, A5 |
| X8 | Maintenance counters: burn hours since the ash bin was emptied, the fan was cleaned or the probes were calibrated | A1 |
| X9 | HA Assist voice queries: "what's the brisket at?", "set the smoker to 275" | U1 |
| X10 | Cook comparison: overlay this cook's curves on a previous one | A1 |
| X11 | Diagnostics: Wi-Fi signal, controller board temperature, uptime, fan current trend | |

## Design notes for C2 (cook programs)
- **Where it runs:** on the ESP32 (custom ESPHome component). It is robust without HA, and HA just shows and edits it.
  The alternative, running programs as HA scripts/automations, is quicker to build and easy to edit, but stops if HA or Wi-Fi drops mid-cook.
- **How programs are edited:** a compact JSON program stored on the device, edited from an HA dashboard card or the device web UI.
  A few presets are built in.
- **External probes (T5):** the ESP subscribes to the HA entity (ESPHome `homeassistant` sensor). If the value goes stale,
  triggers that depend on it pause and you get a notification, instead of acting on old data.
