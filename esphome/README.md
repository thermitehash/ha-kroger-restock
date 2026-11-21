# ESPHome wall scanner

A wall-mounted barcode scanner: scan an empty package, and it lands on the
grocery list (and in your Kroger cart if it's in stock). A buzzer and two LEDs
tell you what happened.

| Feedback | Sound | Light | Meaning |
| --- | --- | --- | --- |
| Success | Short rising chirp | Green | In cart (or quantity +1 on a duplicate) |
| Waiting | Two medium beeps | Green + red | Out of stock; kept on the list as waiting |
| Error | Long low tone ×2 | Red blinks 3× | Unknown barcode, needs review, or Home Assistant unreachable |

Not affiliated with Kroger.

## Parts

| Part | Notes |
| --- | --- |
| ESP32 dev board (ESP32-WROOM-32, "esp32dev") | Any ESP32 with free GPIO16/17 works |
| Barcode module: **GM65** or **GM861** | UART (TTL) version. GM65 runs on 5 V; GM861 on 3.3 V. Both talk 3.3 V-level serial |
| Passive piezo buzzer (3–5 V) | Passive, so it can play tones. Optional: 100 Ω series resistor |
| Green LED + 220 Ω resistor | |
| Red LED + 220 Ω resistor | |
| Momentary push button (optional) | Prints the list on the receipt printer |
| 5 V USB power supply (1 A) | Powers the ESP32 and the scanner |
| Enclosure, wires | A 3D-printed or project box with a window for the scan head |

## Wiring

| Scanner pin | ESP32 pin | Notes |
| --- | --- | --- |
| VCC | 5V (GM65) or 3V3 (GM861) | Check your module's label |
| GND | GND | |
| TX | GPIO16 (RX2) | Scanner → ESP32 |
| RX | GPIO17 (TX2) | ESP32 → scanner (only used to send commands) |

| Part | ESP32 pin | Other side |
| --- | --- | --- |
| Buzzer + | GPIO25 | Buzzer − to GND |
| Green LED anode (via 220 Ω) | GPIO26 | Cathode to GND |
| Red LED anode (via 220 Ω) | GPIO27 | Cathode to GND |
| Print button | GPIO33 | Other leg to GND (internal pull-up is used) |

All pins can be changed under `substitutions:` at the top of
`kroger-scanner.yaml`.

## Scanner settings

Out of the box, GM65 and GM861 modules send each code at 9600 baud followed
by a carriage return (CR), which is what the config expects. If yours was
reconfigured, scan the setup codes in the module's manual to restore:

- Serial (UART) output, 9600 baud, 8N1
- Suffix: CR
- Recommended: **induction / sense mode** with a "same barcode delay" of
  about 1–2 s, so the scanner wakes when something is in front of it.
  Home Assistant also ignores repeat scans of the same code for 3 s by
  default (configurable in the integration's options).

## Setup

1. Copy `kroger-scanner.yaml` into your ESPHome config folder (or the ESPHome
   Device Builder app), and add the entries from `secrets.example.yaml` to your
   `secrets.yaml`. Generate the API key with `openssl rand -base64 32`, or let
   the dashboard create one.
2. Install it on the ESP32 (the first time over USB).
3. In Home Assistant, adopt the new device: **Settings → Devices & services →
   ESPHome**.
4. **Required:** on the ESPHome integration, open the device's **Configure**
   and turn on **Allow the device to perform Home Assistant actions**.
   Without this, scans never reach Home Assistant.
5. Add the feedback automation: paste `ha_feedback_automation.yaml` into a new
   automation (**⋮ → Edit in YAML**). If you renamed the device, change
   `esphome.kroger_scanner_feedback` to `esphome.<your_device_name>_feedback`.

## How it works

- The UART debugger with a dummy receiver acts as a line buffer: it collects
  bytes until CR and hands the whole line to a lambda, which keeps only the
  digits and calls `kroger_restock.scan_upc` with `source: esphome`.
- Home Assistant fires `kroger_restock_scanned`; the feedback automation calls
  the device's `feedback` action with the `result`, and the device plays the
  matching pattern.
- If Home Assistant isn't connected, the device plays the error pattern right
  away.
- The latest code is shown in Home Assistant as the **Last barcode** sensor.
