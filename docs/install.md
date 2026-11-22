# Install

## 1. Flash the ESP32-S3

**Browser (easiest):** open the [web installer](https://legal-copy7045.github.io/gravity-controller/) in Chrome or
Edge, plug the board in with a USB-C *data* cable, click **Install**, then enter your Wi-Fi details when asked.

**Or from the ESPHome dashboard** (lets you change the YAML): create a device and paste

```yaml
substitutions:
  name: gravity980
  friendly_name: Smoker
  temperature_unit: "F"                 # or "C"
  weather_entity: weather.forecast_home # your weather entity (outdoor temp, humidity, wind)
packages:
  smoker: github://Legal-Copy7045/gravity-controller/firmware/core.yaml@claude/intelligent-cori-rntbhy
external_components:
  - source: github://Legal-Copy7045/gravity-controller@claude/intelligent-cori-rntbhy
    components: [gravity980, cook_assistant]
    refresh: 1d
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
```

(Replace the branch with `main` once the project has one.)

Updates: the device checks GitHub Pages every 6 hours and shows **Firmware** under *Updates* in Home Assistant.
Install from there, or from the ESPHome dashboard.

## 2. Add it to Home Assistant

1. A *Discovered* notification for **Smoker** appears: **Add**. Leave *Allow the device to perform Home Assistant
   actions* **off** (it only sends events, which don't need it).
2. Device page → **Grill IP address**: the grill's IP (give it a DHCP reservation on your router). Without it the
   bridge uses Bluetooth only (read-only).
3. **ntfy topic** (optional): a long random topic name, e.g. `smoker-9f3k2q7x`. Subscribe to the same topic in the
   ntfy app; critical alarms then reach your phone even if Home Assistant is down.
4. If your weather entity isn't `weather.forecast_home`, change the `weather_entity` substitution (ESPHome dashboard)
   — or create a template weather entity with that id.

## 3. Home Assistant package

Copy `homeassistant/packages/smoker.yaml` to `/config/packages/smoker.yaml`. If you don't use packages yet, add to
`configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Edit the two lines marked **EDIT** in the package: your phone's `notify.mobile_app_…` action and your
`ai_task` entity. Restart Home Assistant.

## 4. Dashboard

HACS → ⋮ → *Custom repositories* → `https://github.com/Legal-Copy7045/gravity-controller`, type *Integration* →
install **Smoker** → restart → Settings → Devices & services → *Add integration* → **Smoker**. A **Smoker** entry
appears in the sidebar.

(Without HACS: copy `custom_components/smoker` to `/config/custom_components/smoker` and restart.)

## 5. Govee H5198 (optional)

The Smoker device is an active Bluetooth proxy. Put the Govee within range; Home Assistant's **Govee Bluetooth**
integration discovers it. Then set the `govee_probe_1..4` substitutions to its probe entities (ESPHome dashboard) so
the four probes appear as *Govee 1–4* with predictions, and can be used in programs (`govee1 >= 165`).
