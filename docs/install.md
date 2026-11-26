# Install

What you need: [README → What you need](../README.md#what-you-need). Home Assistant is optional: without it, flash the
board (step 1) and go to [Running without Home Assistant](standalone.md).

## 1. Flash the ESP32-S3

**Browser (easiest):** open the [web installer](https://legal-copy7045.github.io/gravity-controller/) in Chrome or
Edge on a computer, plug the board in with a USB-C *data* cable (on a two-port board, the chip's own port: labelled
**USB** or **OTG**, not **COM**/**UART**; flashing works on either, but the Wi-Fi step only on that one), click
**Install**, then enter your Wi-Fi details when asked (2.4 GHz). Not asked? See the setup hotspot in step 2.

**Or from the ESPHome dashboard** (ESPHome 2026.11 or newer; lets you change the YAML): create a device and paste

```yaml
substitutions:
  name: gravity980                      # don't change (see below)
  friendly_name: Smoker                 # don't change (see below)
  temperature_unit: "F"                 # or "C"
  weather_entity: weather.forecast_home # your weather entity (outdoor temp, humidity, wind)
packages:
  smoker: github://Legal-Copy7045/gravity-controller/firmware/core.yaml@main
external_components:
  - source: github://Legal-Copy7045/gravity-controller@main
    components: [gravity980, cook_assistant, govee_h5198, standalone]
    refresh: 1d
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
# Your build is updated from the ESPHome dashboard: don't offer the prebuilt firmware, and give the dashboard's
# own over-the-air updates a password (without one, anyone on your Wi-Fi could flash the controller).
update: !remove
ota:
  - platform: esphome
    password: !secret smoker_ota_password
```

**Keep `name` and `friendly_name` as they are.** The dashboard and the Home Assistant package expect the device to be
`gravity980` and its entities `…smoker_…` (actions `esphome.gravity980_*`). Renaming it means editing the package and
the dashboard to match, which isn't supported.

**One controller per network.** The address `gravity980.local` has no suffix, so two controllers on the same network
collide. A second one needs its own build with a different `name`, and then a Home Assistant package edited to match.

### Updates

- **With Home Assistant:** a board flashed from the web installer checks GitHub Pages every 6 hours and shows
  **Firmware** under *Updates* in Home Assistant: install it from there.
- **Without Home Assistant:** if your controller's page shows an update, install it there. Otherwise open the
  [web installer](https://legal-copy7045.github.io/gravity-controller/) again, plug the board in over USB and click
  **Install**, and **don't tick "Erase device"**. Settings, the PIN and learned cooks are normally kept, but note your
  settings first (Wi-Fi, ntfy topic, keys) in case they aren't.
- **Built in the ESPHome dashboard:** update it from the dashboard (pull the latest and install).
- **Signed updates (from 1.1.0):** released firmware is signed, and a controller running it only installs updates
  signed with the same key, and never an older version. Someone who took over the download site couldn't push their
  own firmware to it. Flashing over USB from the web installer always works, so it's never stuck.
- **Automatic updates (from 1.2.0, off by default):** turn on *Automatic updates* in Home Assistant (the controller's
  configuration) or on the controller's page (Setup → This controller). A new release is then installed only after
  the controller has been idle for an hour: grill not connected, no cook active, no program running or paused. You
  get a "Controller updated" notification when it's back.
- **Automatic rollback (from 1.4.0):** a new firmware is on trial until it has held its Wi-Fi for a minute. If it
  crashes or hangs in its first 15 minutes, or can't stay on the network for 10, the controller goes back to the
  version it had and tells you; automatic updates then skip that version (you can still install it by hand).
- **Local only (from 1.4.0, off by default):** *Local only (no internet)* (Setup → This controller) stops every
  internet connection the controller makes, and what the integration does on its behalf: weather, the AI, Pushover,
  Telegram, ntfy, Open Pitmaster, update checks and the internet clock. Home Assistant on your network still works and
  is then the only way alerts reach your phone: **without Home Assistant, local only means no alerts at all** (Setup →
  Connectivity says so). Without Home Assistant, clock times (`at 17:30`, the serve-by planner) need the internet clock,
  so they stop too, and after a power cut the grill isn't turned back on automatically (the outage can't be measured).
  Requests already waiting when you turn it on are dropped too. One exception: an update that was already found before
  you turned it on can still be installed by hand (Install downloads it); no new update is looked for. After a Home
  Assistant restart, the integration counts a controller it hasn't seen yet as local only until it connects.
- **Connectivity:** one line (Setup → This controller) shows the grill link, the controller's Wi-Fi, Home Assistant
  and the internet. During a cook you're told if Home Assistant goes away (alerts then come straight to your phone,
  if a direct route is set up and Local only is off) and, when the controller's Wi-Fi comes back, how long it was
  offline. A Wi-Fi that worked and then stays stuck for 20 minutes with no cook restarts the controller; a second
  restart in a row waits for 2 hours of Wi-Fi down, a third for 6 hours, and then it stops trying (never during a
  cook, and never a controller that hasn't joined its Wi-Fi yet).

**Logs.** The controller's page doesn't show its log. Use the web installer's **Logs & console** over USB (click
**Install**, connect, then *Logs & console*), the ESPHome dashboard's *Logs* if you build it yourself, or the
ESPHome integration in Home Assistant.

## 2. Add it to Home Assistant

**Add it within 15 minutes of plugging it in; otherwise unplug it and plug it back in.** Until Home Assistant adopts
the controller (and sets its encryption key), it accepts a new connection only in the first 15 minutes after power-on.
The same window covers its Wi-Fi setup:

- **Setup hotspot:** if the controller can't join Wi-Fi for 90 s, it opens a **Smoker setup** hotspot. Join it from
  your phone and pick your network. It only appears within the 15 minutes, and never once the controller has joined
  your Wi-Fi (until it's restarted).
- **Bluetooth Wi-Fi setup (Improv):** also needs a short press of the board's **BOOT** button, so someone nearby
  can't move it to their own Wi-Fi.

Then:

1. A *Discovered* notification for **Smoker** appears: **Add** (Home Assistant sets up the encryption key). Leave
   *Allow the device to perform Home Assistant actions* **off** (it only sends events, which don't need it).
   No notification? Discovery needs Home Assistant on the same network as the board (Nabu Casa doesn't help here):
   Settings → Devices & services → *Add integration* → **ESPHome** → host `gravity980.local` or the board's IP
   (from your router). Erasing the board when reflashing clears the key; Home Assistant then asks to reconfigure.
   Home Assistant may also offer a **Govee** Bluetooth device (the H5198, seen through the smoker's Bluetooth
   proxy): you can ignore it; the controller reads the H5198 itself.
2. Device page → **Grill IP address**: the grill's IP (give it a DHCP reservation on your router). Find it in your
   router's client list, or in the controller's log (see *Logs* above), which prints `Grill reports Wi-Fi status …, IP
   a.b.c.d` when it connects over Bluetooth. Left empty, the bridge uses the IP the grill reports only right after
   **Grill Wi-Fi: join saved network** (or a Wi-Fi setup), and only a private address on the controller's own network
   ([why](protocol.md#trust)). **Optional:** without it the bridge reads *and controls* the grill over Bluetooth
   (**Control over Bluetooth**, on by default; see [first run](first-run.md#control-over-bluetooth)). Grill Wi-Fi not
   joining (common on UniFi)? See [the grill's Wi-Fi](first-run.md#the-grills-wi-fi-unifi-and-mesh-networks), or just
   leave it on Bluetooth.
3. **Bridge enabled** (device page): turn it **off** while you use the Char-Griller app (setting up the grill's
   Wi-Fi, firmware updates): the grill only accepts one connection, and the bridge holds it.
4. **ntfy topic** (optional): a long random topic name, e.g. `smoker-9f3k2q7x`. Subscribe to the same topic in the
   ntfy app; critical alarms then reach your phone even if Home Assistant is down. The ntfy server must be a public
   `https://` address (the default, ntfy.sh, is fine).
5. **Weather:** the simplest is to set your area on the controller's own page (Setup → *Weather and time*; Open-Meteo, free, no
   account). It wins over Home Assistant's weather and works whatever your weather entity is called. Without it, the
   prebuilt firmware reads current conditions from `weather.forecast_home` (in your own build: the `weather_entity`
   substitution). The package's weather choice (step 3) is separate: Home Assistant uses it for the hourly forecast it
   sends to the controller and for the AI.

**The controller's own page:** open `http://gravity980.local` (or its IP; on a phone, Android especially, the IP is
more reliable) for a phone page served by the controller itself: connection status first, the grill with live
readings, food, pit target and program, charcoal and setup. It works without Home Assistant and without the internet,
and loads nothing from other sites. A PIN is optional: to lock changes, set one there (Setup → This page's PIN) whenever
you like ([details](standalone.md#the-device-pages-pin)), or set it from Home Assistant at any time:
Developer tools → Actions, **Smoker: Set the device page PIN** (`smoker.set_device_pin`, admin only; empty clears it).

## 3. Home Assistant package

The Smoker integration (dashboard and package installer) and its package. Needs Home Assistant **2025.11** or newer.

1. **Install from HACS:** HACS → ⋮ → *Custom repositories* → `https://github.com/Legal-Copy7045/gravity-controller`,
   type *Integration* → install **Smoker**.
2. **Restart** Home Assistant.
3. Settings → Devices & services → *Add integration* → **Smoker**. A **Smoker** entry appears in the sidebar.
4. **Make sure `configuration.yaml` loads packages.** If you don't use packages yet, add:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

5. **Run the action Smoker: Install the Smoker package** (Developer tools → Actions, `smoker.install_package`) with
   your phone's notify action, e.g. `notify: notify.mobile_app_my_phone`. Optional fields: `ai_task` (default
   `ai_task.google_ai_task`), `weather` (default `weather.forecast_home`), `calendar` (an event called "BBQ",
   "brisket"… sets the serve-by time) and `todo` (charcoal to buy). It writes `/config/packages/smoker.yaml` and
   remembers your choices.
6. **Restart** Home Assistant again.

After that, each update of the integration through HACS updates the package by itself (with your choices, and a
backup); the one restart HACS asks for is enough.

Notification buttons carry a one-time code, so buttons on notifications sent before an update may stop working; use
the dashboard instead. Starting a cook by voice asks you to say "confirm smoker start".

(Without HACS: copy `custom_components/smoker` to `/config/custom_components/smoker` and restart.)

**By hand instead of the action:** copy `homeassistant/packages/smoker.yaml` to `/config/packages/smoker.yaml` (with the
`packages:` line above) and replace the placeholders marked **EDIT** (search-and-replace does each):

| Placeholder | Replace with |
|---|---|
| `notify.mobile_app_your_phone` (once) | your phone's notify action |
| `ai_task.google_ai_task` (three places) | your AI Task entity |
| `weather.forecast_home` (every one) | your weather entity |
| `calendar.your_calendar` (once) | a calendar for serve-by times (optional) |
| `todo.shopping_list` (every one) | a to-do list for charcoal and upkeep (optional) |

Then restart Home Assistant. A package copied by hand is never changed by updates: copy and edit it again after each
one.

## 4. Dashboard

The **Smoker** sidebar entry (from step 3) is the dashboard. It starts in **Basic** (what the Char-Griller app does);
switch to **Advanced** above the section bar for programs, AI, charcoal, planning and the journal.

**Your grill's photo (optional):** on the dashboard, Setup → **Grill photo** → *Upload a photo* (a phone offers the
camera or your library; administrators only). Or save it by hand as `/config/www/smoker/grill.png` (or `.jpg`,
`.webp`). The dashboard then shows it at the top with the live readings pinned on it (pit on the barrel, target and
link on the controller, food on the front shelf, charcoal on the hopper, fan on the ash box); without it, a drawing of
the grill is used. The pins are placed for a straight front view like the one in Char-Griller's product photos.
Opening the dashboard also passes the photo's address to the controller (*Grill photo URL*), so the controller's own
page shows it too.

## 5. Food probes: grill, H5198 or anything in Home Assistant

The controller has six food slots, **Food 1** to **Food 6**. Each slot reads one thermometer, chosen with its
**Food N probe** select (on the dashboard: *Probe sources*):

| Source | What it is | Defaults |
|---|---|---|
| Grill probe 1 / 2 | The food probes plugged into the Gravity 980's controller (read through the bridge). The slot's target is kept in step with the grill's, both ways. | Food 1, Food 2 |
| Home Assistant | Any temperature sensor in Home Assistant, e.g. a Govee H5198 through Home Assistant's **Govee Bluetooth** integration. If the thermometer has its own alarm (Govee: `…_temperature_alarm_probe_N`), that becomes the slot's target when you change it there. | Food 3–6 (the H5198's probes 1–4) |
| H5198 probe 1–4 | A **Govee H5198** read directly over Bluetooth by the controller (no Home Assistant needed; finer, 0.01 °C readings). | |

Every slot gets the same predictions, stall detection, pull-at and rest coaching, and can be used in cook programs
(`food3 >= 165`).

**One food, several probes.** On the dashboards, *What's cooking* lists foods, not slots: **Add food**, then give it a
name, cut and weight. **Add another probe in it** puts a second slot in the same food (say where it is: breast, thigh)
with its own target. Slots with the same **Food N name** are one food: the serve-together plan and its "put it on"
reminder count it once (at its slowest probe), and alerts name it ("Turkey (breast) is done").

**Choosing Home Assistant thermometers.** On the dashboard, open *Probe sources*, set a slot to *Home Assistant* and
pick the sensor from the list (temperature sensors, probe-like ones first). Use as many slots as you have probes.
Left on the default, slots 3–6 read `sensor.meat_thermometer_temperature_probe_1` … `_4`: if your thermometer's
entities are named differently, pick them in the list, or change the defaults in the package's *Smoker external
probe N* template sensors. Behind the scenes slot N follows the helper *Smoker external probe N entity*. A Govee probe
that's unplugged reports exactly 0 °C (32 °F); that's treated as no reading.

**Without Home Assistant.** The grill's probes and the H5198 read directly both work with Home Assistant down: the controller keeps predicting, running programs and sending ntfy alarms. Only *Home Assistant* sources need it.

**H5198 direct.** Nothing to set up: the controller uses the first H5198 that sends probe readings (*H5198
connected* / *H5198 signal* show it) and remembers it once it has been heard steadily for a minute. A probe reading
that jumps more than 15 °C within 10 s is shown only once it repeats in 3 advertisements in a row (a probe really moved
into the pit still shows within a second or two). Advertisements aren't authenticated, so to pin your unit (and never
pick up a neighbour's or a look-alike), add its Bluetooth address in your device YAML:

```yaml
govee_h5198:
  mac_address: "AA:BB:CC:DD:EE:FF"
```

The format follows Home Assistant's own Govee decoder (govee-ble) and was checked against a real H5198's
broadcasts. If readings stay empty, add `log_raw: true` under `govee_h5198:`, reflash, and
[open an issue](https://github.com/Legal-Copy7045/gravity-controller/issues/new/choose) (template: *Grill data*) with
the logged packets.


## Before you sell or give away your controller

1. **Factory reset it:** Setup → This controller → **Factory reset** on the device page (tap twice within 10 s), the
   controller's **Factory reset** button in Home Assistant (press twice within 10 s), or hold the board's **BOOT**
   button for 30 s. It erases the Wi-Fi, the API key, the PIN and sessions, notification and AI keys, all settings,
   the journal and learned cooks, then restarts with its setup hotspot.
2. **Remove it from Home Assistant** (Settings → Devices & services → ESPHome → the controller → Delete).
3. **Rotate the keys that were stored on it** (AI API key, ntfy topic, Pushover and Telegram tokens): the flash isn't
   encrypted, so someone with the board in hand could have read them. More in
   [standalone.md](standalone.md#before-you-sell-or-give-away-your-controller).
