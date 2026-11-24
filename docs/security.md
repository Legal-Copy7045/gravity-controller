# Security: what's protected, and how much

This is a smoker controller on a home network. The aim is **convenient to use, not full of holes, and never a way
in for someone else's code**: the board must not become the first foothold in an attack on the rest of the house.
Reviews (the regression suite's security review included) judge findings against this, not against a bank's or a
power station's standards.

## Threat model

**In scope (guarded firmly):**
- **Someone else's code running on the controller.** A board that can be reflashed over the network is a foothold.
- **A web page in your browser** quietly changing the controller or reading its keys (cross-site requests).
- **Bad data from outside:** an AI answer, a shared cook record, the weather service, a Bluetooth thermometer or
  something pretending to be the grill. It may give wrong numbers, but it must not run code, crash the board in a
  loop, or push the grill outside safe limits.
- **Your keys** (AI, Pushover, Telegram, ntfy) leaking from the board, its page or its logs.
- **The release pipeline:** a tampered build, or the signing key leaking.

**Out of scope (convenience wins):**
- People you've let into Home Assistant, and devices you trust on your Wi-Fi. Anyone with a Home Assistant login can
  already work the grill; the controller doesn't try to tell your family apart.
- Someone already able to read your Wi-Fi traffic or holding the board in their hands.
- A determined attacker on your LAN who wants to annoy you (lock the page, run up an AI bill). These are limited
  where it's cheap to do so, and always recoverable (BOOT button, Home Assistant).

## Never a way in for code

| Way in | How it's closed |
|---|---|
| Firmware over the network | Only updates signed with this project's key are installed, never an older version. No LAN upload: no ESPHome OTA port, no upload on the device page. The signing key never meets the compile's third-party build code (CI signs in a separate job). |
| Firmware over USB | Physical access only (web installer). |
| Wi-Fi setup | The setup hotspot appears only for a new controller or one that can't reach its Wi-Fi, within 15 minutes of power-on; Bluetooth setup needs a press of the BOOT button. |
| Home Assistant's API | Encrypted once Home Assistant adopts the controller. Before that, open for 15 minutes after power-on (to add it), and closed straight away when a device-page PIN is set. |
| The device page | Serves only its own files (nothing loaded from the internet); refuses requests from other websites; parses input with size limits; no file uploads stored. |
| Outgoing requests | HTTPS with certificate checks, no redirects followed, answers capped at 64 KB and parsed as JSON only. |
| AI answers and shared data | Treated as data: shown escaped, never run. An AI's cook program is checked, by the controller and by Home Assistant (pit capped at "AI max pit", including what a keep step can ask for; no Turbo; no links), before it can be loaded, and you load it yourself. |
| The Home Assistant integration | Admin-only for installing the package (setting the PIN is offered to admins, but anyone with a Home Assistant login can reach the controller's own actions: they're trusted); photo uploads checked as images; no paths taken from requests; the dashboard's bridge only touches the smoker's own entities. |
| Notification buttons | A one-time code per notification, valid only for that notification's buttons. |
| Build pipeline | Actions pinned to commit SHAs; the build and signing jobs' Python packages hash-pinned (the signing job installs only esptool and its own dependencies, in a fresh environment); the test jobs' packages version-pinned (they hold no secrets and publish nothing); release jobs separated; provenance attested. |

## Convenience choices (deliberately relaxed)

- The device-page PIN is optional, can be set whenever you like, and keeps a browser unlocked for a week.
- Readings, and asking the AI (5 questions a day from a locked page), need no PIN.
- Home Assistant keeps its **Clear the device page PIN** and **Factory reset** buttons (the reset needs two presses
  within 10 s).
- Local only is off by default.

## Reporting

Found something that lets code in, or leaks a key? Open an issue (no details of an unfixed hole in public: ask for a
contact first).
