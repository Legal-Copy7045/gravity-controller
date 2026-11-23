# Changelog

## [0.2.49] - 2026-11-23

- **Turbo and Turn the grill off, as the Char-Griller app sends them**, found in the app's own code (v2.0.8).
  - Both are command 0x04, whose value holds four flags: F leaves a flag alone, 0 or 1 sets it.
  - Turbo on is `FF 04 FF 1F`, turbo off is `FF 04 FF 0F`, and power off is `FF 04 0F FF`.
  - New entities: *Turbo* (switch; its state is the grill's own turbo flag) and *Turn the grill off* (button).
  - Not yet confirmed on a grill.
- **Command 0x05 shows a pairing code on the grill's display.** It doesn't silence the alarm. The app sends the code
  as hex digits (`FF 05 46 55` shows 4655) and asks you to type it in.
- **Capture mode is out of the released firmware.** It's now a developer config, `firmware/dev-capture.yaml`, which
  CI still checks.
- **Command tests accept 0x04, one flag at a time** (like `0FFF` or `FF1F`), for checking these on a real grill.

## [0.2.48] - 2026-11-23

- **Basic and Advanced mode** (both dashboards; the switch sits above the section bar, and each browser remembers
  its choice):
  - **Basic is what the Char-Griller app does:** the pit's temperature and target, food probes with their temperature
    and target, a timer, Boost (for turbo), the fan, lid and turbo state, the temperature chart, and Setup.
  - **Advanced is everything:** programs, AI, charcoal, planning, the journal, estimates and more.
  - A browser that hasn't used the page before starts in Basic. One that has starts in Advanced.
  - The mode only changes the page: alerts, programs and Boost run either way.
- **A timer, like the app's:** type the minutes and press Start. You get a notification when it's done.
  - It's kept by the controller, so it works without Home Assistant (it doesn't survive a restart).
  - New entities: *Timer* and *Timer remaining*.
- **A *Fan on* chip** on the controller's page.
- **Find the app's commands** (Setup, and a config switch *Capture the app's commands*): for 10 minutes the controller
  poses as the grill so the Char-Griller app connects to it, and lists every byte the app sends. Switch the grill off,
  turn capture on, connect the app to *Gravity980-XXXX* and press Power and Turbo: that's how their commands will be found.
  Nothing is ever sent to the grill, and a Wi-Fi password the app sends isn't kept (docs/protocol.md).

## [0.2.47] - 2026-11-23

**Security release: the fixes from a full audit.** It looked for anything that would let someone else control the
grill, the controller or Home Assistant, or use one to get into another.

**The controller**
- **First 15 minutes only:** until Home Assistant adopts the controller (and sets its encryption key), it accepts a new
  connection only for 15 minutes after power-on. The same goes for its setup hotspot and Bluetooth Wi-Fi setup.
  - Bluetooth Wi-Fi setup also needs a short press of the BOOT button.
  - The setup hotspot no longer comes back once the controller has joined your Wi-Fi.
- **The first device-page PIN:** it can be set only within 15 minutes of powering on, or of holding BOOT for 10 s.
  **No PIN yet? Unplug the controller and plug it back in, then set one.**
- **Wrong PINs:** they now lock out only the device that sent them. A global limit stays as a backstop, and empty
  PINs aren't counted.
- **ntfy:**
  - Changing the ntfy server clears the topic; enter it again.
  - The server must be a public https name. **A self-hosted ntfy on a LAN-only name no longer works.**
  - Redirects are never followed.
- **Requests addressed to another hostname** (DNS rebinding) are refused, reads included. Logs no longer stream to
  the page.
- **Before you unlock:** the AI plan, advice and the serve-by time are hidden.
- **Removed:** `?classic` and the web fonts. The page loads nothing from other sites.

**The grill link**
- **Grill Wi-Fi setup:** the password goes only to the grill the controller already knows.
  - That means one remembered before the last restart, or for 10+ minutes, or `bluetooth: mac_address`.
  - It must also be sending status and have a strong signal.
  - The page shows which device got it.
- **Look-alike grills:**
  - Only a "Gravity980-" device can take over from the remembered grill, and only after 10 minutes of silence.
  - A new grill is remembered only after 2 minutes of good data.
- **The address the grill reports:** used only right after a Wi-Fi setup, and only if it's on the controller's own
  network.
- **Wi-Fi and Bluetooth disagree** for 30 s: Wi-Fi is dropped.
- **Limits and checks:**
  - Scan results only during a scan, capped.
  - Test commands can't send setpoints.
  - TCP reads capped per loop.
- **Govee H5198:** impossible jumps are ignored, and a thermometer is remembered only after a steady minute.
- **Community averages** that don't look like Open Pitmaster's own are dropped before they reach the AI.

**Home Assistant**
- **Notification buttons:** they carry a one-time code. A forged button event from another phone or a webhook does
  nothing. **Buttons on notifications sent before this update won't work.**
- **AI plans:** checked before loading.
  - Pit or hold above *Smoker AI max pit* (400°F) is refused, and so are links or anything that isn't a program.
  - The notification shows the program itself.
  - Your notes, scanned labels and community data go to the AI marked as data, shortened.
