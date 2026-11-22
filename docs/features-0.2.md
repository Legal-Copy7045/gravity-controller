# Fuel gauge, forecast, rest coach, cook journal and voice

## Charcoal fuel gauge (no hopper sensor) · Experimental until learned

Tell it what you see; it estimates the burn in between and learns your grill.

| When | Dashboard (Charcoal card) | Voice |
|---|---|---|
| You light it | **Started at** → ¾ | "the hopper is three quarters full" |
| You look in | **It's at** → ½ | "the hopper is half full" |
| You top up and see the new level | **Topped up to** → ½ | "I topped up the hopper to half full" |
| You know how much you added | **Added** → ¼ | "I added a quarter of a hopper" |
| The cook is over | **Finished with** → ⅛ | — |

The burn rate is modelled from the pit temperature over outdoor temperature and how much the fan runs. Every
stretch with a known start, known additions and an observed level at the end (a check or the finish) re-learns it,
separately for **briquettes** and **lump** (choose under *Charcoal type*). "Topped up to ½" without knowing the level
before can't teach it anything, but the estimate carries on from ½; "Added ¼" keeps the stretch learnable.

You get **Charcoal level / left / hours left / empty at / burn rate**, a "running low" alert under 1.5 h, and a
"won't last" alert when the hopper should run out before the food is done.

## Forecast-aware finish times · Experimental

Every 30 minutes Home Assistant sends the hourly forecast to the controller (`esphome.gravity980_set_forecast`).
Hours that will be colder than now are expected to cost some pit temperature (0.15 °C of pit per °C colder outside),
so an overnight brisket's finish time accounts for the 3 a.m. low.

## Pull temperature and rest coach · Experimental until learned

- Each probe shows **Pull at**: the target minus the carryover the meat is expected to coast up after you pull it
  (learned from your past cooks of that protein and weight; defaults by protein until then). You get a "time to pull"
  alert there.
- When it comes off, flip **Food 1 pulled** (or tap *Pulled it* on the alert, or say "I pulled the brisket"), leaving
  the probe in. The controller measures the carryover peak and how fast it cools, shows **Ready to slice in …**, and
  alerts when it's down to **Slice at** (default 150 °F). The carryover and cooling rate are saved with the cook so the
  next pull recommendation is yours, not a default.

## Cook journal and "what's being cooked"

- Every finished cook appears in the **Cook journal** on the dashboard: protein, weight, total and stall time, pit and
  outdoor temperature, and the packages you scanned. Rate it (1-5 ★) and add notes; **Compare** overlays its
  temperature curve on your last cooks of the same protein.
- **What's cooking**: photograph the barcode / label of one or several packages (on a phone the camera opens).
  Home Assistant's AI reads the cut and the net weight; pick a probe for each item and its protein and weight are set
  on the controller. Store barcodes on weighed meat (starting with 2) only encode the price/weight, so the AI reads the
  printed label text.
- The AI advisor and planner see your recent notes and ratings (e.g. a 2★ "dry" brisket at 275 °F) and the scanned
  packages, and adjust their advice.
- Needs: the Smoker integration (HACS), an AI Task entity that supports attachments (Google Gemini does), and Home
  Assistant's media folder (photos are stored in `media/smoker/` and `.storage/smoker_photos/`).

## Voice (Assist)

| Say | Does |
|---|---|
| "How long until the brisket is done?" / "When will the food be ready?" | Temperature and finish time per probe |
| "How hot is the smoker?" / "What's the pit at?" | Pit temperature and target |
| "Set the smoker to 275 degrees" | Sets the pit target (200-700 °F; pauses a running program) |
| "How much charcoal is left?" | Level, hours left, empty time |
| "The hopper is three quarters full" / "I topped up the hopper to half" / "I added a quarter of a hopper" | Fuel gauge entries |
| "Is the stall over?" | Stall status and expected remaining |
| "I pulled the brisket" | Starts the rest coach for that probe |
| "Start the pork shoulder program" / "Smoke a brisket" | Picks the preset and starts it |

The sentences are automations in `homeassistant/packages/smoker.yaml` (conversation triggers), so they work with
any Assist device or the Companion app.

## Food probes from anywhere

Six food slots, **Food 1-6**. Each reads one thermometer, picked with **Food N probe** (dashboard: *Probe sources*):
the grill's own probes (*Grill probe 1/2*, targets kept in step with the grill), a **Govee H5198** read directly over
Bluetooth by the controller (*H5198 probe 1-4*), or any temperature sensor in Home Assistant (*Home Assistant*:
pick it from the list on the dashboard; slots 3-6 default to the Govee H5198's probes through Home Assistant). Every slot gets predictions, stall detection, the rest
coach and voice, and works in cook programs (`food4 >= 165`). Changing a slot's source mid-cook restarts that slot's
estimate (the learned history is kept). Setup: [install.md §5](install.md).

## What's experimental

Some numbers can't be trusted until the controller has seen your grill, your charcoal and your cooks. Those are
marked **Experimental** on the dashboard (a purple chip), in the alerts and in the entities' "estimate basis" text.
The label goes away on its own once there's enough history:

| Estimate | Experimental until | Where it says so |
|---|---|---|
| Finish time, time remaining, stall length (per food) | 3 similar past cooks (same kind of meat, similar weight and pit) | *Food N estimate basis*, the probe card |
| Pull-at temperature and rest/slice time | 2 measured rests for that kind of meat | *Food N estimate basis*, the probe card, the "time to pull" alert |
| Charcoal level, hours left, empty time, low-fuel alerts | about 3 kg of charcoal burned in stretches you logged (start/level and finish) — roughly one cook | *Charcoal estimate basis*, the charcoal card, the alerts |
| Forecast adjustment | always, for now (the cold-weather effect is a fixed guess, not learned) | "weather-adjusted (experimental)" |
| AI estimate, AI recommendations, AI review | always (a language model's opinion, not measurements) | the AI card and recommendations |
| H5198 direct readings | until they've been compared with the thermometer's display on a real cook (the format matches Home Assistant's decoder and a real unit's broadcasts) | *Probe sources* |

Not experimental: temperatures, targets, pit control, cook programs, done/almost-done/stall/probe/lid/connection
alerts, and the cook journal.

