# Shopping list

♻️ = common workshop parts many makers already have (resistor and capacitor kits, Wago lever connectors, 22 AWG wire,
breadboards, Dupont jumpers, proto board, heat shrink, Kapton tape, solder, flux, a multimeter). Check your parts box
before ordering.

Prices are rough US street prices for budgeting.

## Today: the bridge (all you need)

| Qty | Part | Notes | Have? | ~$ |
|---|---|---|---|---|
| 1 | **ESP32-S3 N16R8** board (16 MB flash, 8 MB octal PSRAM, DevKitC-1 style, BOOT button on GPIO0) | The firmware is built for it. Keep the BOOT button reachable in the box | | 8–20 |
| 1 | USB-C charger (5 V, 1 A is plenty) + USB-C cable | Powers the bridge near the grill; a data cable for the first flash | ♻️ | 0–10 |
| 1 | Small weatherproof box (IP65, ~100×68×50 mm) + cable gland | Keep the ESP32 out of rain and heat. Mount it away from the firebox; plastic so Bluetooth/Wi-Fi get out | | 8–15 |

That's it: the bridge talks to the stock controller wirelessly. **Total ≈ $15–50.**

## Future: a controller of its own (not needed today)

**Future work.** Nothing in today's firmware uses these parts; they're for building a controller that replaces the
stock one ([design notes](../docs/design.md)). Buy only after the measurement session ([design.md §9](../docs/design.md#9-measurement-session-grill-out)) — the ⚠ rows
depend on what the measurements show.

### Core electronics

| Qty | Part | Notes | Have? | ~$ |
|---|---|---|---|---|
| 1 | ESP32-S3 N16R8 (second board, or reuse the bridge's) | Same firmware family. If Wi-Fi is weak at the grill, the **IPEX/U.FL version + 2.4 GHz antenna** | ♻️ | 0–15 |
| 1 | 12 V → 5 V buck: **Pololu D24V10F5** (or MP1584EN module) | Runs everything from the grill's 12 V supply | | 5–16 |
| 1 | Logic-level MOSFET: **AO3400** on a breakout, **IRLZ44N**, or a **D4184** module | Fan driver. ❌ not the IRF520 modules (don't switch at 3.3 V) | | 2–5 |
| 1 | Schottky diode **SS34 / 1N5819** | Fan flyback | | 1 |
| 1 | **INA226** current/voltage module | Fan health (dead/unplugged/seized) | | 4–8 |
| 1 | Inline ATO fuse holder + **3 A** fuse, **SMBJ15A** TVS | 12 V input protection | | 4 |
| — | Resistors: 100 Ω (gate), 10 kΩ (gate pull-down), 4.7 kΩ ×2 (I²C pull-ups) | | ♻️ resistor kit | 0 |
| — | Capacitors: 0.1 µF decoupling, 100 µF on 5 V | | ♻️ capacitor kits | 0 |

### Temperature

| Qty | Part | Notes | Have? | ~$ |
|---|---|---|---|---|
| 2 | **MAX31856** thermocouple breakout (Adafruit 3263 or generic) | Pit (⚠ if the stock pit probe is a thermocouple) and charcoal-chute probe | | 8–20 ea |
| 0–1 | **MAX31865** RTD breakout (Adafruit 3328/3648) | Only ⚠ if the stock pit probe is a PT100/PT1000 | | 8–20 |
| 2 | **ADS1115** 16-bit ADC module (0x48 / 0x49) | 8 channels: 4 food + 4 zone NTC probes | | 3–6 ea |
| 8 | 0.1 % metal-film resistors (⚠ 10 kΩ food, 1 kΩ air; confirm after measuring probes) | Divider accuracy | | 3 |
| 8 | 2.5 mm mono panel jacks | For standard NTC probes (⚠ check the stock probes' plug: may be 3.5 mm) | | 6 |
| 2 | Mini-K thermocouple panel sockets | Pit and chute | | 5–10 |
| 4 | High-temp **air probes with grate clips** (ThermoWorks Pro-Series or Inkbird-compatible, 2.5 mm) | Zone temperatures (left/right/top rack) | | 13–26 ea |
| 1 | K-type thermocouple, stainless sheath, ≥ 1000 °C, mini-K plug | Charcoal chute (fire health) | | 10–20 |
| 0–4 | Food probes (2.5 mm NTC) | Only if you want more than the stock ones / the Govee's | | 10–26 ea |

A **Govee H5198** (4 probes, through Home Assistant or read directly over Bluetooth) may cover food probes entirely,
leaving the ADS1115 channels for zones.

### Local display, alarm, status light

| Qty | Part | Notes | Have? | ~$ |
|---|---|---|---|---|
| 1 | **MAX98357A amp + 4 Ω 3 W speaker** | Alarm tones / spoken alerts (much louder and nicer than a buzzer) | | 6–10 |
| 1 | **WS2812B ring** (or a short strip) + **SN74AHCT125N** + 470 Ω | Status light: colour = pit on target / hot / cold / alarm, visible across the garden | | 5–10 |
| 1 | 0.56" **TM1637** 4-digit LED display (or 1.3" SH1106 OLED) | "Current temp" readout, readable in sunlight | | 3–8 |
| 1 | **EC11 rotary encoder** with push (or 3 buttons) | Setpoint and alarm silence without the phone | | 2–3 |

### Connectors, wiring, enclosure

| Qty | Part | Notes | Have? | ~$ |
|---|---|---|---|---|
| 3 | **GX12** aviation connectors (2/3/4-pin) | Fan, lid switch, 12 V in: weatherproof and keyed | | 6–10 |
| 1 | **Wago 221-415** lever connectors | 12 V / 5 V / GND hubs | ♻️ | 0 |
| — | **PTFE or silicone high-temperature wire** + fibreglass sleeving | Anything inside or near the grill body: ordinary PVC melts | | 8–13 |
| — | 22 AWG stranded hook-up wire | Inside the enclosure | ♻️ | 0 |
| 1 | IP65 ABS/polycarbonate enclosure (~120×80×50 mm) + cable glands | Where the stock controller sits | | 10–20 |
| 1 | Perma-Proto half board (or a JLCPCB carrier later) | Interface board | ♻️ | 0 |
| — | Heat shrink, Kapton tape, solder, flux, cable ties | | ♻️ | 0 |

### Tools

| Part | Notes | Have? |
|---|---|---|
| Multimeter | Needed for the measurement session (probe resistances, fan voltage, switch type) | ♻️ |
| Soldering iron, strippers | | ♻️ |
| USB logic analyser (Saleae clone, ~$12) or pocket scope | Optional: tells PWM from DC on the stock fan drive | |
| IR thermometer | Optional: hopper, enclosure-location temperatures during a cook | |

### Hopper level (back of the list)

The hopper gets too hot for a laser (ToF) sensor without a cooled/remote-optics mount; deferred. The fuel estimate
from fan duty and burn time comes first (software only), then 2–3 clip-on probes on the outside of the hopper wall
(burn-front estimate, uses spare ADS1115 channels).

## Future controller total (new parts only)

Roughly **$100–170** for electronics and connectors, plus **$60–130** for zone probes and the chute thermocouple,
assuming the ♻️ items come from your parts box.
