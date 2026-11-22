# Gravity 980 smoker controller

Local, cloud-free control and monitoring for the **Char-Griller Gravity Fed 980** charcoal smoker, built on an
**ESP32-S3** with **ESPHome** and **Home Assistant**.

**Phase 1 (this release): bridge.** The ESP32-S3 talks to the grill's *stock* controller over Wi-Fi (TCP) and/or
Bluetooth, and adds:

- **Learning cook-time prediction** for every food probe: a physics model (warming → stall → finishing) fitted to the
  live data, seeded from your most similar past cooks (protein, weight, pit temperature, wrapped, weather) and
  corrected for how your grill actually holds temperature. Finish time with an early/late range, before the probe is
  even in the meat.
- **Stall detection** and stall-remaining estimates; "wrapped" switch that the model takes into account.
- **Cook programs** you can type on a phone: `pit 250 until food1 >= 165 for 30m; pit 275 until food1 >= 203; hold 200 notify "Rest it"`.
- **Alerts**: done / almost done, stall start and end, probe slipped out, pit off target, fire may be out, lid open,
  grill connection lost. Through Home Assistant (actionable notifications), with **ntfy** as a direct path for
  critical alarms when Home Assistant is down.
- **Home Assistant AI** (any `ai_task` entity): plan a cook from a sentence, a second-opinion ETA every 30 minutes,
  a review after each cook.
- **Six food probe slots**, each reading the grill's own probes, a **Govee H5198** directly over Bluetooth, or any
  temperature entity in Home Assistant. Plus a **Bluetooth proxy**: the closest radio to the grill.
- **Charcoal fuel gauge** from what you tell it (started ¾ full, topped up to ½, finished with ⅛), learning your
  grill's burn rate; low-fuel and "won't last to the finish" alerts.
- **Forecast-aware** finish times, a **pull-temperature and rest coach** (learned carryover and cooling), a
  **cook journal** with ratings, notes and curve comparison, **package photos read by AI** to set what's being cooked,
  and **voice** through Assist. See [docs/features-0.2.md](docs/features-0.2.md).
- **Dashboard**: a phone-friendly Home Assistant sidebar page, with AI recommendations (prep, lighting time, wrap point, weather effects).
- **Updates over the air** from GitHub Pages; **browser installer** for the first flash.

**Phase 2 (planned): replacement controller** driving the stock fan directly, with extra zone probes. See
[docs/design.md](docs/design.md) and [hardware/shopping-list.md](hardware/shopping-list.md).

Estimates that need history (finish times, pull-at, the charcoal gauge) and anything from the AI are marked
**Experimental** until the controller has learned enough; see
[What's experimental](docs/features-0.2.md#whats-experimental).

## Quick start

1. Flash the ESP32-S3 from the [web installer](https://legal-copy7045.github.io/gravity-controller/) (Chrome/Edge).
2. Add the **Smoker** device in Home Assistant, set **Grill IP address** on its device page (or rely on Bluetooth).
3. Add the Home Assistant package and the dashboard integration: [docs/install.md](docs/install.md).
4. First session with the grill: [docs/first-run.md](docs/first-run.md).

## Repository

| Path | What |
|---|---|
| `components/gravity980/` | ESPHome component: stock-controller protocol over TCP and BLE |
| `components/cook_assistant/` | ESPHome component: predictor, cook history, programs, alerts (pure C++ core + glue) |
| `firmware/` | Device configuration (`core.yaml`) and the prebuilt firmware entry point |
| `custom_components/smoker/` | Home Assistant integration: the Smoker sidebar dashboard |
| `homeassistant/packages/smoker.yaml` | Notifications, AI advisor/planner/review, ready-by planner, rest timer |
| `tools/fake_grill.py` | Simulated stock controller for testing without the grill |
| `tools/ble_probe.py` | Laptop tool to investigate the grill's Bluetooth protocol |
| `tests/` | Unit tests, end-to-end test (native firmware ↔ simulator), HA config check, dashboard render test |
| `docs/` | Research, design, protocol, programs, predictor, install, first run |

## Development

```bash
make -C tests                                   # core unit tests
esphome compile firmware/gravity980-bridge.yaml # ESP32-S3 firmware
esphome compile tests/host-bridge.yaml && python3 tests/e2e.py
python3 tests/ha_check.py && python3 tests/render_page.py
```

Protocol reverse engineering credit: [grzbiet/cg980app](https://github.com/grzbiet/cg980app) (MIT). Unofficial hobby
project, not affiliated with Char-Griller.
