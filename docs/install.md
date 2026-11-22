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
   connects over Bluetooth. **Optional:** without it the bridge reads *and controls* the grill over Bluetooth
   (**Control over Bluetooth**, on by default; see
   [first run](first-run.md#control-over-bluetooth)). Grill Wi-Fi not joining (common on UniFi)? See
   [the grill's Wi-Fi](first-run.md#the-grills-wi-fi-unifi-and-mesh-networks), or just leave it on Bluetooth.
3. **Bridge enabled** (device page): turn it **off** while you use the Char-Griller app (setting up the grill's
   Wi-Fi, firmware updates): the grill only accepts one connection, and the bridge holds it.
4. **ntfy topic** (optional): a long random topic name, e.g. `smoker-9f3k2q7x`. Subscribe to the same topic in the
   ntfy app; critical alarms then reach your phone even if Home Assistant is down.
5. If your weather entity isn't `weather.forecast_home`, change the `weather_entity` substitution (ESPHome dashboard)
   and the same name in the package — or create a template weather entity with that id.

**The controller's own page:** open `http://gravity980.local` (or its IP; on a phone the IP is more reliable) for a
phone page served by the controller itself: connection status first, the grill with live readings, food, pit target
and program, charcoal and setup. It works without Home Assistant and without the internet. ESPHome's standard page
with every entity and the logs is at `http://gravity980.local/?classic` (that one loads from the internet).

## 3. Home Assistant package

**Easiest:** with the Smoker integration installed, run the action **Smoker: Install the Smoker package**
(Developer tools → Actions, `smoker.install_package`) with your phone's notify action, e.g.
`notify: notify.mobile_app_my_phone` (AI task and weather default to `ai_task.google_ai_task` and
`weather.forecast_home`). It writes `/config/packages/smoker.yaml` for you; restart Home Assistant. Run it again after
updating the integration to update the package (from 0.2.19 that happens by itself on each update). Your `configuration.yaml` still needs the `packages:` line below.

By hand: Copy `homeassistant/packages/smoker.yaml` to `/config/packages/smoker.yaml`. If you don't use packages yet, add to
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

**Your grill's photo (optional):** on the dashboard, Setup → **Grill photo** → *Upload a photo* (a phone offers the
camera or your library). Or save it by hand as `/config/www/smoker/grill.png` (or `.jpg`, `.webp`). The dashboard then shows it at the top
with the live readings pinned on it (pit on the barrel, target and link on the controller, food on the front shelf,
charcoal on the hopper, fan on the ash box); without it, a drawing of the grill is used. The pins are placed for a
straight front view like the one in Char-Griller's product photos. Opening the dashboard also passes the photo's
address to the controller (*Grill photo URL*), so the controller's own page shows it too.

## 5. Food probes: grill, H5198 or anything in Home Assistant

The controller has six food slots, **Food 1** to **Food 6**. Each slot reads one thermometer, chosen with its
**Food N probe** select (on the dashboard: *Probe sources*):

| Source | What it is | Defaults |
|---|---|---|
| Grill probe 1 / 2 | The Gravity 980's own food probes (through the bridge). The slot's target is kept in step with the grill's, both ways. | Food 1, Food 2 |
| Home Assistant | Any temperature sensor in Home Assistant, e.g. a Govee H5198 through Home Assistant's **Govee Bluetooth** integration. If the thermometer has its own alarm (Govee: `…_temperature_alarm_probe_N`), that becomes the slot's target when you change it there. | Food 3–6 (the H5198's probes 1–4) |
| H5198 probe 1–4 | A **Govee H5198** read directly over Bluetooth by the controller (no Home Assistant needed; finer, 0.01 °C readings). | |
| Wired probe 1–4 | NTC meat probes plugged into the controller itself (optional ADS1115 add-on, below). | |

Every slot gets the same predictions, stall detection, pull-at and rest coaching, and can be used in cook programs
(`food3 >= 165`).

**Choosing Home Assistant thermometers.** On the dashboard, open *Probe sources*, set a slot to *Home Assistant* and
pick the sensor from the list (temperature sensors, probe-like ones first). Use as many slots as you have probes.
Left on the default, slots 3–6 read `sensor.meat_thermometer_temperature_probe_1` … `_4`: if your thermometer's
entities are named differently, pick them in the list, or change the defaults in the package's *Smoker external
probe N* template sensors. Behind the scenes slot N follows the helper *Smoker external probe N entity*. A Govee probe
that's unplugged reports exactly 0 °C (32 °F); that's treated as no reading.

**Without Home Assistant.** The grill's probes, the H5198 read directly, and wired probes all work with Home Assistant
down: the controller keeps predicting, running programs and sending ntfy alarms. Only *Home Assistant* sources need it.

**H5198 direct.** Nothing to set up: the controller uses the first H5198 that sends probe readings (*H5198
connected* / *H5198 signal* show it). To pin a specific unit, add its Bluetooth address in your device YAML:

```yaml
govee_h5198:
  mac_address: "AA:BB:CC:DD:EE:FF"
```

The format follows Home Assistant's own Govee decoder (govee-ble) and was checked against a real H5198's
broadcasts. If readings stay empty, add `log_raw: true` under `govee_h5198:`, reflash, and send the logged packets.


**Wired probes (optional hardware).** Up to four standard 2.5 mm NTC food probes on the controller: an **ADS1115**
module on I2C (SDA GPIO8, SCL GPIO9 by default) and, per probe, a 100 kΩ 0.1 % resistor from 3.3 V to the ADS1115
input, with the probe jack from that input to GND (diagram in `firmware/wired-probes.yaml`). Build from the ESPHome
dashboard and add the package next to the main one:

```yaml
packages:
  smoker: github://Legal-Copy7045/gravity-controller/firmware/core.yaml@main
  wired: github://Legal-Copy7045/gravity-controller/firmware/wired-probes.yaml@main
```

Then pick *Wired probe N* as a slot's source. Without the add-on those sources simply read nothing. The default curve
suits common 100 kΩ (B 3950) probes; for yours, either set `wired_r25` / `wired_b` (substitutions) from the probe's
datasheet, or calibrate: note the probe's resistance (the ADS1115 voltage in the logs) in ice water, at room
temperature and in boiling water, and use ESPHome's three-point `calibration:` on the `ntc` sensors. Until then,
treat wired readings as experimental and check them against a thermometer you trust.