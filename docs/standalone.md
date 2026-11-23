# Running without Home Assistant

The controller runs a cook on its own:
- the grill link over Bluetooth or Wi-Fi;
- probes: the grill's own, a Govee H5198 read directly, and wired probes;
- cook programs, finish-time predictions and learning, and the charcoal gauge;
- its own web page (`http://gravity980.local`).

This page covers what replaces Home Assistant for the rest. Everything here also works alongside Home Assistant.

## The device page's PIN

Anyone on your Wi-Fi can open the controller's page. **Set a PIN** (Setup → This page's PIN) and every change made
through the page needs it. That covers pit targets, programs, switches, settings and keys. Readings stay open on
your network. A PIN is also required before notification or AI keys can be stored.

How it's protected:
- **Hashed, never stored:** the PIN is hashed with PBKDF2-HMAC-SHA256 (20,000 rounds, random salt). Only the salt
  and the hash are stored.
- **Rules:** at least 6 characters; repeated or sequential ones (111111, 123456) are refused.
- **Lockout:** 5 wrong PINs lock the page for 30 s, then 60 s, doubling up to an hour.
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
| **ntfy** | Free, open source | Install the ntfy app and subscribe to a long, random topic (e.g. `smoker-k3v9x2q7`): anyone who knows the topic can read it. Enter the same topic on the controller. Self-hosting? Change the server (https only). |
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

## Still needs Home Assistant

| Feature | Without Home Assistant |
|---|---|
| Thermometers that live in Home Assistant (e.g. the Govee via its integration) | Use the H5198 directly (Bluetooth) or wired probes |
| Voice ("when is it done?") | Not available |
| The AI pitmaster, Plan with AI, reading labels | Coming: on the controller with your own Gemini, Claude or OpenAI key |
| "Controller offline" alert | A controller can't report its own power cut; Home Assistant (or a ping service) can |
