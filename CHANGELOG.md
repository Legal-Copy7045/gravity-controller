# Changelog

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
