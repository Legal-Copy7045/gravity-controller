# Sharing cooks with Open Pitmaster (anonymous, opt-in)

The Smoker integration can add your finished cooks to **[Open Pitmaster](https://github.com/Legal-Copy7045/open-pitmaster)**,
an open, anonymous dataset that improves everyone's predictions and AI pitmaster. It is **off until you turn it on**
(Smoker dashboard → Setup → Share cooks). You can turn it off, or remove everything you've shared, at any time.

## What's shared

One record per cook, and only rounded numbers and how it turned out:
- the cut, the weight (to ½ lb), the pit temperature (to 5 °F) and the probe target;
- the stall and total time (to 0.1 h; durations, never clock times), and whether it was wrapped;
- a 5 °F band of the outside temperature, and the season instead of a date;
- your stars and your "How was it?" tags (juicy, tender, dry, tough, undercooked, just right, overcooked, great bark,
  soft bark, good smoke, too smoky, too little smoke, fat rendered, fat not rendered);
- the grill model and the software release;
- a new random id per cook.

**Never shared:**
- dates or times;
- where you are (your location or IP address);
- your notes, photos or scanned labels;
- names;
- Home Assistant or device identifiers;
- anything that links two cooks together.

The full field list, and how the service treats each cook, are in Open Pitmaster's
[PRIVACY.md](https://github.com/Legal-Copy7045/open-pitmaster/blob/main/PRIVACY.md). The service refuses any record
that doesn't match it exactly.

## When a cook is shared

- A cook is ready to share once you've **rated it or ticked "How was it?"** in the journal, or 12 hours after it
  ended. That way the shared record says how the food turned out.
- The journal then asks **"Share this cook?"** and shows exactly what's sent. You can share it or choose *Not this
  one*.
- With **Share automatically**, ready cooks go without asking. That covers only cooks that end after you turn it on,
  never your history.
- The service holds every cook back for a random 1-3 days before it joins the public data.

## Removing what you've shared

**Remove my shared cooks** deletes every cook shared from your Home Assistant. It uses deletion keys that never leave
your Home Assistant otherwise. **Download my cooks (anonymised)** gives you every cook as it would be shared, so you
can look first.

## The averages (for everyone)

Twice a day the integration downloads Open Pitmaster's `aggregates.json`, whether or not you share. That file holds
typical times and how cooks turned out, by cut, weight, pit and weather, for groups of 3 or more cooks. The
integration publishes them as `sensor.smoker_community`, and the AI pitmaster's prompts include them as "shared cooks
from other Gravity 980 owners".

The service and the dataset live in [github.com/Legal-Copy7045/open-pitmaster](https://github.com/Legal-Copy7045/open-pitmaster).
To use your own service, change `SHARE_URL` / `AGGREGATES_URL` in `custom_components/smoker/sharing.py`.
