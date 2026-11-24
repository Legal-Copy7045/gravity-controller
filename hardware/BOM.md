# Hardware shortlist (draft BOM)

**Future work, not needed today.** Parts for a future controller of its own ([design notes](../docs/design.md)).
Today's bridge needs only the ESP32-S3 board: see the [README](../README.md#what-you-need). These are
prototype-friendly breakout modules first; a custom PCB can replace them in stage 4.
Prices are rough US street prices (Amazon/AliExpress/Adafruit/DigiKey) (generic vs branded) for budgeting only. ⚠ marks a choice that
depends on the measurement session ([design.md §9](../docs/design.md#9-measurement-session-grill-out)).

## Core

| Item | Recommended | Why / alternatives | ~$ |
|---|---|---|---|
| MCU | **ESP32-S3 N16R8** (DevKitC-1 style) for the prototype and likely the final build | 16 MB flash / 8 MB octal PSRAM. **GPIO 35–37 are taken by the PSRAM**; avoid the strapping pins 0, 3, 45 and 46 and the USB pins 19/20. It has a PCB antenna, so test Wi-Fi with the board in its enclosure on the grill; if it's weak, switch to an ESP32-S3-WROOM-1**U** board (U.FL) plus an external antenna | 8–20 |
| 12 V → 5 V | **Pololu D24V10F5** (or a generic MP1584EN) | The Pololu is cleaner, with real current limits; the MP1584 is fine for a prototype | 4–16 |
| Input protection | ATO/mini blade fuse holder + **3 A fuse**, SS34 Schottky (reverse polarity), SMBJ15A TVS | Grill PSUs and long leads are a noisy, wet environment | 4 |
| PSU | **Stock 12 V adapter** ⚠ check rating ≥ 2 A | Replace with a Mean Well GST36A12 if it's marginal | 0 / 20 |

## Fan drive (stock fan kept)

| Item | Recommended | Why / alternatives | ~$ |
|---|---|---|---|
| MOSFET | **IRLZ44N** (TO-220) or an **AO3400** (SOT-23) on a board, or a "**D4184** dual MOSFET" module | It must be **logic-level at 3.3 V**. ❌ Avoid the common **IRF520 modules**: they barely switch at 3.3 V | 1–4 |
| Gate parts | 100 Ω gate resistor, 10 kΩ gate pull-down | Pull-down = fan off at boot or crash | — |
| Flyback | 1N5819 / SS34 across the fan | | — |
| Fan monitor | **INA226** module | Measures fan current and voltage, which detects a seized, unplugged or dead fan. Better resolution than the INA219 | 4–8 |
| Optional | LC filter (100 µH + 470 µF) or an adjustable buck for voltage control | Only if low-frequency PWM is noisy or the fan stalls at low duty ⚠ | 4–10 |

## Temperature

| Item | Recommended | Why / alternatives | ~$ |
|---|---|---|---|
| Thermocouple amp ×2 | **MAX31856** breakout (Adafruit 3263 or a generic purple board) | Pit (if the stock probe is a TC ⚠) and the charcoal chute. It has open/short fault detection and 50/60 Hz rejection. MAX31855 is OK. ❌ The MAX6675 is old and slow | 6–20 ea |
| RTD amp (only if needed) | **MAX31865** breakout (Adafruit 3328/3648) | Only if the stock pit probe is a PT100/PT1000 ⚠ | 6–20 |
| NTC ADC ×2 | **ADS1115** module (addr 0x48 / 0x49) | 8 channels for 4 meat + 4 zone probes. ❌ Don't use the ESP32's own ADC for probes: it is noisy and non-linear | 3–6 ea |
| Bias resistors | 0.1 % metal film, 10 kΩ (meat) and 1 kΩ (air/zone), values to confirm per probe ⚠ | Accuracy of the divider matters more than the ADC | 3 |
| Meat probes | **ThermoWorks Pro-Series** or **Inkbird**-style 2.5 mm NTC food probes | Cheap, replaceable, standard plugs. Reuse the stock 980 probes if they fit ⚠ | 10–26 ea |
| Air/zone probes | Pro-Series-style **high-temp air probe with grate clip** (rated ~370 °C) | Left/right/top-rack zones | 13–26 ea |
| Chute thermocouple | K-type, stainless sheath, **≥ 1000 °C rated**, mini-K plug | Sits in/near the burning charcoal | 10–20 |
| Hopper-wall probes (stage 3) | 2–3 × NTC or K-type surface/clip probes | Burn-front estimate | 6–13 ea |

## Hopper level (back of the list)

| Item | Recommended | Why / alternatives | ~$ |
|---|---|---|---|
| ToF sensor | **VL53L1X** module (Pololu 3415 / Adafruit 3967 / generic GY-53L1) | Narrow programmable beam, mm resolution, I²C. The VL53L4CX is an alternative. ❌ Ultrasonic sensors (HC-SR04/JSN-SR04T) get scattered by lumpy charcoal and their beam is too wide for the hopper | 8–26 |
| Window | Borosilicate window + shroud | **Deprioritised:** the hopper runs very hot; only revisit with a remote-optics or cooled mount | 4 |

## Inputs, local UI, alarm

| Item | Recommended | Notes | ~$ |
|---|---|---|---|
| Lid/hopper switch | **Stock switch(es)** | Also wired inline with the fan as a hardware interlock ⚠ NC? | 0 |
| Buzzer | 5 V active buzzer + 2N2222/BC547 | | 1 |
| Display | 1.3" **SH1106 OLED** (I²C), or a 0.56" 4-digit TM1637 LED display for "current temp" only | The LED display is the most readable in sunlight | 5–10 |
| Knob (optional) | **EC11 rotary encoder** with push | Local setpoint change | 1–3 |

## Connectors, wiring, enclosure

| Item | Recommended | Notes | ~$ |
|---|---|---|---|
| Probe jacks | 2.5 mm **mono** panel-mount jacks ×8 | Match the probe plugs ⚠ (stock may be 3.5 mm) | 6 |
| TC jacks | **Mini-K** panel sockets ×2 (yellow) | Use thermocouple-grade contacts, not generic ones | 5–10 |
| Harness | **GX12** aviation connectors for fan, switch, power | Weatherproof, keyed | 6 |
| In-grill wire | **PTFE or silicone high-temp** wire, fibreglass sleeving | Normal PVC melts near the firebox | 6–13 |
| Enclosure | IP65 ABS/polycarbonate box (~120×80×50 mm) + cable glands | Mount where the stock controller sat, away from the firebox | 10–20 |
| Board | Perfboard / proto PCB → custom PCB (JLCPCB) later | | 3–13 |

## Tools worth having

| Tool | Why |
|---|---|
| Multimeter | Probe resistances, switch type, fan voltage (needed for the measurement session) |
| Cheap USB logic analyser (Saleae clone, ~$12) or a pocket scope | Characterise the stock fan drive (PWM vs voltage) and debug I²C/SPI |
| Bench PSU (optional) | Test the fan's minimum running voltage and duty safely |
| Reference thermometer (e.g. Thermapen) | Probe calibration |
| IR thermometer | Hopper lid, wall and enclosure temperatures |

## Rough totals
- Prototype electronics (excluding the ESP32 and probes): **~$60–120**
- Probes (4 meat, 4 air, 1 chute TC): **~$120–220**, depending on brand
- Enclosure, connectors and wiring: **~$40–65**
