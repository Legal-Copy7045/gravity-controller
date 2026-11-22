# Changelog

## [0.2.9] - 2026-11-22

- **Cook program step editor** on the dashboard and the controller's own page: each stage is "Set pit to N° until …"
  (probe reaches / drops to, pit reaches, probe done, time in step, clock time, stall start/end; "held for" minutes;
  several conditions = "or"), with a notification per stage; add, remove and reorder stages; presets load into it;
  the program text is still there ("Edit as text").
- **Set up the grill's Wi-Fi over Bluetooth** (what the Char-Griller app does): *Join saved network* (the app sends
  this on every connect; the controller didn't), *Scan*, and a new network and password from the controller's own
  page. The password goes to the controller only (never to Home Assistant) and isn't stored.
- **Control over Bluetooth** is confirmed working on a Gravity 980: no longer marked experimental (the switch is now
  named "Control over Bluetooth"; the old "(experimental)" entity can be deleted in Home Assistant).

## [0.2.8] - 2026-11-22

- The controller's own page shows **your grill photo** too: new *Grill photo URL* setting, filled in automatically by
  the Smoker dashboard when it finds the photo in Home Assistant (`/config/www/smoker/grill.png`). Unreachable or
  empty: the drawing.
- **Fix:** "Running cold/hot" only during a cook (it showed with the grill idle).
- **Fix:** the hopper's "no level" label no longer runs into the ash box; the status strip's explanation sits on its
  own line on phones.

## [0.2.7] - 2026-11-22