- **ESPHome events:** smoker events are accepted only from the smoker controller.
  - Cook summaries are checked field by field.
  - Notification buttons can't be injected through a tag.
- **Label photos:** stripped of location (EXIF) before saving or sending to the AI. One scan at a time per user, with
  a size cap.
- **Grill photo:**
  - Only an administrator can upload it.
  - It's served at an unguessable address that changes with each upload.
  - Huge images are refused.
- **Voice:** "start a cook" now asks you to confirm ("confirm smoker start").
- **Smaller fixes:**
  - Calendar notifications show the event name without links.
  - Sharing a declined cook needs an administrator.
  - The page passes data through data- attributes, not inline handlers.

**Releases**
- **The publishing job:** the published firmware is built in a job with ESPHome only; the test tools run separately,
  pinned.
- **Attestations:** made in their own default-branch job. Releases are attested before they're published, and never
  cancelled midway.
- **Privacy check:** it runs the default branch's copy of itself.
- **The web installer** loads nothing from other sites and has a strict CSP.

## [0.2.46] - 2026-11-23

- **Boost (both dashboards, next to the pit target), standing in for the panel's turbo button:**
  - Tested on a real 980: no remote command turns turbo on (fan speed 0x06 with eight values, and ids 0x07-0x1F).
  - So Boost raises the grill's pit target by 100°F (at most 700°F), which runs the fan hard. It puts the target back
    when the pit reaches it, after 15 minutes, when you press *Stop boost*, or after a restart.
  - The pit target still shows your real target throughout, and a running cook program isn't disturbed.
  - Changing the target (here, on the panel or by the program) ends the boost and keeps the new target.
  - New entities: *Boost* (switch) and *Boost status*.
- A *Turbo (panel)* chip shows when turbo is on at the grill.

## [0.2.45] - 2026-11-23

- **Protocol research tools (off by default), to look for a remote turbo command:**
  - A *Command tests* switch (in configuration). It turns itself off after 30 minutes.
  - An action, `test_command` (command id, value), that sends one `FF <id> <hi> <lo>` command to the grill.
    It only works while the switch is on, sends at most one command every 15 s, and never sends 0x01, 0x04 or 0x05.
  - A *Command test* sensor showing what was sent or why it was refused.
- Confirmed on a real Gravity 980: the panel's turbo button sets byte 15 bit 4 of the status frame, and nothing else
  changes.

## [0.2.44] - 2026-11-23

- **Set the pit target from the top of the page** (both dashboards): − and + buttons, or type a temperature and press
  Set (or Enter). The buttons are greyed out while the app can't control the grill.
- **The section bar goes where you click:**
  - The chip you click is the one highlighted. It used to highlight the next section when the one you chose was short
    (Chart highlighted Journal).
  - Sections near the end of the page now scroll right up to the bar.
- **Keys stay out of the code:** the release check now also catches Telegram bot tokens, alongside Google, Claude and
  OpenAI keys. A test confirms the controller never sends a stored AI key back and never writes it to its log.

## [0.2.43] - 2026-11-23

- **The calendar event's end is the serve-by time:** block out the whole cook in your calendar (say a 12-hour
  "Brisket cook") and the smoker plans to have it ready when the event ends. An event that has already started still
  counts until it ends; all-day events are ignored. The notification shows the event's start and end.

## [0.2.42] - 2026-11-23

- **No more "unknown entity" warnings for a calendar or to-do list you haven't chosen** (Spook/Repairs flagged
  `calendar.your_calendar`). The package now names the calendar in a template, so an unchosen calendar is simply skipped,
  and only adds charcoal and maintenance jobs to the to-do list when that list exists.

## [0.2.41] - 2026-11-23

- **A simple way to set up a cook** (both dashboards, in *Edit the program*):
  - Pick what's cooking and the form fills in a typical cook: smoke at one temperature until the meat reaches a
    temperature, wrap (butcher paper, foil or not at all), then finish at another temperature until it's done, then
    keep it warm or turn the grill off.
  - Built in: pork shoulder, brisket, ribs (3-2-1 by time, or to temperature), whole chicken, chicken pieces, turkey,
    reverse-sear steak and roast (smoke low, then sear hot), salmon, sausages and pork loin. Change any number.
  - You get a notification when it's time to wrap (or unwrap the ribs, or sear).
  - *Load this cook* writes an ordinary program; *Advanced: edit the steps* opens the step editor on it.
  - Choosing one of the controller's presets still shows its steps.

## [0.2.40] - 2026-11-23

- **The temperature graph shows the plan beside the actual:**
  - When a cook's first sound prediction comes in, the controller records the predicted food temperature curve as
    the cook's plan (the new *Food N plan* entities).
  - Both dashboards draw it dotted next to the real temperature, running on into the future.
  - Each food card says how far ahead or behind plan you are ("40 min behind plan").
