# Features: today and in the future

## Today: a bridge to the grill's own controller

The controller is an **ESP32-S3 board and nothing else**. It has no probes, fan driver or wiring of its own: it talks to
the Gravity 980's stock controller over Wi-Fi and/or Bluetooth, like the Char-Griller app does. The grill's
controller still runs the fire (fan, pit temperature, lid switch). Everything the bridge reads comes from the grill,
from a Govee H5198 nearby, or from Home Assistant.

| Area | What it does today |
|---|---|
| Grill link | Reads the grill over Wi-Fi (TCP) or Bluetooth, or both; falls back between them |
| Control | Pit and food targets, Turbo, the timer, power on/off (two taps within 10 s), like the Char-Griller app |
| Temperatures | The pit probe and the two food probes **plugged into the grill's controller**; a Govee H5198 read directly over Bluetooth; any temperature sensor in Home Assistant. Six food slots, each reading one of these |
| Predictions | Finish time per food (warming → stall → finishing) with an early/late range, learned from your past cooks, weather-aware; stall detection and stall remaining |
| Cook programs | Multi-step programs run on the controller (`pit 250 until food1 >= 165 for 30m; ...`), presets, manual override and resume, restore after a restart |
| Alerts | Done/almost done, stall, probe slipped out, pit off target, pit running away (grease fire or air getting in), fire dying or out (told apart from a lid opening), charcoal stuck in the chute, lid open, connection lost, low charcoal; through Home Assistant, ntfy, Pushover or Telegram |
| Power cuts | A cut during a cook (up to an hour): reconnects, turns the grill back on if it was on, sends the targets again and resumes the program, then says what happened |
| Watchdog | Grill link, Wi-Fi, Home Assistant and internet in one status line; recovers stuck links; tells you what was missed while offline |
| Local only | One switch stops every internet connection (weather, AI, sharing, internet notifications, update checks) |
| Pit report | How steadily the pit held its target each cook, and what each lid opening cost in finish time |
| Hold mode | `keep food1 150`: the pit moves to keep a food at a temperature |
| Charcoal | A fuel gauge from what you tell it (levels, top-ups), learning your burn rate |
| Planning | "Ready by" planner, pull-temperature and rest coach, kitchen timer |
| AI (optional) | Plan a cook from a sentence, a second-opinion estimate, recommendations, a review after the cook (Home Assistant's AI task, or Gemini/Claude/OpenAI from the controller) |
| Journal | Every cook saved with ratings, notes, photos read by AI, curve comparison, sharing |
| Pages | The controller's own page (works without Home Assistant or the internet, optional PIN for changes) and the Home Assistant dashboard; Basic and Advanced modes |
| Voice | Assist: "when is the brisket done?", "set the smoker to 275" |
| Updates | Signed over-the-air updates from this project's releases, optionally automatic while idle; a new firmware that crashes or can't stay on the network rolls itself back; web installer for the first flash |

Details: [features-0.2.md](features-0.2.md), [cook-programs.md](cook-programs.md), [standalone.md](standalone.md).

## Future: a controller of its own

These need hardware the project hasn't built yet: a board that replaces the grill's controller (or sits beside it)
and drives the stock fan itself. Nothing below is in the firmware today. The design notes are in
[design.md](design.md); parts lists in [hardware/](../hardware/BOM.md).

| ID | Feature | Needs |
|---|---|---|
| F1 | Pit temperature control (PID) driving the stock fan, with fan kick-start and a minimum speed | Fan driver |
| F2 | Lid-open handling: fan stops, the loop pauses, then a recovery period (avoids the 980's overshoot spikes) | Fan driver, lid switch input |
| F3 | Lighting mode (full fan until lit, then a ramp) and a burn-out/shutdown mode | Fan driver |
| F4 | Hardware safety: fan off while the board boots or crashes, lid interlock, overtemperature and probe-fault cut-offs, fuse | Fan driver, interface board |
| F5 | Fan health: dead, unplugged or seized fan (current sensing) | Current monitor |
| F6 | PID autotune and per-fuel tuning (briquettes vs lump) | F1 |
| F7 | Probes wired to the controller itself: four more food probes (2.5 mm) | Probe inputs (ADC) |
| F8 | Zone probes (left, right, top rack) and control on a chosen zone or an average | Probe inputs (ADC) |
| F9 | A thermocouple in the charcoal chute: fire health, flare-up detection | Thermocouple input |
| F10 | Hopper level: burn-front probes on the hopper wall; a distance sensor last (the hopper runs hot) | Probe inputs, sensor |
| F11 | A display, buttons or a knob, a buzzer or speaker and a status light on the controller | Display, buzzer |
| F12 | A weatherproof enclosure with panel connectors, mounted where the stock controller sits | PCB, enclosure |
| F13 | A motorised damper on the fan intake (tighter control at low temperatures) | Servo, mounting |

What carries over: the cook assistant (predictions, programs, alerts, charcoal, journal, AI) reads ordinary sensors,
so it moves to a future controller unchanged, and so do the Home Assistant entities, the dashboards and the
controller's own page. Today's bridge is also collecting the real cook data the design needs.

Before any of this can start, the grill's probes, fan and lid switch have to be measured: see
[design.md §9](design.md#9-measurement-session-grill-out).
