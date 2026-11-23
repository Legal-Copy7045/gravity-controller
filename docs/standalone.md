# Running without Home Assistant

The controller runs a cook on its own:
- the grill link over Bluetooth or Wi-Fi;
- probes: the grill's own, a Govee H5198 read directly, and wired probes;
- cook programs, finish-time predictions and learning, and the charcoal gauge;
- its own web page (`http://gravity980.local`).

This page covers what replaces Home Assistant for the rest. Everything here also works alongside Home Assistant.

## Getting started without Home Assistant

1. **Flash it** from the [web installer](https://legal-copy7045.github.io/gravity-controller/) and give it your Wi-Fi
   ([install, step 1](install.md#1-flash-the-esp32-s3)). No Wi-Fi prompt? Within 15 minutes of plugging it in, join
   its **Smoker setup** hotspot (it appears after 90 s without Wi-Fi), or use Bluetooth setup after a short press of
   its **BOOT** button.
2. **Open `http://gravity980.local`** on your phone (same Wi-Fi). On Android, or if the name doesn't open, use the
   controller's IP address (from your router's list of devices). A **Get started** list walks you through the rest;
   each item opens the card that does it:
   - **Protect this page with a PIN**;
   - **Find the grill**: turn the grill on and the controller finds it over Bluetooth (on Wi-Fi, enter its IP);
   - **Alerts on your phone**: **Set up ntfy in one tap** makes a long random topic and shows it once; install the
     ntfy app, tap **+** and subscribe to it, then **Send a test**. Pushover and Telegram are under Setup;
   - **Your time zone and weather**;
   - **AI pitmaster** (optional): your own Gemini, Claude or OpenAI key.
3. The list goes away once the first four are done, or with **Hide this**. Open `http://gravity980.local/?start` to
   see it again.

**Set the PIN soon after plugging it in:** the first PIN can only be set within 15 minutes of power-on (see below).
Mount the controller so you can still reach its **BOOT** button: it clears a forgotten PIN and allows Bluetooth Wi-Fi
setup.

**Updating without Home Assistant:** if your controller's page shows an update, install it there. Otherwise open the
web installer again, plug the controller in over USB, click **Install** and don't tick *Erase device*. Settings are
normally kept, but note them first (Wi-Fi, notification topic, keys). Logs: the web installer's **Logs & console**
over USB.

**Building your own firmware without Home Assistant?** Use `firmware/base.yaml` instead of `firmware/core.yaml`:
- `core.yaml` is `base.yaml` plus `home-assistant.yaml`: the API, Home Assistant's clock, weather and thermometers,
  the Bluetooth proxy, and the events Home Assistant listens for;
- `base.yaml` alone has no API at all;
- `tests/configs/no-ha.yaml` is checked on every build.

## The device page's PIN

Anyone on your Wi-Fi can open the controller's page. **Set a PIN** (Setup → This page's PIN) and every change made
through the page needs it. That covers pit targets, programs, switches, settings and keys. Readings stay open on
your network. A PIN is also required before notification or AI keys can be stored.

How it's protected:
- **Hashed, never stored:** the PIN is hashed with PBKDF2-HMAC-SHA256 (20,000 rounds, random salt). Only the salt
  and the hash are stored.
- **Rules:** at least 6 characters; repeated or sequential ones (111111, 123456) are refused.
- **Setting the first PIN:** only within 15 minutes of powering the controller on (or of holding its BOOT button
  for 10 s, which clears a forgotten PIN), so someone else on your Wi-Fi can't set one first and lock you out. A
  restart from the page doesn't reopen that window; unplugging it does.
- **Lockout:** 5 wrong PINs from one device lock that device out for 30 s, then 60 s, doubling up to an hour; other
  devices aren't affected. Empty or malformed PINs aren't counted.
- **Sessions:** unlocking gives this browser a random 256-bit session, valid for 12 hours after its last change. At
  most 4 are live, and changing the PIN ends them all.
- **Other websites:** they can't send changes on your behalf; the web server refuses cross-origin requests.
- **Keys are write-only:** notification and AI keys can be replaced or removed, never read back, and they're never
  written to the logs.

**Forgotten the PIN?** Hold the controller's **BOOT** button for 10 seconds, or press **Clear the device page PIN**
in Home Assistant. Then set a new one. Your keys and settings are kept.

## Notifications straight to your phone

Setup → Notifications. **Send them:**
- **Automatic** (default): via Home Assistant while it's connected, straight to your phone when it isn't;
- **Only via Home Assistant**: as before;
- **Only straight to my phone**;
- **Both**: you may get two of each.

**Critical alarms** (the fire's out, far too hot, probe trouble during a cook) always go straight to your phone too,
whenever a service is set up.

Pick one or more services:

| Service | Cost | Set up |
|---|---|---|
| **ntfy** | Free, open source | Install the ntfy app and subscribe to a long, random topic (e.g. `smoker-k3v9x2q7`): anyone who knows the topic can read it. Enter the same topic on the controller. Self-hosting? Change the server: it must be a public `https://` name (a LAN-only name doesn't work), and changing it clears the topic. |
| **Pushover** | One-off app purchase | Your user key from pushover.net, plus an app token (create an application there). |
| **Telegram** | Free | Create a bot with @BotFather (gives the bot token), send your bot a message, then look up your chat ID (e.g. with @userinfobot). |

**Send a test** checks the set-up. The card shows whether each service accepted the last message.

## Weather and time

- **Weather:**
  - Enter your town on the device page. The search goes from your phone to Open-Meteo, not through the controller.
  - The controller stores the area, rounded to about 1 km, and fetches the current conditions and a 24-hour forecast
    from Open-Meteo (free, no account) every 30 minutes.
  - That feeds the finish-time predictions, the stall and charcoal estimates and the AI.
  - With an area set it wins over Home Assistant's weather. Remove it to go back.
- **Time:**
  - The controller sets its clock from internet time servers (and from Home Assistant when it's there).
  - **Use this phone's time zone** sends the zone's offsets and daylight-saving rules, worked out by your browser.
    Without it, and without Home Assistant, clock times show in UTC.

## On the device page (no Home Assistant needed)

- **Basic and Advanced:** the switch sits just above the section bar. **Basic** is what the Char-Griller app does:
  pit and food temperatures and targets, the timer, Turbo, turning the grill on or off, the fan/lid/turbo state, the
  chart and Setup. **Advanced** adds everything else: Plan, AI, the journal, Charcoal, programs and estimates. A
  browser that hasn't used the page before starts in **Basic**, so switch to **Advanced** to see Plan, AI, Journal and
  Charcoal. Each browser remembers its choice, and the mode only changes the page: alerts, programs and Boost run
  either way.
- **Pit target:** − / type it / + and **Set**, first thing on the page. The grill only takes targets while it's
  cooking (start the cook on its panel).
- **Turbo:** the grill's own Turbo (the fan runs flat out), the same as the panel's button. The button shows the
  grill's turbo state.
- **Turn on / Turn off:** two taps within 10 s. The first tap arms it (the button turns red: *Tap again to turn
  off*), the second does it. The controller enforces this, so one press from anywhere does nothing. Turning on works
  while the grill is in standby with its Bluetooth awake.
- **Boost** (Advanced): raises the pit target by 100 °F until the pit reaches yours, for up to 15 minutes, without
  disturbing a running program. *Stop boost* ends it.
- **Timer:** type the minutes and press **Start**; you get a notification when it's done. The controller keeps it,
  so it works without Home Assistant (a restart clears it).
- **Chips:** *Fan on* while the fan runs, *Turbo (panel)* when turbo is on at the grill, *Lid open*. The on/off
  button follows the grill's own on flag (*Grill on*).
- **Temperatures:** a chart of the pit, the pit target and every food probe for the last 3, 6, 12 or 24 hours. The
  controller keeps one point a minute for 24 hours in memory, so a restart clears it.
- **Charcoal:** log it as on the dashboard: *Started at*, *It's at*, *Topped up to*, *Added*, *Finished with*.
- **Plan:** set **Serve by** and the rest time. The controller works out *Light the grill by* from its own estimate
  (set the cut and weight on a Food card) and sends a notification when it's time. Resting and the "ready to slice"
  alert were already on the controller.
- **Cook journal:**
  - every finished cook is kept in the controller's flash (the last 24);
  - you can add stars, **How was it?** tags (texture, doneness, bark, smoke, fat) and a note, or remove an entry.
- **Open Pitmaster:**
  - share cooks anonymously straight from the controller (Setup → Open Pitmaster; off unless you turn it on);
  - the journal asks *Share this cook?* once a cook is rated or 12 hours old, and shows exactly what's sent;
  - **Share automatically** skips the question, **Remove my shared cooks** deletes what you've shared, and
    **Download my cooks (anonymised)** lets you look first;
  - the Plan card shows the shared averages for the cuts you're cooking;
  - if you also share from Home Assistant's Smoker page, turn one of them off, or each cook would be shared twice.

## The AI pitmaster on the controller

Setup → AI: pick **Google Gemini**, **Anthropic Claude** or **OpenAI**, paste your API key (it needs the PIN, and is
write-only like the notification keys), and press **Test the key**. You pay the provider per question: a few cents a
cook. The model can be changed; the defaults are `gemini-flash-lite-latest`, `claude-opus-5-5` and `gpt-4.1-mini`. With Claude
the controller asks for Anthropic's server-side fallback, so a question the main model declines can be answered by a
fallback model in the same call.

Once it's set up, an **AI pitmaster** section appears on the page:
- **Second opinion:** how the cook is going, the next thing to do, its own finish estimate and a few timed tips.
  **Ask now**, or turn on **every 30 min during a cook**.
- **Plan with AI:** describe the cook ("9 lb pork shoulder, eating at 6 pm Saturday"). It suggests when to light up and
  the steps, and writes a cook program: **Load as program**, check it under Pit & program, then Start.
- **What's cooking:** **Take a photo** or **Choose a photo** of the package label. The page shrinks it, the AI reads
  the cut and weight, and **Set** puts them on a Food slot.

**It only works on a cook.** Nothing is asked unless a cook is underway (the pit is up, or a program is running) or
planned (**Serve by** within the next two days). On an idle grill **Ask now** is greyed out and the 30-minute check
doesn't run; Plan with AI and label reading still work, because that's planning. As a backstop, the controller asks
at most 40 questions a day.

What's sent: the live readings and settings, this grill's learned cooks, your journal entries (stars, tags, notes), the
Open Pitmaster averages for your cuts and the weather numbers. Never your area, Wi-Fi, PIN or other keys. Label photos
go to the provider and aren't kept on the controller.

## Still needs Home Assistant

| Feature | Without Home Assistant |
|---|---|
| Thermometers that live in Home Assistant (e.g. the Govee via its integration) | Use the H5198 directly (Bluetooth) or wired probes |
| Voice ("when is it done?") | Not available |
| "Controller offline" alert | A controller can't report its own power cut; Home Assistant (or a ping service) can |
