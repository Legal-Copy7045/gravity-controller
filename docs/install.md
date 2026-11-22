# Install

## 1. Flash the ESP32-S3

**Browser (easiest):** open the [web installer](https://legal-copy7045.github.io/gravity-controller/) in Chrome or
Edge, plug the board in with a USB-C *data* cable (on a two-port board, the port labelled **USB**), click
**Install**, then enter your Wi-Fi details when asked. Not asked? Join the **Smoker setup** hotspot with your phone
and choose your network there.

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
# Your build is updated from the ESPHome dashboard: don't offer the prebuilt firmware.
update: !remove
```

(Replace the branch with `main` once the project has one.)

Updates: a board flashed from the web installer checks GitHub Pages every 6 hours and shows **Firmware** under
*Updates* in Home Assistant: install from there. A board built in the ESPHome dashboard is updated from the
dashboard (pull the latest and install).

## 2. Add it to Home Assistant

1. A *Discovered* notification for **Smoker** appears: **Add** (Home Assistant sets up the encryption key). Leave
   *Allow the device to perform Home Assistant actions* **off** (it only sends events, which don't need it).
2. Device page → **Grill IP address**: the grill's IP (give it a DHCP reservation on your router). Find it in your
   router's client list, or in the device log, which prints `Grill reports Wi-Fi status …, IP a.b.c.d` when it
   connects over Bluetooth. Without it the bridge uses Bluetooth only (read-only).
3. **Bridge enabled** (device page): turn it **off** while you use the Char-Griller app (setting up the grill's
   Wi-Fi, firmware updates): the grill only accepts one connection, and the bridge holds it.
4. **ntfy topic** (optional): a long random topic name, e.g. `smoker-9f3k2q7x`. Subscribe to the same topic in the
   ntfy app; critical alarms then reach your phone even if Home Assistant is down.
5. If your weather entity isn't `weather.forecast_home`, change the `weather_entity` substitution (ESPHome dashboard)
   and the same name in the package — or create a template weather entity with that id.

## 3. Home Assistant package

Copy `homeassistant/packages/smoker.yaml` to `/config/packages/smoker.yaml`. If you don't use packages yet, add to
`configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Edit the lines marked **EDIT** in the package: your phone's `notify.mobile_app_…` action (once) and your
`ai_task` entity (three places, all `ai_task.google_ai_task` by default: a search-and-replace does it). Restart Home
Assistant.

## 4. Dashboard

HACS → ⋮ → *Custom repositories* → `https://github.com/Legal-Copy7045/gravity-controller`, type *Integration* →
install **Smoker** → restart → Settings → Devices & services → *Add integration* → **Smoker**. A **Smoker** entry
appears in the sidebar.

(Without HACS: copy `custom_components/smoker` to `/config/custom_components/smoker` and restart.)

## 5. Govee H5198 (optional)

The Smoker device is an active Bluetooth proxy. Put the Govee within range; Home Assistant's **Govee Bluetooth**
integration discovers it. Then, in Settings → Devices & services → Helpers, set **Smoker Govee probe 1 entity** …
**4** to the Govee's probe temperature entities (e.g. `sensor.h5198_xxxx_temperature_probe_1`; check the names on
the Govee device page). The probes then appear on the dashboard as *Govee 1–4* with predictions, and can be used
in programs (`govee1 >= 165`). No firmware change is needed.
