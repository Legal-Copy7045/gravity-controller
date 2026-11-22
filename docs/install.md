# Install

## 1. Flash the ESP32-S3

**Browser (easiest):** open the [web installer](https://legal-copy7045.github.io/gravity-controller/) in Chrome or
Edge, plug the board in with a USB-C *data* cable (on a two-port board, the chip's own port: labelled **USB** or **OTG**, not **COM**/**UART**; flashing works on either, but the Wi-Fi step only on that one), click
**Install**, then enter your Wi-Fi details when asked. Not asked? Join the **Smoker setup** hotspot with your phone
and choose your network there.

**Or from the ESPHome dashboard** (ESPHome 2026.11 or newer; lets you change the YAML): create a device and paste

```yaml
substitutions:
  name: gravity980
  friendly_name: Smoker
  temperature_unit: "F"                 # or "C"
  weather_entity: weather.forecast_home # your weather entity (outdoor temp, humidity, wind)
packages:
  smoker: github://Legal-Copy7045/gravity-controller/firmware/core.yaml@main
external_components:
  - source: github://Legal-Copy7045/gravity-controller@main
    components: [gravity980, cook_assistant, govee_h5198]
    refresh: 1d
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
# Your build is updated from the ESPHome dashboard: don't offer the prebuilt firmware.
update: !remove
```



Updates: a board flashed from the web installer checks GitHub Pages every 6 hours and shows **Firmware** under
*Updates* in Home Assistant: install from there. A board built in the ESPHome dashboard is updated from the
dashboard (pull the latest and install).

## 2. Add it to Home Assistant

1. A *Discovered* notification for **Smoker** appears: **Add** (Home Assistant sets up the encryption key). Leave
   *Allow the device to perform Home Assistant actions* **off** (it only sends events, which don't need it).
   No notification? Discovery needs Home Assistant on the same network as the board (Nabu Casa doesn't help here):
   Settings → Devices & services → *Add integration* → **ESPHome** → host `gravity980.local` or the board's IP
   (from your router). Erasing the board when reflashing clears the key; Home Assistant then asks to reconfigure.
   Home Assistant may also offer a **Govee** Bluetooth device (the H5198, seen through the smoker's Bluetooth
   proxy): you can ignore it; the controller reads the H5198 itself.
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

Edit the lines marked **EDIT** in the package: your phone's `notify.mobile_app_…` action (once), your `ai_task`
entity (three places, all `ai_task.google_ai_task` by default) and, if yours is different, your weather entity (all
`weather.forecast_home`). Search-and-replace does each. Restart Home Assistant.

## 4. Dashboard

HACS → ⋮ → *Custom repositories* → `https://github.com/Legal-Copy7045/gravity-controller`, type *Integration* →
install **Smoker** → restart → Settings → Devices & services → *Add integration* → **Smoker**. A **Smoker** entry
appears in the sidebar.

(Without HACS: copy `custom_components/smoker` to `/config/custom_components/smoker` and restart.)

## 5. Food probes: grill, H5198 or anything in Home Assistant

The controller has six food slots, **Food 1** to **Food 6**. Each slot reads one thermometer, chosen with its
**Food N probe** select (on the dashboard: *Probe sources*):

| Source | What it is | Defaults |
|---|---|---|
| Grill probe 1 / 2 | The Gravity 980's own food probes (through the bridge). The slot's target is kept in step with the grill's, both ways. | Food 1, Food 2 |
| H5198 probe 1–4 | A **Govee H5198** read directly over Bluetooth by the controller (no Govee app, no cloud, no Home Assistant needed). | Food 3–6 |
| Home Assistant | Any temperature entity in Home Assistant (another thermometer, a Wi-Fi probe, …). | |

Every slot gets the same predictions, stall detection, pull-at and rest coaching, and can be used in cook programs
(`food3 >= 165`).

**H5198.** Nothing to set up: the controller listens for the first H5198 it hears and uses it (the *H5198 connected*
and *H5198 signal* entities show it). To pin a specific thermometer when there are several nearby, add its Bluetooth
address in your device YAML:

```yaml
govee_h5198:
  mac_address: "AA:BB:CC:DD:EE:FF"
```

The H5198's advertisement format comes from one community decoder and hasn't been checked on many units. If the
probes stay empty while the thermometer shows temperatures, add `log_raw: true` under `govee_h5198:`, reflash, and
send the logged packets (they contain no personal data).

**Home Assistant entities.** Set the slot's source to *Home Assistant*, then type the entity (e.g.
`sensor.kitchen_probe_temperature`) into the box that appears, or set the helper **Smoker external probe N entity**
in Settings → Devices & services → Helpers. Slot N reads helper N. Home Assistant passes it on in °F; change
`weather_temperature_unit` if your Home Assistant uses °C.
