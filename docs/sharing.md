# Sharing cooks (anonymous, opt-in)

The Smoker integration can add your finished cooks to an **open, anonymous dataset** that everyone's predictions and
AI pitmaster draw on. It is **off until you turn it on** (Smoker dashboard → Setup → Share cooks), and you can turn it
off, or remove everything you've shared, at any time.

## What's shared

One record per finished cook, and only this:

| Field | Example | How it's made non-identifying |
|---|---|---|
| `cut` | Pork shoulder | One of the dashboard's protein profiles |
| `weight_lb` | 8.5 | Rounded to ½ lb; 25 lb and over shown as 25 |
| `pit_f`, `target_f` | 250, 203 | Pit to 5 °F, the probe target to 1 °F |
| `stall_h`, `total_h` | 3.1, 11.6 | Hours, to 0.1 h: durations, never clock times |
| `wrapped` | true | Yes / no / unknown |
| `outside_f` | 35 | A 5 °F band (35 means 35–40 °F); below −10 °F shown as −10 |
| `season` | autumn | Instead of a date (southern hemisphere handled) |
| `rating` | 4 | Your stars, if you gave any |
| `grill`, `release`, `v` | gravity980, 0.2.25, 1 | The grill model, the software release, the format version |
| `id` | 32 random hex digits | New for every cook: it links to nothing, not even your other cooks |

**Never shared:**
- dates or times;
- where you are (your location, weather station or IP address);
- your journal notes, package photos or scanned labels;
- names (yours, your probes' or your devices');
- Home Assistant entity ids, Bluetooth or Wi-Fi details;
- anything that links two cooks together.

The dashboard shows each record before it's sent ("Exactly what's sent"). **Download my cooks (anonymised)** gives
you all of them as a file, so you can check them first.

## How it travels

1. When a cook ends, the journal asks *Share this cook?* (or, with **Share automatically**, shares it straight away).
2. Your Home Assistant sends the record to a small receiving service (a Cloudflare Worker,
   [`sharing/worker`](../sharing/worker/src/index.js)):
   - it checks every field against the table above and refuses anything else, so a mistake can't leak something extra;
   - it stores the record with a release time only. Your IP address, the time it arrived and the request headers are
     not stored or logged. Cloudflare's network necessarily sees the connection, as any host would.
3. The record is **held back for one to three days** (a random delay), then released in a shuffled batch. That way
   nobody can tie a cook to "someone was smoking on Saturday afternoon".
4. Each night a GitHub Action adds released cooks to the **public dataset**: branch
   [`community-data`](https://github.com/Legal-Copy7045/gravity-controller/tree/community-data), CC0, as
   `cooks.jsonl` / `cooks.csv`. It also rebuilds `aggregates.json`: typical times by cut, weight, pit and outside
   temperature, only for groups of at least 3 cooks.

## Removing what you've shared

Each shared cook has a random deletion key that stays on your Home Assistant. **Remove my shared cooks** sends those
keys and the service deletes the cooks. Ones already in the dataset are removed at the next nightly build. Nobody else
can delete your cooks, and the key can't be traced back to you.

## How the averages are used

The integration downloads `aggregates.json` about twice a day, whether or not you share. It publishes the averages as
`sensor.smoker_community` (attribute `similar`), and the AI pitmaster's prompts include them as "similar shared cooks".
The controller's own learning still works from your cooks; the shared figures are a second reference, labelled with
how many cooks they're based on.

## Running your own

Everything is in this repository:
- the Worker: `sharing/worker`, deployed with `npx wrangler deploy` after creating a KV namespace;
- the nightly build: `.github/workflows/community-data.yml` and `.github/scripts/community_build.py`;
- the format's examples and tests: `sharing/schema/examples.json`.

To point an install at your own service, change `SHARE_URL` in `custom_components/smoker/sharing.py`.
