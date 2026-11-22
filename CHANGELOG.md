# Changelog

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
  bad weights and ratings return a message instead of an error; photo names can't collide; unused photos are
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