- **Restart** button for the controller (device page in Home Assistant, the dashboard's Setup → Controller, and the
  controller's own page; the last two ask for a second tap). Settings and learned cooks are kept.

## [0.2.6] - 2026-11-22

### Firmware
- **The controller's own web page** (`http://gravity980.local`) in the home-dashboards look, replacing ESPHome's stock
  page: a status strip first (connected, controlling, anything wrong), the grill with live readings, food, pit target
  and program, charcoal, and setup (Bluetooth control, bridge, grill IP and Wi-Fi report, probe sources). Built into
  the firmware: works without Home Assistant or the internet. The stock page is at `/?classic`.

### Home Assistant dashboard
- Rebuilt in the home-dashboards layout: a status strip first, the grill (your own photo from
  `/config/www/smoker/grill.png`, or a drawing) with each reading where it is on the grill, a sticky section bar, and
  sections that follow the grill: food, pit & program, charcoal, then chart, plan, journal and setup.
- Food cards lead with temperature, finish, target, pull and rest; the rest folds away (and stays open while it
  updates). A Setup section gathers the connection, probe sources and controller details.

## [0.2.5] - 2026-11-22

- **Grill Wi-Fi** diagnostic entity: what the grill reports about its own Wi-Fi over Bluetooth (network, IP, signal,
  status code), to find out why it won't join.
- With *Grill IP address* empty, the bridge uses the IP the grill reports for the Wi-Fi link.
- Docs: a "still won't join" table in first-run.

## [0.2.4] - 2026-11-22

- **Control over Bluetooth** is on by default: the app controls the grill over Bluetooth when its Wi-Fi isn't
  connected (it often won't join UniFi networks). Still experimental until a cook confirms the grill takes it.
- Dashboard: the pit card shows how the app reaches the grill (Wi-Fi, Bluetooth, or read-only and why), with the
  Bluetooth control switch.
- Docs: UniFi/mesh settings that stop the grill joining Wi-Fi.

## [0.2.3] - 2026-11-22

### Firmware
- **Control over Bluetooth (experimental)** switch (device page, Configuration, off by default): pit and food target
  changes over Bluetooth when the grill's Wi-Fi isn't available. Not yet confirmed on a 980; every write is checked
  against what the grill reports back. See [first run](docs/first-run.md#control-over-bluetooth).

## [0.2.2] - 2026-11-22

### Firmware
- **Fix:** the H5198 reader used the wrong broadcast format (from a community decoder) and would never have read a
  real unit. It now follows Home Assistant's own Govee decoder (govee-ble), checked against a real H5198's
  broadcasts: recognised by its service id, all packet variants, unplugged probes. Each probe's alarm on the
  thermometer is available too (*H5198 probe N alarm*).
- Optional **wired probes**: up to four NTC meat probes on the controller itself through an ADS1115
  (`firmware/wired-probes.yaml`); every slot can pick *Wired probe 1-4*. They work without Home Assistant, like the
  grill's probes and the H5198 read directly.
- Food 3-6 default to the *Home Assistant* source. A thermometer's own alarm (H5198 direct, or the matching Home
  Assistant alarm entity) becomes the slot's target when it's changed there; nothing is written back to it.

### Home Assistant
- Pick each slot's Home Assistant thermometer from a list on the dashboard (*Probe sources*). Slots 3-6 default to
  the Govee H5198's probes 1-4 (`sensor.meat_thermometer_temperature_probe_N`).
- A Govee probe reporting exactly 0 °C (unplugged) counts as no reading; the probe's alarm becomes the slot target.

## [0.2.1] - 2026-11-22

Second review round, and **Experimental** labels on estimates that need history
([what's experimental](docs/features-0.2.md#whats-experimental)).

### Firmware
- **Fix:** the controller no longer reboots after 15 minutes without Home Assistant or Wi-Fi (it kept cooking and
  alerting through ntfy, then restarted and lost the cook's estimates).
- **Fix:** probe targets: quick changes no longer bounce back, a target the idle grill ignored is re-sent, targets set
  on the grill's panel are taken as they are (the slot range is now the grill's), and two slots on the same grill
  probe don't overwrite each other. The charcoal gauge ignores a warm but unlit grill.
- The H5198 reader only picks a device once it has sent real probe readings.
- **Experimental** labels: finish times (until 3 similar cooks), pull-at (until 2 measured rests) and the charcoal
  gauge (until about one logged cook) say so in their estimate basis and alerts until there's enough history; new
  *Charcoal estimate basis* entity.

### Home Assistant
- Dashboard: an **Experimental** chip on estimates without enough history yet, the AI estimate and
  recommendations, and H5198 readings ([what's experimental](docs/features-0.2.md#whats-experimental)).
- Voice finish-time answers say when the estimate is still experimental.
- Package scan photos are kept in `media/smoker_scans`; only the integration's own files there are tidied up.
- Weather entity lines are marked **EDIT** in the package.

### Docs
- ESPHome dashboard snippet includes `govee_h5198` and needs ESPHome 2026.11 or newer; which USB port to use; adding
  the device by hand when it isn't discovered; `.local` names on phones.

## [0.2.0] - 2026-11-22

Five new features ([docs/features-0.2.md](docs/features-0.2.md)) and selectable food probes.

**Upgrading from 0.1.x:** the grill's probes are now *Grill probe 1/2*; Food 1 and Food 2 read them by default, so
nothing changes unless you used the Govee helpers: set those slots (Food 3-6) to *Home Assistant* or use the H5198
directly (below). Cook programs use `food3`…`food6` instead of `govee1`…`govee4`. Learned cook history is kept.

### Firmware
- Six food slots (Food 1-6), each reading a grill probe, a **Govee H5198 read directly over Bluetooth** (new
  `govee_h5198` component, no Home Assistant needed) or any temperature entity in Home Assistant, chosen per slot
  with *Food N probe*. A slot's target stays in step with the grill's own probe target.
- Charcoal fuel gauge: start level, checks, top-ups (to a level, or an amount added) and the end level; burn rate
  learned per fuel type; level, hours left, empty time, low-fuel and "won't last" alerts.
- Forecast-aware predictions: the hourly forecast from Home Assistant adjusts the expected pit temperature ahead.
- Rest coach: recommended pull temperature from learned carryover, "pulled" switch per probe, ready-to-slice time and
  alert; carryover and cooling are saved with each cook.
- **Fix:** pulling the meat at the recommended pull temperature (below the target) records the cook, ends "until
  done" program steps, and no longer writes the rest result into an older cook.
- **Fix:** cook history saved by 0.1.x is converted, not discarded.
- **Fix:** the "pulled" switch always shows whether a rest is running; the "time to pull" alert doesn't repeat after
  a restart; the fuel gauge doesn't learn from stretches that span hours with the grill cold; "running low" and
  "won't last" alerts no longer replace each other; forecast adjustments age with the forecast.
- **Fix:** a slot's target is no longer overwritten by the grill's old probe target at boot or reconnect (the slot's
  target is pushed to the grill instead; changes made on the grill's panel still come through, and are saved).
- **Fix:** grill link drop-outs: the fuel gauge keeps burning at the last rate for 15 minutes and doesn't learn from a
  longer gap; switching a slot's source just after a finish keeps the cook; marking "pulled" twice doesn't
  overwrite the measured rest.
- Food targets, slice-at and pull-at are temperature entities, so Home Assistant shows them in its own unit.

### Home Assistant
- Cook journal (Smoker integration): every finished cook with ratings, notes and curve comparison.
- "What's cooking": photos of package barcodes/labels read by the AI; assign items to probes to set protein and
  weight.
- Voice: ask for finish times, pit temperature, charcoal; set the pit; log the hopper; start presets; mark pulled.
- AI advisor and planner use journal ratings/notes and scanned packages; forecast sent to the controller.
- Dashboard: *Probe sources* picks each slot's thermometer (and the Home Assistant entity); the probe card shows it.
- Helpers *Smoker external probe 1-6 entity* replace the Govee helpers; °C sources are converted.
- **Fix:** voice no longer takes over "the grill is off", asks which probe when it's ambiguous, answers the stall
  question for the food you name, uses the pit's own range (°C too), and understands "half a hopper".
- **Fix:** photo uploads are size-limited while reading; scanned item ids are checked (they ended up in the page);
  bad weights and ratings return a message instead of an error; photo names can't collide; unused scan photos are
  tidied up.
- **Fix:** the finished-cook summary no longer fails for cooks without a stall (poultry, sausage, fish) or without a
  pit average, so the rest timer and the AI review run; package photo thumbnails load; the AI plan isn't refreshed
  every time the controller reconnects; notification buttons use the pit's own range and unit.

## [0.1.1] - 2026-11-22

Fixes from the third test-and-review round.

### Firmware
- **Fix:** a cook is still recorded when the food target is lowered while the food is done.
- **Fix:** pausing a program and then losing a probe reading no longer counts the pause twice.
- **Fix:** 700 °F is reachable as a pit target; settings storage no longer grows memory per save, and detects
  corrupted or old-format data.
- API encryption (Home Assistant sets the key when you add the device); firmware can no longer be uploaded from
  the device's web page; Bluetooth Wi-Fi setup uses `improv_ble`.
- Govee probes come from Home Assistant helpers (no firmware change needed to map them).

### Home Assistant
- Govee probe mapping helpers; every line to edit is marked.
- Dashboard: long programs clear the edit box once loaded.

### Docs
- Use the board's native USB port for the Wi-Fi step; turn **Bridge enabled** off while using the Char-Griller
  app; finding the grill's IP; set a food target for a first cook; start the cook on the grill's panel.

## [0.1.0] - 2026-11-22

First release: the bridge to the stock Gravity 980 controller.

### Firmware
- Connects to the stock controller over Wi-Fi (TCP 3333) and Bluetooth LE (status notifications); uses whichever is
  delivering data. Pit and food-probe temperatures and targets, lid, fan, alarm. Pit and probe targets can be set
  (over Wi-Fi; only while the grill is cooking).
- Only the three setpoint commands are ever sent; the timer/power/silence commands known to crash the stock
  controller's Wi-Fi are not implemented.
- Cook assistant: learning cook-time prediction per probe (history of up to 40 cooks on the device, weather-aware),
  stall detection, cook programs with presets, alerts, cook-complete events.
- Bluetooth proxy (active), Govee H5198 probes as extra food probes.
- Over-the-air updates from GitHub Pages; Improv Wi-Fi setup; ntfy for critical alarms.

### Home Assistant
- Smoker dashboard integration (sidebar page).
- Package: actionable notifications, AI cook planner / advisor / review, ready-by planner, rest timer.
