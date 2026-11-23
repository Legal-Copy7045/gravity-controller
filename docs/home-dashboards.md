# For integrators: embedding the Smoker page in another dashboard project

Most owners don't need this: the Smoker integration's own sidebar panel is the dashboard. This page is for people who
build their own Home Assistant dashboard site (a custom panel that hosts several pages in a frame, with its own site
bar and a shim between the pages and Home Assistant) and want the Smoker page inside it.

There is one copy of the page: `custom_components/smoker/frontend/page.html` (installed and updated by HACS). Load it
from there rather than forking it, and ask for changes in this repository.

## Assembling the page (what `panel.py` does, and what your build must do)

From `custom_components/smoker/frontend/` (on Home Assistant: `/config/custom_components/smoker/frontend/`):

1. `page.html`: replace `/*COMMON*/` with **this folder's `common.js`**. Don't also load another `common.js`-style
   helper that declares `$`, `esc`, `H`, `S`, `val`, `num`, `live`, `hist`… with `const`: loading both is a syntax
   error.
2. Insert `fonts.html` and `<style>` + `style.css` + `</style>` just before `</head>` (after the page's own `<style>`,
   as `panel.py` `build_page()` does). style.css carries its own colour tokens plus the ember accent `--page`
   #c2410c / #fb8a3c; your site's CSS may follow it. (In the Smoker panel, `shim.js` goes first in `<head>`; in your
   project, your own shim takes that place.)
3. The page talks to Home Assistant only through `window.hdHA` (`live`, `state`, `find`, `all`, `subscribe`, `call`,
   `service`, `ws`, and optionally `api`).
4. Optional label swap: the eyebrow reads `Smoker · live`.

The page works under a sticky `nav.site` site bar (its section bar measures it), shows a status strip first, and
works without `hdHA.api` (journal and package scans then say they need the Smoker integration; the grill photo is
looked up at `/local/smoker/grill.(png|jpg|webp)` directly).

## What the shim must allow (all limited to the Smoker's own entities: `*.smoker_*`)

| Kind | Allow |
|---|---|
| `call` | `number.set_value`, `select.select_option`, `switch.turn_on/turn_off/toggle`, `button.press` (**never** a factory reset, safe mode, or `button.smoker_clear_cook_history`), `text.set_value`, `input_number.set_value`, `input_text.set_value`, `input_datetime.set_datetime`, `input_boolean.turn_on/turn_off/toggle`, `timer.start/cancel` |
| `service` | `esphome.gravity980_*` (the controller's actions: programs, pit target, fuel log, forecast, context), `script.smoker_plan_cook`, `script.smoker_ai_advise` |
| `ws` | read-only `history/history_during_period` |
| `api` | `GET/POST/DELETE` on `^/api/smoker/(journal(/[0-9a-f]{6,16})?|draft|identify|grill_photo|photo/[0-9a-f-]+\.(jpg|png)|sharing(/(export|withdraw|(share|decline)/[0-9a-f]{6,16}))?)$` via `hass.fetchWithAuth`, returning JSON (or a Blob for photos); `identify` takes a `FormData` body |

`custom_components/smoker/frontend/shim.js` is the reference implementation of exactly this allowlist.

## Suggested placement

Slug `smoker`, title *Smoker*, icon `mdi:grill`, accent `#c2410c` / `#fb8a3c`. Site-wide alerts can take the page's
status strip conditions (grill not connected while a cook is active, lid open, running hot/cold during a cook, probe
check, charcoal under 1.5 h, program paused).
