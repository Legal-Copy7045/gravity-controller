# Third-party software and licences

This project's own code (the ESPHome components, the device page, the Home Assistant integration and package, the
tools and the docs) is under the [MIT licence](LICENSE).

## The firmware binary is GPLv3

The released firmware (`.bin` files on the [releases page](https://github.com/Legal-Copy7045/gravity-controller/releases)
and the [web installer](https://legal-copy7045.github.io/gravity-controller/)) is a combined work: this project's
components are compiled together with ESPHome's C++ runtime, which is licensed under the GNU General Public Licence
version 3. **The firmware binary is therefore distributed under the terms of the GPLv3.**

The complete corresponding source is this repository at the release's tag (`v<version>`): `firmware/` (the
configuration, entry point `firmware/gravity980-bridge.yaml`) and `components/`, built with the ESPHome version pinned in
`.github/workflows/build.yml` (`ESPHOME_VERSION`; the controller's own page shows it under *This controller → Built
with*). ESPHome itself, and the libraries below, are fetched by ESPHome's build at those versions. To build it
yourself, see [Development](README.md#development). The MIT licence on this project's own files still applies to those
files on their own.

## Bundled in the firmware

Versions are those of the current build and move with ESPHome.

| Component | Licence | Notes |
|---|---|---|
| [ESPHome](https://github.com/esphome/esphome) | GPLv3 (C++ runtime); MIT (Python code generator, not shipped in the binary) | The device framework |
| [ESP-IDF](https://github.com/espressif/esp-idf) (5.5) | Apache-2.0 | Espressif's SDK, with its own bundled components (FreeRTOS: MIT; mbedTLS: Apache-2.0; NimBLE: Apache-2.0; lwIP: BSD) |
| [libsodium](https://github.com/jedisct1/libsodium) (ESPHome's ESP-IDF packaging) | ISC (packaging: MIT) | Encryption for the Home Assistant API |
| [noise-c](https://github.com/rweather/noise-c) (ESPHome's fork) | MIT | Noise protocol for the Home Assistant API |
| [ArduinoJson](https://github.com/bblanchon/ArduinoJson) | MIT | JSON |
| [espressif/mdns](https://github.com/espressif/esp-protocols) | Apache-2.0 | `gravity980.local` |
| [multipart-parser](https://components.espressif.com/components/zorxx/multipart-parser) | MIT | Web server uploads |
| [Improv SDK](https://github.com/improv-wifi/sdk-cpp) | Apache-2.0 | Wi-Fi setup over USB and Bluetooth |

## The web installer

The installer site serves [ESP Web Tools](https://github.com/esphome/esp-web-tools) (Apache-2.0) from its own
address; the site build downloads a pinned release from npm and checks its hash.

## Protocol credit

The stock controller's protocol was first worked out by [grzbiet/cg980app](https://github.com/grzbiet/cg980app)
(MIT), from analysis of the official app and live testing. See [docs/protocol.md](docs/protocol.md) for what has been confirmed since.

## Trademarks

Char-Griller and Gravity 980 are trademarks of their owner. This is an unofficial hobby project, not affiliated with or
endorsed by Char-Griller. Govee, Home Assistant, ESPHome and other names belong to their owners.
