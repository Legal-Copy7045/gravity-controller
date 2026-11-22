# Changelog

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
