# Hardware shortlist (draft BOM)

These are prototype-friendly breakout modules first; a custom PCB can replace them in phase 4.
Prices are rough UK street prices (generic vs branded) for budgeting only. ⚠ marks a choice that
depends on the measurement session (docs/design.md §9).

## Core

| Item | Recommended | Why / alternatives | ~£ |
|---|---|---|---|
| MCU | **Your ESP32-S3** for the prototype | For the final build, prefer a module with a **U.FL external antenna** (e.g. ESP32-S3-DevKitC-1**U**, N8R8) plus a 2.4 GHz antenna on the enclosure, because the steel grill body blocks Wi-Fi. A board with a built-in screen (LilyGO T-Display-S3) is an option if you want a local display | 8–15 |
| 12 V → 5 V | **Pololu D24V10F5** (or a generic MP1584EN) | The Pololu is cleaner, with real current limits; the MP1584 is fine for a prototype | 3–12 |
| Input protection | ATO/mini blade fuse holder + **3 A fuse**, SS34 Schottky (reverse polarity), SMBJ15A TVS | Grill PSUs and long leads are a noisy, wet environment | 3 |
| PSU | **Stock 12 V adapter** ⚠ check rating ≥ 2 A | Replace with a Mean Well GST36A12 if it's marginal | 0 / 15 |

## Fan drive (stock fan kept)

| Item | Recommended | Why / alternatives | ~£ |
|---|---|---|---|
| MOSFET | **IRLZ44N** (TO-220) or an **AO3400** (SOT-23) on a board, or a "**D4184** dual MOSFET" module | It must be **logic-level at 3.3 V**. ❌ Avoid the common **IRF520 modules**: they barely switch at 3.3 V | 1–3 |
| Gate parts | 100 Ω gate resistor, 10 kΩ gate pull-down | Pull-down = fan off at boot or crash | — |
| Flyback | 1N5819 / SS34 across the fan | | — |
| Fan monitor | **INA226** module | Measures fan current and voltage, which detects a seized, unplugged or dead fan. Better resolution than the INA219 | 3–6 |
| Optional | LC filter (100 µH + 470 µF) or an adjustable buck for voltage control | Only if low-frequency PWM is noisy or the fan stalls at low duty ⚠ | 3–8 |

## Temperature

| Item | Recommended | Why / alternatives | ~£ |
|---|---|---|---|
| Thermocouple amp ×2 | **MAX31856** breakout (Adafruit 3263 or a generic purple board) | Pit (if the stock probe is a TC ⚠) and the charcoal chute. It has open/short fault detection and 50/60 Hz rejection. MAX31855 is OK. ❌ The MAX6675 is old and slow | 5–15 ea |
| RTD amp (only if needed) | **MAX31865** breakout (Adafruit 3328/3648) | Only if the stock pit probe is a PT100/PT1000 ⚠ | 5–15 |
| NTC ADC ×2 | **ADS1115** module (addr 0x48 / 0x49) | 8 channels for 4 meat + 4 zone probes. ❌ Don't use the ESP32's own ADC for probes: it is noisy and non-linear | 2–5 ea |
| Bias resistors | 0.1 % metal film, 10 kΩ (meat) and 1 kΩ (air/zone), values to confirm per probe ⚠ | Accuracy of the divider matters more than the ADC | 2 |
| Meat probes | **ThermoWorks Pro-Series** or **Inkbird**-style 2.5 mm NTC food probes | Cheap, replaceable, standard plugs. Reuse the stock 980 probes if they fit ⚠ | 8–20 ea |
| Air/zone probes | Pro-Series-style **high-temp air probe with grate clip** (rated ~370 °C) | Left/right/top-rack zones | 10–20 ea |
| Chute thermocouple | K-type, stainless sheath, **≥ 1000 °C rated**, mini-K plug | Sits in/near the burning charcoal | 8–15 |
| Hopper-wall probes (phase 3) | 2–3 × NTC or K-type surface/clip probes | Burn-front estimate | 5–10 ea |

## Hopper level (phase 3)

| Item | Recommended | Why / alternatives | ~£ |
|---|---|---|---|
| ToF sensor | **VL53L1X** module (Pololu 3415 / Adafruit 3967 / generic GY-53L1) | Narrow programmable beam, mm resolution, I²C. The VL53L4CX is an alternative. ❌ Ultrasonic sensors (HC-SR04/JSN-SR04T) get scattered by lumpy charcoal and their beam is too wide for the hopper | 6–20 |
| Window | 3 mm borosilicate or polycarbonate disc + a short shroud | Keeps dust and heat off the sensor ⚠ check the lid temperature | 3 |

## Inputs, local UI, alarm

| Item | Recommended | Notes | ~£ |
|---|---|---|---|
| Lid/hopper switch | **Stock switch(es)** | Also wired inline with the fan as a hardware interlock ⚠ NC? | 0 |
| Buzzer | 5 V active buzzer + 2N2222/BC547 | | 1 |
| Display (optional) | 1.3" **SH1106 OLED** (I²C) | Readable outdoors; phase 4 | 4–8 |
| Knob (optional) | **EC11 rotary encoder** with push | Local setpoint change | 1–2 |

## Connectors, wiring, enclosure

| Item | Recommended | Notes | ~£ |
|---|---|---|---|
| Probe jacks | 2.5 mm **mono** panel-mount jacks ×8 | Match the probe plugs ⚠ (stock may be 3.5 mm) | 5 |
| TC jacks | **Mini-K** panel sockets ×2 (yellow) | Use thermocouple-grade contacts, not generic ones | 4–8 |
| Harness | **GX12** aviation connectors for fan, switch, power | Weatherproof, keyed | 5 |
| In-grill wire | **PTFE or silicone high-temp** wire, fibreglass sleeving | Normal PVC melts near the firebox | 5–10 |
| Enclosure | IP65 ABS/polycarbonate box (~120×80×50 mm) + cable glands | Mount where the stock controller sat, away from the firebox | 8–15 |
| Board | Perfboard / proto PCB → custom PCB (JLCPCB) later | | 2–10 |

## Tools worth having

| Tool | Why |
|---|---|
| Multimeter | Probe resistances, switch type, fan voltage (needed tomorrow) |
| Cheap USB logic analyser (Saleae clone, ~£10) or a pocket scope | Characterise the stock fan drive (PWM vs voltage) and debug I²C/SPI |
| Bench PSU (optional) | Test the fan's minimum running voltage and duty safely |
| Reference thermometer (e.g. Thermapen) | Probe calibration |
| IR thermometer | Hopper lid, wall and enclosure temperatures |

## Rough totals
- Prototype electronics (excluding the ESP32 and probes): **~£45–90**
- Probes (4 meat, 4 air, 1 chute TC): **~£90–170**, depending on brand
- Enclosure, connectors and wiring: **~£30–50**
