# The Smoker page in the home-dashboards project

The Smoker dashboard is one page with two homes:

- the **Smoker integration's own panel** (`custom_components/smoker`, sidebar entry *Smoker*), and
- the owner's **home-dashboards** project (`/home-dashboards/smoker`), with its site bar, menus, search and alerts.

Like the MagicbHAnds page, the **content belongs to this repo**: `custom_components/smoker/frontend/page.html` (installed and
updated by HACS). home-dashboards owns the plumbing (pickup, nav, shim allowlist). There is one copy of the page: don't
fork it into home-dashboards; ask for changes here.

## Assembling the page (what `panel.py` does, and what home-dashboards' build must do)

From `custom_components/smoker/frontend/` (on Home Assistant: `/config/custom_components/smoker/frontend/`):

1. `page.html`: replace `/*COMMON*/` with **this folder's `common.js`** (not home-dashboards' `live_common.js`: both
   declare `$`, `esc`, `H`, `S`, `val`, `num`, `live`, `hist`… with `const`, so loading both is a syntax error).
2. Insert `fonts.html` and `<style>` + `style.css` + `</style>` just before `</head>` (after the page's own `<style>`, as
   `panel.py` `build_page()` does). style.css carries the same tokens as home-dashboards' shell plus the ember accent
   `--page` #c2410c / #fb8a3c; the shell's CSS may follow it. (In the Smoker panel, `shim.js` goes first in `<head>`;
   inside home-dashboards its own shim takes that place.)
3. The page talks to Home Assistant only through `window.hdHA` (`live`, `state`, `find`, `all`, `subscribe`, `call`,
   `service`, `ws`, and optionally `api`).
4. Optional label swap: the eyebrow reads `Smoker · live`.

The page already sits under a sticky `nav.site` (its section bar measures the site bar), shows a status strip first, and
works without `hdHA.api` (journal and package scans then say they need the Smoker integration; the grill photo is
looked up at `/local/smoker/grill.(png|jpg|webp)` directly).

## What the shim must allow (all limited to the Smoker's own entities: `*.smoker_*`)

| Kind | Allow |
|---|---|
| `call` | `number.set_value`, `select.select_option`, `switch.turn_on/turn_off/toggle`, `button.press` (**never** a factory reset, safe mode, or `button.smoker_clear_cook_history`), `text.set_value`, `input_number.set_value`, `input_text.set_value`, `input_datetime.set_datetime`, `input_boolean.turn_on/turn_off/toggle`, `timer.start/cancel` |
| `service` | `esphome.gravity980_*` (the controller's actions: programs, pit target, fuel log, forecast, context), `script.smoker_plan_cook`, `script.smoker_ai_advise` |
| `ws` | read-only `history/history_during_period` |
| `api` (new) | `GET/POST/DELETE` on `^/api/smoker/(journal(/[0-9a-f]{6,16})?|draft|identify|grill_photo|photo/[0-9a-f-]+\.(jpg|png))$` via `hass.fetchWithAuth`, returning JSON (or a Blob for photos); `identify` takes a `FormData` body |

`custom_components/smoker/frontend/shim.js` is the reference implementation of exactly this allowlist.

## Suggested placement

Slug `smoker`, title *Smoker*, icon `mdi:grill`, accent `#c2410c` / `#fb8a3c`, menu *Outdoors* (next to Yard and Flying).
Site-wide alerts can take the page's status strip conditions (grill not connected while a cook is active, lid open, running
hot/cold during a cook, probe check, charcoal under 1.5 h, program paused).
