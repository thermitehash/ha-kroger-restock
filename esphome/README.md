# ESPHome wall scanner

Scan an empty package at the wall and it lands on the grocery list (and in
your Kroger cart if it's in stock).

Not affiliated with Kroger.

## Recommended build: M5Stack AtomS3 Lite + Atomic QRCode2 Base (no soldering)

| Part | Notes |
| --- | --- |
| M5Stack **AtomS3 Lite** (ESP32-S3, 8 MB) | Has the RGB LED (GPIO35) and button (GPIO41) used for feedback |
| M5Stack **Atomic QRCode2 Base** (SKU A133-B) | M14 scan engine with its own beep and illumination; the Atom plugs on top |
| USB-C cable (right-angle recommended) + 5 V USB supply | |
| 3D-printed wall housing | [`../hardware/housing/`](../hardware/housing/) |

Config: [`kroger-scanner-atoms3.yaml`](kroger-scanner-atoms3.yaml)

### Feedback

| Result | Atom LED |
| --- | --- |
| In cart (or quantity +1) | Green |
| Waiting on stock | Amber |
| Needs review | Blue |
| Unmatched, error, or Home Assistant unreachable | Red |
| Print sent (short press) | White |
| Sync sent (long press) | Cyan |

The base's own beep confirms each read. QR codes and other non-product codes
are ignored on the device: no beep from Home Assistant, no LED.

### Button

- **Short press:** print the list on the receipt printer (`print_list`)
- **Long press (1 s+):** push pending cart items (`sync`)

### Pins and scanner setup (from M5Stack's driver code)

| Signal | AtomS3 pin | Notes |
| --- | --- | --- |
| Scanner TX → Atom RX | GPIO5 | `rx_pin` |
| Atom TX → scanner RX | GPIO6 | `tx_pin` (if nothing is ever read, swap 5 and 6) |
| TRIG | GPIO7 | Only for pulse mode; not used |
| RGB LED | GPIO35 | Built into the Atom |
| Button | GPIO41 | Built into the Atom, active low |

UART runs at 115200 baud. At boot the device sends the M14 these commands
(from M5Stack's `qrcode_m14` driver), so you don't need to scan setup
barcodes:

- `21 61 41 02`: auto (continuous) scan mode. Set `scan_mode: "0x05"` for
  motion-sensing mode instead (wakes when something moves in front).
- `21 63 42 01`: one beep per successful read.
- `21 64 82 05 DC`: report the same code again only after 1.5 s. Home
  Assistant also ignores repeats for 3 s by default.

**Barcode types:** UPC-A, UPC-E, EAN-8 and EAN-13 are normally on by
default on scan engines like this. The UART commands to enable them couldn't
be verified, so if a UPC won't scan, scan the "enable UPC-A / UPC-E / EAN-8 /
EAN-13" setup codes in M5Stack's M14 user manual (linked from the Atomic
QRCode2 Base product page).

## Alternative build: ESP32 + GM65 / GM861 (soldered)

The original design, still supported: [`kroger-scanner.yaml`](kroger-scanner.yaml)
with a buzzer and two LEDs. Parts and wiring below.

| Feedback | Sound | Light | Meaning |
| --- | --- | --- | --- |
| Success | Short rising chirp | Green | In cart (or quantity +1 on a duplicate) |
| Waiting | Two medium beeps | Green + red | Out of stock; kept on the list as waiting |
| Error | Long low tone ×2 | Red blinks 3× | Unknown barcode, needs review, or Home Assistant unreachable |

Not affiliated with Kroger.

### Parts (GM65 build)

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

### Wiring (GM65 build)

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

### Scanner settings (GM65 build)

Out of the box, GM65 and GM861 modules send each code at 9600 baud followed
by a carriage return (CR), which is what the config expects. If yours was
reconfigured, scan the setup codes in the module's manual to restore:

- Serial (UART) output, 9600 baud, 8N1
- Suffix: CR
- Recommended: **induction / sense mode** with a "same barcode delay" of
  about 1–2 s, so the scanner wakes when something is in front of it.
  Home Assistant also ignores repeat scans of the same code for 3 s by
  default (configurable in the integration's options).

## Setup (both builds)

1. Copy `kroger-scanner-atoms3.yaml` (or `kroger-scanner.yaml` for the GM65 build) into your ESPHome config folder (or the ESPHome
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
