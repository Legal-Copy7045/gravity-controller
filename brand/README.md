# Brand

Original artwork for this project (not Char-Griller's logo or trademarks): a gravity smoker, barrel and hopper tower,
with an ember flame, on an ember tile.

| File | Use |
|---|---|
| `mark.svg` | The mark (any size ≥ 24 px). |
| `favicon.svg` | The flame alone, for 16–32 px (browser tabs). |
| `icon.png`, `icon@2x.png` | 256 / 512 px, transparent corners: the sizes Home Assistant's brands repository asks for (`custom_integrations/smoker/`). |
| `icons.svg` | Line icons (24 × 24, `stroke="currentColor"`), used as `<svg class="ic"><use href="#i-flame"/></svg>`: now, flame, food, grill, hopper, chart, plan, book, setup, steps, wifi, bt, off, fan, alert. |

Colours: ember `#f97316` → `#b4330a` (tile), accent `#c2410c` light / `#fb8a3c` dark (pages), charcoal `#1c1917`,
cream `#fff7ed`. Type: Bricolage Grotesque (headings), Instrument Sans (text), JetBrains Mono (numbers), the same as the
home-dashboards project.

The pages inline these files (the dashboard in `custom_components/smoker/frontend/page.html`, the controller's own page
in `firmware/device-ui/ui.js`, the installer in `web/index.html`); update them there too when the artwork changes.