- **Plan with AI shows its result on the page** (Home Assistant's Smoker page):
  - The button says *Planning…* while the AI works.
  - Then the Plan card shows the AI's explanation, the program the controller loaded and a *Start the program*
    button, or why the controller refused it.
  - It used to go only to a phone notification.

## [0.2.39] - 2026-11-23

Ten new features:
1. **More notification buttons:** "Pulled it" alerts also offer *Not yet: hold it warm*; charcoal alerts offer *I
   topped it up*. Alerts sent straight to your phone (ntfy, Pushover, Telegram) open the controller's page at the
   right section when tapped.
2. **The fire may be dying:** a warning before "Fire may be out", when the fan has been blowing for 8 of the last 10
   minutes and the pit is still 10°F under target and falling. It says to top up if the charcoal estimate is low, and
   otherwise to check the chute and the ash.
3. **This cook vs your best:** during a cook, the Temperatures section compares your food probe with your
   best-rated earlier cook of the same cut. It says how far ahead or behind you are at the same point.
4. **Serve time from your calendar:** an event in the next two days with "BBQ", "brisket", "smoker", "ribs"... in
   its title sets the serve-by time, unless you've set one by hand. Choose the calendar with the action
   `smoker.install_package` (field *Calendar*).
5. **The controller remembers your thermometer and grill:**
   - The Govee H5198 is pinned once found, so a neighbour's isn't picked up. *Forget the thermometer* clears it.
   - The grill's Bluetooth address is remembered across restarts. Another device now has to wait a minute after
     your grill was last heard (not 10 s) before it can take over, and *Forget the grill* clears it.
   - The grill can change address when it's switched off and on, so the controller can't lock it to one address
     outright.
6. **Charcoal stock and cost:**
   - Set the bag size and price (Setup → Supplies and maintenance). Charcoal burned comes off the stock, and
     *Bought a bag* adds one.
   - The Charcoal card shows the kg, cost and kg/h of your last cook.
   - Below one bag, "Charcoal for the smoker" goes on your to-do list.
7. **One-page cook summary:** *Summary* on a journal entry shows the cut, timings, stall, pit, outside temperature,
   rating, notes and its temperature chart. You can print it, save it as a PDF or share it.
8. **Open Pitmaster has a public page:** https://api.open-pitmaster.workers.dev/ shows the shared averages by cut,
   weight, pit and weather.
9. **More voice commands:** "the brisket is wrapped", "push dinner back an hour" (or "bring it forward"), "when
   should I light the grill".
10. **Maintenance reminders:** burn hours count while a cook is on. The ash pan (12 h), grease tray (30 h), and
    gasket and fan (100 h) send a reminder and go on your to-do list. Mark each done on the Setup page.

`smoker.install_package` takes two new optional fields: *Calendar* and *To-do list* (default `todo.shopping_list`).

## [0.2.38] - 2026-11-23

Fixes from a second independent review:
- **Security: the controller's buttons and settings needed the PIN only for some kinds of request.** ESPHome also
  carries out actions sent as a plain link (GET), so any website you visited could press "Clear the device page
  PIN", change the pit target or start an update. Those now need the PIN too, and are refused from other websites.
  Requests that don't name the controller (its IP address or `.local` name) are refused, which stops a website
  pretending to be it (DNS rebinding).
- **Crash fix:** big pieces of data (a label photo, AI answers, the chart's history) now use the controller's 8 MB
  of PSRAM instead of the small internal memory Wi-Fi and Bluetooth need. A label photo could have restarted it.
  Large uploads need a PIN to be set.
- **The grill's hostname is looked up on a task of its own:** a slow or failing lookup (a few seconds) could have
  tripped the main loop's watchdog and restarted the controller.
- **Programs:** one too long to save whole is refused (it used to resume cut short after a restart); an AI notify
  text with a quote in it no longer breaks *Load as program*; a paused program no longer rewrites the flash every
  5 minutes.
- **Setup page:** tapping its title no longer folds it away; leaving it through another section doesn't leave an
  extra step in the browser's history; focus moves with it (keyboard and screen readers); on Home Assistant's page
  the Setup cards were inside the Setup heading, and the section bar always highlighted Setup.
- **Smaller:** the PIN panel behaves as a proper dialog (Escape, Tab stays inside, focus returns); "in Setup" hints
  open Setup; dark mode's highlighted buttons are readable; the grill's Bluetooth address is still picked up after 25
  days unseen; fuel values that aren't numbers are ignored; the AI model name is checked on every path.
- **Home Assistant:** after the integration is reloaded its journal and community sensors come back; *Remove my shared
  cooks* also removes a cook whose upload reply was lost; the automatic package update only reloads automations while
  Home Assistant is starting (a reload at run time would stop your other running automations).
- Note on the package fingerprint added in 0.2.37: a package installed before 0.2.37 had no fingerprint, so if you'd
  edited it by hand, that one update replaced it (the old file is kept as a backup next to it).

## [0.2.37] - 2026-11-23

**Setup has a page of its own** on both dashboards: the section bar's Setup button opens it, with *Back to the cook*
(the phone's back gesture works too). The main page is just the cook. On the controller's page, a change while it's
locked asks for the PIN right there instead of sending you to Setup.

Fixes from two independent reviews of the whole project:
- **Security:**
  - The controller no longer accepts firmware uploads from the local network (anyone on the Wi-Fi could have
    flashed it and skipped the PIN). Updates come from the signed release only. Building it yourself in the ESPHome
    dashboard: add a password-protected OTA (docs/install.md).
  - Other websites can't send changes to the controller (cross-site requests are refused).
  - Big uploads only from an unlocked page; journal notes are only shown to an unlocked page; keys are never in the
    HTTP client's logs.
- **PIN:** a controller up for more than 25 days would have refused every PIN ("too many wrong PINs"). Changing the
  PIN hashes it once less, and the hashing pauses regularly so it never holds anything else up.
- **Reliability:** the AI questions read the cook's state on the right task; a request that can't start still
  reports back (the page used to wait forever); no Wi-Fi reconnect during a cook; the last two timer wrap-rounds
  fixed; an idle controller no longer writes to flash every 5 minutes.
- **Home Assistant:**
  - The automatic package update never overwrites a package you've edited (you get a notification instead).
  - The AI advisor stays off after a restart if you turned it off (it used to switch itself back on).
  - Open Pitmaster: one upload per cook (a star then a tag could upload two, one of them impossible to remove);
    turning sharing back on doesn't share the cooks from while it was off; automatic sharing waits 10 minutes
    after your last change so your feedback goes together.
  - The grill photo is stored without its location data. A switched-off controller isn't reloaded every half hour.
- **Releases:** the privacy check now has to pass before anything is published.

## [0.2.36] - 2026-11-23

- **Plan with AI on the controller makes programs the grill can run.** The AI is told the pit's range again (it
  had planned a 150°F keep-warm hold, which the controller refused, keeping the old program). Any step outside
  the range is now moved into it before you see the program, with a note saying what changed. **Load as program**
  says whether the controller took it, rather than always "loaded".
- **The controller's page loads without a white flash or jumping:** its colours apply before the script runs,
  and the starting layout no longer changes once the controller answers (Setup starts folded, the chart open, the
  Right now strip stays).
- **AI:** the default Gemini model is `gemini-flash-lite-latest`.

## [0.2.35] - 2026-11-23

- **Fix: the controller restarted itself after a short drop in Home Assistant's connection** (from 0.2.32). The
  "restart once after an hour without Home Assistant" timer could misread a few milliseconds as hours. The same
  slip could also fetch the weather, record the chart, check the shared averages or ask the AI one extra time.

## [0.2.34] - 2026-11-23

- **Fix: the controller restarted when its page was used, and kept asking for the PIN.** Since 0.2.31 the controller
  crashed ("exception/panic") when you entered the PIN or used its page, and each restart forgot that your browser
  was unlocked. (The 0.2.31 update failing to stick was the same crash, not the memory at boot that 0.2.33 blamed.)
  - The page's requests now run on a task of their own, on the controller's second processor core: the web server's
    task has too little room, and checking a PIN takes a second or two that must never stall the controller's main
    work.
  - The PIN has its own lock, so the main loop never waits on it.
- **Unlocking survives a restart:** unlocked browsers are saved on the controller, so an update or a restart no
  longer locks them out.

Running without Home Assistant, part 4:
- **Get started** on the controller's page: a checklist for a controller used on its own: PIN, find the grill,
  alerts on your phone (ntfy in one tap: a random topic, shown once to subscribe), time zone and weather, and the AI
  (optional). It hides once done or dismissed; `?start` shows it again.
- **The firmware is split** into `base.yaml` (everything that works without Home Assistant) and
  `home-assistant.yaml` (the API, Home Assistant's clock, weather and thermometers, the Bluetooth proxy, the events).
  `core.yaml` includes both, so the prebuilt firmware and existing ESPHome dashboard builds behave as before.
  - A build with no Home Assistant at all (`tests/configs/no-ha.yaml`) is checked on every release.
- docs/standalone.md: getting started without Home Assistant.
- docs/install.md: the ESPHome dashboard recipe lists the `standalone` component (it was missing).

## [0.2.33] - 2026-11-23

- **Fix: the controller's update to 0.2.31/0.2.32 didn't stick.** The new firmware started a second background task
  for the AI at boot, taking internal memory that Bluetooth and Wi-Fi need. The controller restarted and fell back to
  the old firmware. The AI's task now starts only when an AI question is first asked.
- **New diagnostics:** *Last restart reason* and *Free memory*, so a crash or low memory shows in Home Assistant.
- **One layout for both dashboards** (Home Assistant's Smoker page and the controller's own page):
  - the same sections in the same order: planning first while nothing's cooking, the cook first during one;
  - every section folds from its heading, and each browser remembers what you folded;
  - Setup folds to a one-line summary once it's set up; the journal folds during a cook;
  - the cook program editor stays folded once a program is loaded ("Edit the program" opens it);
  - cards fill their row, and the "Right now" tiles no longer leave a grey gap;
  - the controller's page gains the "Right now" strip, and Charcoal and Plan are separate sections, as in
    Home Assistant. Plan with AI and What's cooking sit in Plan.

## [0.2.32] - 2026-11-23

- **Home Assistant reconnects to a controller it has lost.** Home Assistant's link to the controller can get stuck:
  the controller keeps running (its page answers) while everything in Home Assistant shows unavailable.
  - The integration now checks every minute. After 3 minutes like that, if the controller's page answers, it
    reloads the connection. If the page doesn't answer either, it tries once after 15 minutes.
  - The controller helps from its side: once Home Assistant has used it, 10 minutes without Home Assistant makes it
    reconnect its Wi-Fi (every 30 minutes while it lasts). After an hour it restarts once, never during a cook, and
    not again until Home Assistant is back. A controller used without Home Assistant is left alone.
- **The AI only works on a cook.** It asks nothing unless a cook is underway or planned (a serve-by time within the
  next two days), on the controller and in Home Assistant:
  - the AI pitmaster's *Ask now* is greyed out on an idle grill;
  - the plan refresh no longer fires when you edit a probe's cut with nothing on;
  - Plan with AI and label reading are still there when you're planning.
  - The controller also caps AI questions at 40 a day, so a fault can't run up a bill.

## [0.2.31] - 2026-11-23

Running without Home Assistant, part 3: the AI on the controller, with your own key (docs/standalone.md).
- **Providers:** Google Gemini, Anthropic Claude or OpenAI (Setup → AI). The key is write-only, like the
  notification keys; **Test the key** checks it. The model can be changed (defaults: gemini-2.5-flash,
  claude-opus-5-5, gpt-4.1-mini).
- **AI pitmaster:** a second opinion on the live cook (pit, probes, weather, this grill's past cooks, your journal and
  the Open Pitmaster averages), on request or every 30 minutes during a cook (off unless turned on).
- **Plan with AI:** describe the cook; it suggests when to light up and the steps, and writes a cook program you can
  load with one tap.
- **What's cooking:** take or choose a photo of the package label; it reads the cut and weight, and sets them on a
  Food slot.
- AI calls run in their own lane, so a slow answer never holds up a notification.
- Fix: the controller page's "Send them" menu (where notifications go) now saves.

## [0.2.30] - 2026-11-23

The controller's page, tidied (it was all over the place on a wide screen):
- **Cards fill their row:** a lone card no longer sits narrow next to empty space. The pit and program share a row
  (the program wider); Charcoal and the Plan sit side by side; the journal is beside its Open Pitmaster card.
- **Setup in three pairs:** Grill connection (link, probe sources), Phone and weather (notifications, weather and
  time), This controller (PIN, controller details).
- **Smaller fixes:** the link status reads as a sentence; the empty chart is compact; drop-downs fit their cards; the
  notes box fills its row on a phone.

## [0.2.29] - 2026-11-23

Running without Home Assistant, part 2: the controller's own page catches up (docs/standalone.md).
- **Temperatures chart** (3/6/12/24 h): the pit, the pit target and every food probe, recorded on the controller.
- **Charcoal log** from the controller's page (started at, it's at, topped up, added, finished with).
- **Plan:** serve-by time and rest. *Light the grill by* comes from the controller's estimate, with a notification
  when it's time.
- **Cook journal** on the controller: the last 24 cooks, with stars, "How was it?" tags, notes and removal.
- **Open Pitmaster from the controller:** opt-in anonymous sharing (asks per cook, or automatic once rated),
  removal with keys kept on the controller, anonymised download, and the shared averages shown in the Plan card.

## [0.2.28] - 2026-11-23

- The integration has its own icon in Home Assistant (Settings → Devices & services, and wherever the integration is
  listed): the Smoker mark, shipped in `custom_components/smoker/brand/`.
- The favicon is redrawn: a balanced flame centred on the tile (the old one leaned and sat off-centre). It's the same
  on the dashboard, the controller's page and the web installer.

## [0.2.27] - 2026-11-23

Running without Home Assistant, part 1 (docs/standalone.md):
- **A PIN for the device page.** Once set, every change through the page needs it; readings stay open.
  - PBKDF2-SHA256 (20,000 rounds, salted).
  - Lockout after 5 wrong PINs, then 12-hour sessions per browser.
  - Forgotten: hold BOOT for 10 s, or "Clear the device page PIN" in Home Assistant.
- **Notifications straight to your phone** through ntfy, Pushover or Telegram. Automatic (via Home Assistant when
  it's there, direct when it isn't), Home Assistant only, direct only, or both. Critical alarms always go direct too.
  Keys are write-only on the controller; a test button checks them. The old "ntfy topic" setting moves into the key
  store automatically.
- **Weather on the controller:** set your area on the device page and it fetches the conditions and the 24-hour
  forecast from Open-Meteo (no account). This feeds the predictions; it wins over Home Assistant's weather while set.
- **Internet time** alongside Home Assistant's. The device page sends your phone's time zone (offsets and
  daylight-saving rules).
- New diagnostic sensor *Outdoor temperature*.

## [0.2.26] - 2026-11-23

- Sharing is now **Open Pitmaster**: the service is at `api.open-pitmaster.workers.dev`, and the dataset, the service's
  code and the format live in their own repository (github.com/Legal-Copy7045/open-pitmaster). This repo keeps the
  integration.
- **"How was it?"** on every journal entry: juicy, tender, dry, tough, undercooked, just right, overcooked, great or
  soft bark, smoke, fat rendered or not. Stored with the cook, given to the AI pitmaster with your notes and stars,
  and part of a shared record.
- Sharing waits for feedback: a cook is offered once it's rated or tagged, or 12 h after it ended. Automatic sharing
  covers only cooks that end after it was turned on.
- The averages include what cooks said ("juicy 60%") and the average stars.

## [0.2.25] - 2026-11-23

- **Share cooks, anonymously, if you want to** (Setup → Share cooks; **off unless you turn it on**). Finished cooks
  can go into an open dataset (CC0) that improves everyone's predictions and AI advice. Only rounded numbers are
  shared: cut, weight, pit, stall, total time, outside temperature band, season and rating. Never dates, place, notes,
  photos or names, and no id that links two cooks. The journal asks after each cook and shows exactly what's sent;
  *Share automatically* skips the question; *Remove my shared cooks* deletes them; *Download my cooks (anonymised)*
  lets you look first. Details: docs/sharing.md.
- **Community averages for everyone** (sharing or not): typical times by cut, weight, pit and weather from all shared
  cooks, as `sensor.smoker_community`, included in the AI pitmaster's prompts.
- New in the repo: the receiving service (`sharing/worker`, a Cloudflare Worker) and the nightly dataset build
  (`community-data` branch).

## [0.2.24] - 2026-11-22

Dashboard order, reviewed (the phone page is about 1,000 px shorter):
- During a cook: Now · Food · Pit & program · Charcoal · Chart · **AI pitmaster** · Plan · Journal · Setup. With
  nothing cooking, **Plan the next cook comes first** (the section bar follows).
- Food times are shown once (the picture's Coming up and the Food cards), no longer also as Right now tiles; Right now
  keeps charcoal, cook time and outside, with no empty tile.
- The AI's finish estimate and its recommendations are together in one AI pitmaster section, below the chart, instead
  of the recommendations sitting above the food.
- The program editor folds away while a program runs (Edit the program opens it); open while idle.
- Learning moved to the Cook journal; Setup no longer repeats the grill link (Controller) or the grill's Wi-Fi (now a
  note under its signal).

## [0.2.23] - 2026-11-22

- When the grill is on Wi-Fi **and** Bluetooth, both pages say so at the top ("Grill connected · Wi-Fi + Bluetooth",
  both icons; Bluetooth stands by if Wi-Fi drops), and in the Connection card and on the grill picture. New sensors
  *Grill on Wi-Fi* and *Grill on Bluetooth* report each link on its own; Grill link status says "Connected over Wi-Fi
  and Bluetooth".

## [0.2.22] - 2026-11-22

- Fix: *What's cooking → Read the labels* failed with "No entity_id provided and no preferred entity set" when Home
  Assistant has no default AI task (Settings → AI). It now picks the AI itself: the one the Smoker package was installed
  with, else Home Assistant's default, else any AI task that can read photos, and says plainly if there's none.
- *What's cooking* has separate **Take a photo** and **Choose photos** buttons (the single picker opened the camera
  even though it said "Choose files"). Photos from both add up (up to 6), show as thumbnails you can remove, then
  **Read the labels**.
- Error messages wrap instead of running off the screen, sit above the phone's home bar, and stay 10 s (tap to close).

## [0.2.21] - 2026-11-22

- **Signal strength to the grill.** New *Grill Bluetooth signal* (the controller's link to the grill, read every 30 s;
  while not connected, how strongly its advertisements arrive) and *Grill Wi-Fi signal* (the grill's own Wi-Fi, as the
  grill reports it; **Check** asks it). Both pages show them in the Connection card in dBm with a word (strong, good,
  weak, very weak); the status strip warns about a weak Bluetooth link.
- **Fix: finding a grill that was just switched on.** While it starts up the grill can advertise as "BLEWIFI APP"
  instead of "Gravity980-…"; the controller only knew the second name. It now also recognises "BLEWIFI APP" and the
  grill's service (0xAAAA) in the advertisement.

## [0.2.20] - 2026-11-22

- Release numbers on show: a new *Release* sensor on the controller; the dashboard's Diagnostics shows the controller
  and integration releases (and the footer), the device page shows its release.
- The Wi-Fi signal is labelled for what it is: the controller's own connection to your router, not the grill's (it
  reads even with the grill off). Diagnostics also shows the link status in words, uptime as days/hours and the
  ESPHome version it was built with.

## [0.2.19] - 2026-11-22

- **The package now updates itself with the integration.** After a HACS update, a package that
  `smoker.install_package` installed is brought up to date on start-up (same phone, AI task and weather; the previous
  file kept as a backup, last three) and reloaded, so there's no second restart. A "Smoker package" notification says
  when it happened. A package copied in by hand is left alone.

## [0.2.18] - 2026-11-22

- **The integration installs the Home Assistant package for you**: action `smoker.install_package` (admin) writes
  `/config/packages/smoker.yaml` from the copy bundled with the integration, filled in with your phone, AI task and
  weather. Run it again after an update to bring the package up to date (your choices are kept; the old file is kept
  as a backup). Restart Home Assistant afterwards.

## [0.2.17] - 2026-11-22

- Fix: without the Smoker package for Home Assistant installed, the AI pitmaster switch said "not allowed: .toggle".
  The AI, planning, serve-by, rest timer, recommendations and Home Assistant probe picks now say they need the
  package (with a link to how to add it) instead of offering controls with nothing behind them.

## [0.2.16] - 2026-11-22

- **The bridge recovers from a lost grill link by itself, and says what it's doing.** New *Grill link status*
  (shown on both pages when the grill isn't connected): connected, looking for the grill, connecting, reconnecting and
  why the last link ended. Recovery steps, in order:
  - a Bluetooth link with no status is dropped and made again;
  - a connection attempt stuck for 45 s is cancelled, or Bluetooth is restarted if it can't be;
  - the grill in range but no link for 3 min: Bluetooth is restarted;
  - still none 5 min later: the bridge restarts itself (at most 3 times in a row; a running program comes back paused
    and the grill holds its own pit target meanwhile);
  - no Bluetooth advertisements from anything for 5 min (scanner stuck): Bluetooth is restarted.
  - Turning *Bridge enabled* off (for the grill's own app) stops all of this.
- Wi-Fi drops were already retried every 10 s; their reason now shows in the status too.

## [0.2.15] - 2026-11-22

- **Fix: the bridge now finds a grill that is switched on after it.** A grill that has only just started can accept the
  Bluetooth connection before it's ready (no services yet, or no status), and the bridge used to sit on that dead link
  until it was rebooted. Now it drops a link that hasn't delivered status within 20 s (or whose status stops) and
  connects again, and if the grill comes back on a different Bluetooth address it follows it by name.

## [0.2.14] - 2026-11-22

- Grill photo uploads are shrunk in the browser first: 960 px across (the page never shows it wider than 640 px), WebP
  (keeps transparency) or JPEG, so a phone photo goes from several MB to around 100 kB.

## [0.2.13] - 2026-11-22

- **Upload your grill photo from the dashboard** (Setup → Grill photo; on a phone, camera or library): the integration
  stores it and serves it to both dashboards and the controller's own page, which all pin the live readings on it.
  No more saving files into Home Assistant's `www` folder (that still works). Replace or remove it there too.
- **Fix:** "All good" no longer shows next to "Grill not connected".

## [0.2.12] - 2026-11-22

- **Branding, revisited:** the mark is redrawn on exact geometry (the smoker centred on its tile, the flame centred in
  the barrel, no smoke wisp); every line icon is centred on its box; icons sit centred with their text in the section
  bars and headings. `tools/brand_sync.py` keeps the pages in step with `brand/` (checked in CI).

## [0.2.11] - 2026-11-22

- **Branding:** an original mark (a gravity smoker with an ember flame), favicon and app icons (`brand/`), and a set of
  line icons used across the dashboard, the controller's own page and the installer (section bar, headings, status
  strip). See [brand/README.md](brand/README.md).

## [0.2.10] - 2026-11-22

- The Smoker page can also live in the **home-dashboards** project (one copy, owned here: see
  [docs/home-dashboards.md](docs/home-dashboards.md)): its section bar sits under that project's site bar, and it works
  without the Smoker integration's API (journal and package scans say they need it; the grill photo is found at
  `/local/smoker/grill.*` directly and passed on to the controller).

## [0.2.9] - 2026-11-22

- **Cook program step editor** on the dashboard and the controller's own page: each stage is "Set pit to N° until …"
  (probe reaches / drops to, pit reaches, probe done, time in step, clock time, stall start/end; "held for" minutes;
  several conditions = "or"), with a notification per stage; add, remove and reorder stages; presets load into it;
  the program text is still there ("Edit as text").
- **Set up the grill's Wi-Fi over Bluetooth** (what the Char-Griller app does): *Join saved network* (the app sends
  this on every connect; the controller didn't), *Scan*, and a new network and password from the controller's own
  page. The password goes to the controller only (never to Home Assistant) and isn't stored.
- **Control over Bluetooth** is confirmed working on a Gravity 980: no longer marked experimental (the switch is now
  named "Control over Bluetooth"; the old "(experimental)" entity can be deleted in Home Assistant).

## [0.2.8] - 2026-11-22

- The controller's own page shows **your grill photo** too: new *Grill photo URL* setting, filled in automatically by
  the Smoker dashboard when it finds the photo in Home Assistant (`/config/www/smoker/grill.png`). Unreachable or
  empty: the drawing.
- **Fix:** "Running cold/hot" only during a cook (it showed with the grill idle).
- **Fix:** the hopper's "no level" label no longer runs into the ash box; the status strip's explanation sits on its
  own line on phones.

## [0.2.7] - 2026-11-22

- **Restart** button for the controller (device page in Home Assistant, the dashboard's Setup → Controller, and the
  controller's own page; the last two ask for a second tap). Settings and learned cooks are kept.

## [0.2.6] - 2026-11-22

### Firmware
- **The controller's own web page** (`http://gravity980.local`) in the home-dashboards look, replacing ESPHome's stock
  page: a status strip first (connected, controlling, anything wrong), the grill with live readings, food, pit target
  and program, charcoal, and setup (Bluetooth control, bridge, grill IP and Wi-Fi report, probe sources). Built into
  the firmware: works without Home Assistant or the internet. The stock page is at `/?classic`.

### Home Assistant dashboard
- Rebuilt in the home-dashboards layout: a status strip first, the grill (your own photo from
  `/config/www/smoker/grill.png`, or a drawing) with each reading where it is on the grill, a sticky section bar, and
  sections that follow the grill: food, pit & program, charcoal, then chart, plan, journal and setup.
- Food cards lead with temperature, finish, target, pull and rest; the rest folds away (and stays open while it
  updates). A Setup section gathers the connection, probe sources and controller details.

## [0.2.5] - 2026-11-22

- **Grill Wi-Fi** diagnostic entity: what the grill reports about its own Wi-Fi over Bluetooth (network, IP, signal,
  status code), to find out why it won't join.
- With *Grill IP address* empty, the bridge uses the IP the grill reports for the Wi-Fi link.
- Docs: a "still won't join" table in first-run.

## [0.2.4] - 2026-11-22

- **Control over Bluetooth** is on by default: the app controls the grill over Bluetooth when its Wi-Fi isn't
  connected (it often won't join UniFi networks). Still experimental until a cook confirms the grill takes it.
- Dashboard: the pit card shows how the app reaches the grill (Wi-Fi, Bluetooth, or read-only and why), with the
  Bluetooth control switch.
- Docs: UniFi/mesh settings that stop the grill joining Wi-Fi.

## [0.2.3] - 2026-11-22

### Firmware
- **Control over Bluetooth (experimental)** switch (device page, Configuration, off by default): pit and food target
  changes over Bluetooth when the grill's Wi-Fi isn't available. Not yet confirmed on a 980; every write is checked
  against what the grill reports back. See [first run](docs/first-run.md#control-over-bluetooth).

## [0.2.2] - 2026-11-22

### Firmware
- **Fix:** the H5198 reader used the wrong broadcast format (from a community decoder) and would never have read a
  real unit. It now follows Home Assistant's own Govee decoder (govee-ble), checked against a real H5198's
  broadcasts: recognised by its service id, all packet variants, unplugged probes. Each probe's alarm on the
  thermometer is available too (*H5198 probe N alarm*).
- Optional **wired probes**: up to four NTC meat probes on the controller itself through an ADS1115
  (`firmware/wired-probes.yaml`); every slot can pick *Wired probe 1-4*. They work without Home Assistant, like the
  grill's probes and the H5198 read directly.
- Food 3-6 default to the *Home Assistant* source. A thermometer's own alarm (H5198 direct, or the matching Home
  Assistant alarm entity) becomes the slot's target when it's changed there; nothing is written back to it.

### Home Assistant
- Pick each slot's Home Assistant thermometer from a list on the dashboard (*Probe sources*). Slots 3-6 default to
  the Govee H5198's probes 1-4 (`sensor.meat_thermometer_temperature_probe_N`).
- A Govee probe reporting exactly 0 °C (unplugged) counts as no reading; the probe's alarm becomes the slot target.

## [0.2.1] - 2026-11-22

Second review round, and **Experimental** labels on estimates that need history
([what's experimental](docs/features-0.2.md#whats-experimental)).

### Firmware
- **Fix:** the controller no longer reboots after 15 minutes without Home Assistant or Wi-Fi (it kept cooking and
  alerting through ntfy, then restarted and lost the cook's estimates).
- **Fix:** probe targets: quick changes no longer bounce back, a target the idle grill ignored is re-sent, targets set
  on the grill's panel are taken as they are (the slot range is now the grill's), and two slots on the same grill
  probe don't overwrite each other. The charcoal gauge ignores a warm but unlit grill.
- The H5198 reader only picks a device once it has sent real probe readings.
- **Experimental** labels: finish times (until 3 similar cooks), pull-at (until 2 measured rests) and the charcoal
  gauge (until about one logged cook) say so in their estimate basis and alerts until there's enough history; new
  *Charcoal estimate basis* entity.

### Home Assistant
- Dashboard: an **Experimental** chip on estimates without enough history yet, the AI estimate and
  recommendations, and H5198 readings ([what's experimental](docs/features-0.2.md#whats-experimental)).
- Voice finish-time answers say when the estimate is still experimental.
- Package scan photos are kept in `media/smoker_scans`; only the integration's own files there are tidied up.
- Weather entity lines are marked **EDIT** in the package.

### Docs
- ESPHome dashboard snippet includes `govee_h5198` and needs ESPHome 2026.11 or newer; which USB port to use; adding
  the device by hand when it isn't discovered; `.local` names on phones.

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
  bad weights and ratings return a message instead of an error; photo names can't collide; unused scan photos are
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
