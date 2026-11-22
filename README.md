# Kroger Restock for Home Assistant

<img src="custom_components/kroger_restock/brand/icon.png" alt="" width="96" align="right">

A Home Assistant custom integration that keeps your household grocery list in
Home Assistant and syncs it to your Kroger cart through Kroger's public API.

Scan a barcode with an iPhone Shortcut or a wall-mounted scanner, type an item,
or ask Assist. In-stock items go straight to your cart. Out-of-stock items stay
on the list as **waiting**. Nothing leaves the list until you check it off.

> **Not affiliated with Kroger.** This is an independent, community project.
> "Kroger" is used only to describe compatibility with Kroger's public
> developer API. It is not endorsed by, sponsored by or affiliated with The
> Kroger Co.

**Status:** Phases 1–3 are done: sign-in, store selection, barcode and text
lookup, the to-do list, cart push, the scan event, stock re-checks, order-day
holds, the give-up flag, notifications, and printing to a receipt printer or a
letter-size PDF, plus a blueprint, example automations and an iOS Shortcut
guide, and an ESPHome wall scanner. See [Roadmap](#roadmap).

<!-- Screenshot placeholder: the to-do list card -->
<!-- ![Grocery list](docs/screenshots/todo.png) -->

## Contents

- [Requirements](#requirements)
- [1. Create a Kroger developer app](#1-create-a-kroger-developer-app)
- [2. Install through HACS](#2-install-through-hacs)
- [3. Add the integration](#3-add-the-integration)
- [How the list works](#how-the-list-works)
- [Entities](#entities)
- [Actions](#actions)
- [Events](#events)
- [Order tracking from emails](#order-tracking-from-emails)
- [Printing](#printing)
- [Scanning with an iPhone Shortcut](#scanning-with-an-iphone-shortcut)
- [Blueprint and examples](#blueprint-and-examples)
- [Options](#options)
- [Pre-order cart check](#pre-order-cart-check)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Roadmap](#roadmap)

## Requirements

- Home Assistant **2026.11** or newer
- [HACS](https://hacs.xyz/)
- A Kroger-family store account (Kroger, Ralphs, Fred Meyer, King Soopers, …)
- A free Kroger developer account

## 1. Create a Kroger developer app

1. Go to <https://developer.kroger.com/> and sign in (or create a developer
   account; this is separate from your shopping account).
2. Open **My Apps → Register App** (the wording may differ slightly).
3. Fill in:
   - **Name:** anything, e.g. `Home Assistant Restock`
   - **Environment:** Production
   - **Redirect URI:** `https://my.home-assistant.io/redirect/oauth`
   - **Scopes / API products:** enable **Products**, **Cart** and
     **Identity**, which give these OAuth scopes:
     - `product.compact` (product search, prices, stock, aisles)
     - `cart.basic:write` (add to cart)
     - `profile.compact` (identify the account, so it can't be added twice)
4. Save, then copy the **Client ID** and **Client Secret**.

The redirect URI uses [My Home Assistant](https://my.home-assistant.io/), so
it works whether or not your Home Assistant is reachable from the internet. If
you've disabled the `my` integration, use
`https://<your-ha-url>/auth/external/callback` instead.

## 2. Install through HACS

1. In Home Assistant, open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/thrivestorm2/ha-kroger-restock` with type
   **Integration**.
3. Find **Kroger Restock** in HACS, download it, and restart Home Assistant.

### Updating

HACS only re-checks custom repositories about every 48 hours, so a new
release can take up to two days to appear on its own. To check now: open
**Kroger Restock** in HACS → **⋮ → Update information**, then **Download** (or
update from **Settings → Updates**) and restart Home Assistant. Your list,
settings and order history carry over.

## 3. Add the integration

> **Do this on a computer.** On a phone, the switch between the Home
> Assistant app and the browser during Kroger's sign-in usually loses the
> flow. After setup, everything works from the phone.

1. **Settings → Devices & services → Add integration → Kroger Restock.**
2. When asked for application credentials, enter the Client ID and Client
   Secret from step 1. (You can also add them first under
   **Settings → Application credentials**.)
3. Sign in to your Kroger shopping account and approve access.
4. Enter your ZIP code and pick your store. Each store is listed with its
   street address, because Kroger's store names don't always match the town
   the store is in (a store can be named after a neighboring area). Stock
   levels, prices and
   aisles come from this store.
5. Choose **Pickup** (default) or **Delivery**.

You get a to-do list called **Grocery list** (entity ID based on your store
name, e.g. `todo.kroger_downtown`), plus sensors and buttons. The list's
`store_name`, `store_address` and `location_id` attributes show which store
it refers to.

**Changing store later** (Configure → Change store) takes effect right away,
with no reinstall. The entry is renamed after the new store, aisle, price and
stock data is re-read from it, and entity IDs stay the same.

## How the list works

Home Assistant's list is the source of truth. Every item has a status:

| Status | Meaning | Pushed to cart? |
| --- | --- | --- |
| `in_cart` | Found and in stock; pushed to your Kroger cart | Yes |
| `pushing` | Cart call in progress (saved first, so a crash can't lose it) | In progress |
| `check_cart` | A push was interrupted; may or may not be in the cart; confirm in Repairs | Unknown |
| `waiting` | Found but temporarily out of stock | No |
| `held` | Back in stock, waiting for the order-day window | Not yet |
| `needs_review` | A text or produce match needs you to pick the product | No |
| `unmatched` | The barcode isn't in Kroger's catalog | No |
| `received` | You checked it off | — |

- **Scanning** looks the product up at your store. In stock → cart.
  Out of stock → `waiting`. Unknown barcode → `unmatched`, with the raw code as
  the name so you can fix it. Nothing is ever dropped.
- **Scanning something already on the list** adds 1 to its quantity, and only
  the extra unit is pushed. Repeat scans of the same code within the debounce
  window (3 s by default) are ignored, so a wall scanner can't double-count.
- **Typing or saying an item** searches your store. One clear match is handled
  like a scan. Otherwise the item is marked `needs_review` with up to five
  candidates; fix it with `kroger_restock.resolve_item`.
- **Produce stickers (PLU codes)** like `4011` are searched by name and always
  marked `needs_review`.
- **Waiting items are re-checked** every few hours (3 h by default), with the
  calls spread out. When one comes back in stock it's pushed right away, or,
  if you've set order days, marked `held` and pushed in the window before your
  order day. You get a notification either way.
- **Give-up flag:** an item waiting longer than the give-up setting (30 days by
  default) raises a Repairs issue where you choose **Keep waiting** (restarts
  the clock) or **Remove from list**. Items are never removed automatically.
- **Checking an item off** marks it `received`. That's the only way it leaves
  the active list.
- **Unchecking a received item**, or calling `kroger_restock.readd_item`
  ("they shorted me at pickup"), checks stock again and pushes it again.
- **No double pushes.** The integration records how many units of each item it
  has pushed. Syncing only sends what hasn't been sent yet.
- **Saved before every cart call.** An item is written to disk as *pushing*
  before the request goes to Kroger, and marked *in cart* only after Kroger
  confirms. If Home Assistant restarts or crashes mid-push, or Kroger doesn't
  answer, the item comes back as **May already be in your Kroger cart** (status
  `check_cart`) instead of being lost or pushed twice. Check the Kroger app,
  then settle it from **Settings → Repairs** (or the `check_cart_item`
  action): **Confirm in cart**, **Push again**, or **Remove**.
- **Already in the cart?** For something you added in the Kroger app (or that
  reached the cart without being recorded), scan or add it with
  `already_in_cart: true`. It's recorded as in the cart, with no cart call, so
  it isn't added twice. This works with `scan_upc`, `add_item` and
  `resolve_item`; a needs-review item added this way is recorded when you
  resolve it.
- In the to-do list, each item reads `Name (size) ×qty`. The description shows
  its status, e.g. `In cart · Aisle 12` or `Waiting on stock since Nov 21`.
  Editing the `×qty` part changes the quantity (and pushes the difference).

### How barcodes are matched

Kroger product IDs are 13 digits. For each scan the integration tries, in
order, and stops at the first hit:

1. UPC-A (12 digits): drop the check digit, left-pad to 13
2. EAN-13: drop the check digit, left-pad to 13
3. UPC-E (8 digits): expand to UPC-A, then rule 1
4. Fallback: the full code, left-pad to 13

Successful matches are remembered, and so is any fix you make with
`resolve_item`, so the next scan of that code goes straight through.

**QR codes and other codes are ignored.** Packaging often has a QR code
(recycling info, recipes, GS1 Digital Link) or a Data Matrix code next to the
UPC. Only plain numeric codes are looked up; anything containing letters,
slashes, parentheses or control characters is ignored and no item is added.
You're told so: `scan_upc` returns `{result: ignored, reason:
not_a_product_barcode, message: ...}`, a `kroger_restock_scanned` event fires
with `result: ignored`, and a notification goes out if notification targets
are set (at most one every 30 s). The ESPHome scanners drop these codes on the
device and blink amber twice.

**Short UPC-E codes.** 6- and 7-digit codes are treated as UPC-E missing the
number system and/or check digit: they're expanded to UPC-A, the check digit
is computed, and then they're normalized as usual (the plain code is still
tried last).

### Store locations (aisles)

Kroger's aisle *number* isn't always an aisle. An item at a checkout lane can
come back as number 300 with description "CHECKLANE 15". The description
decides what's shown:

- "AISLE 12" (or a number with no description) → **Aisle 12**
- check lanes, registers, front end → the description (**Checklane 15**),
  grouped under **Front of store** on printouts
- anything else (seasonal, endcaps, departments) → the description, e.g.
  **Seasonal**, as its own group

Printouts list numbered aisles first, then named areas, then Front of store,
then items with no location ("Other").

## Entities

| Entity | Description |
| --- | --- |
| `todo.<store>` | The grocery list (create, edit, check off, delete, reorder) |
| `sensor.<store>_in_cart` | Number of items pushed to the cart |
| `sensor.<store>_waiting_on_stock` | Number of out-of-stock items |
| `sensor.<store>_held_for_order_day` | Number of held items |
| `sensor.<store>_needs_review` | Number of items to review |
| `sensor.<store>_unmatched` | Number of unknown barcodes |
| `sensor.<store>_last_stock_check` | When stock was last checked |
| `sensor.<store>_kroger_order` | Current order status, from order emails (see [Order tracking](#order-tracking-from-emails)) |
| `button.<store>_sync_now` | Push any pending cart items |
| `button.<store>_check_stock_now` | Re-check waiting items now |
| `button.<store>_print_receipt` | Print to the receipt printer |
| `button.<store>_print_pdf` | Make (and print) the letter-size PDF |

## Actions

Every action returns response data (optional), so an iOS Shortcut or script
can show the result. If you have more than one Kroger Restock entry, pass
`config_entry_id`.

### `kroger_restock.scan_upc`

| Field | Required | Default | Description |
| --- | --- | --- | --- |
| `upc` | one of these three | | UPC-A, UPC-E, EAN-13 or PLU code |
| `product_id` | one of these three | | 13-digit Kroger product ID, looked up directly (no barcode guessing) |
| `url` | one of these three | | A kroger.com (or Kroger-banner) product link, or shared text containing one |
| `quantity` | no | 1 | How many |
| `source` | no | `scan` | `scan`, `shortcut`, `esphome`, `manual` or `assist` |

```yaml
action: kroger_restock.scan_upc
data:
  upc: "049000028911"
  source: shortcut
response_variable: result
```

Example response:

```yaml
result: in_cart        # in_cart, waiting, unmatched, needs_review, duplicate
item_id: 3f2a...
status: in_cart
name: Coca-Cola Classic Soda
brand: Coca-Cola
size: 12 fl oz
price: 7.99
aisle: Aisle 7
quantity: 1
upc: "0004900002891"
product_id: "0004900002891"
stock_level: HIGH
image_url: https://...
pushed: true           # false if the cart push failed (it is retried on sync)
```

A scan ignored by the debounce returns `{result: duplicate, debounced: true}`.
A QR code or other non-product code returns `{result: ignored, message: ...}`.

**Links:** product pages look like `https://www.kroger.com/p/<name>/0001111041700`.
The trailing 13-digit ID is used; query strings (`?fulfillment=PICKUP`) and
fragments are ignored, and the link can be inside other text (as the Kroger
app's Share button sends it). A link to any other site, or a Kroger page
that isn't a product page, returns `{result: ignored}` with *"Ignored a link
that isn't a Kroger product page"*. `already_in_cart: true` works with
`product_id` and `url` too.

### `kroger_restock.add_item`

Adds an item by name (`name`, `quantity`, `source`), or by product link
(`url`, same rules as `scan_upc`). Same response shape. If the item needs
review, the response includes `candidates`.

### `kroger_restock.resolve_item`

Fixes an `unmatched` or `needs_review` item: `item_id`, plus `product_id`
(the 13-digit Kroger product ID, or a UPC). The barcode is remembered.

### `kroger_restock.sync`

Pushes any `in_cart` items whose push is still pending (for example after a
network error). Returns `pushed`, `pending` and the items pushed. Units that
were already pushed are never sent again.

### `kroger_restock.readd_item`

Puts an item back (`item_id`) and pushes it again after a stock check. Use it
when an order was shorted. It's the only way an already-pushed item is pushed
again, and it pushes the full quantity.

### `kroger_restock.check_stock`

Re-checks every waiting item now and pushes held items if you're inside the
order window. Returns `checked`, `back_in_stock`, `pushed`, `held`,
`still_waiting` and `held_pushed`.

### `kroger_restock.check_cart_item`

Settles an item whose cart push was interrupted (`check_cart`): `item_id`,
and `action` = `confirm` (it's in the cart; nothing is sent), `push_again`
(it isn't; push now) or `remove` (take it off the list). Same as the Repairs
fix flow.

### `already_in_cart` option

`scan_upc`, `add_item` and `resolve_item` accept `already_in_cart: true` to
record an item that's already in your Kroger cart without calling Kroger.
The response includes `already_in_cart: true`.

### `kroger_restock.mark_cart_received`

Marks the in-cart items (fully pushed) as received after an order is picked up
or delivered. Optional `missing`: items that were expected but didn't arrive,
as item IDs or names (`eggs, milk`). Those go back on the list (stock check,
then pushed again for your next order). Returns `received`, `missing` (each
item's new status) and `unmatched` (names that matched nothing; uncheck those
on the list instead). The order-complete notification does the same with its
**All received** / **Some missing…** buttons.

### `kroger_restock.print_list`

Prints the list. `target`: `receipt`, `pdf` or `both` (default). Returns
`items`, `receipt` (`printed`, `failed` or `not_configured`) and `pdf`
(`path` of the saved file and whether it was `printed`). See
[Printing](#printing).

### `kroger_restock.cart_check`

Sends the [pre-order cart check](#pre-order-cart-check) now and returns
`in_cart` (`item_id`, `name`, `quantity`), `unconfirmed` and `waiting`.
Never changes the cart.

## Events

### `kroger_restock_scanned`

Fired after every scan or text add (not for debounced repeats).

| Key | Example |
| --- | --- |
| `result` | `in_cart`, `waiting`, `unmatched`, `needs_review`, `duplicate` or `ignored` (QR / non-product code; `message` explains) |
| `name`, `brand`, `size` | `Coca-Cola Classic Soda`, `Coca-Cola`, `12 fl oz` |
| `price` | `7.99` |
| `aisle` | `Aisle 7` |
| `quantity` | `1` |
| `upc` | `0004900002891` |
| `source` | `esphome` |
| `item_id`, `config_entry_id` | |

```yaml
triggers:
  - trigger: event
    event_type: kroger_restock_scanned
    event_data:
      result: waiting
actions:
  - action: notify.mobile_app_phone
    data:
      message: "{{ trigger.event.data.name }} is out of stock; it's on the list."
```

### `kroger_restock_back_in_stock`

Fired when a stock check finds waiting items back in stock. Data: `pushed` and
`held` (lists of `{item_id, name}`) and `config_entry_id`.

## Order tracking from emails

Kroger's public API can't read orders, so order status comes from the emails
Kroger sends instead, read through Home Assistant's built-in
[IMAP integration](https://www.home-assistant.io/integrations/imap/).

### What Kroger actually emails

Based on a year of real pickup orders (and one Instacart delivery), Kroger
sends these, all from `email@e.krogermail.com`:

| Email | Subject (roughly) | Status |
| --- | --- | --- |
| Pickup confirmed | "Pickup Order Confirmed, <name>" (older: "Order Confirmed, <name>") | `placed`, with window, item count, total, fee |
| Delivery confirmed (Instacart) | "Order Confirmed, <name>": same subject as the older pickup email | `placed` (pickup vs delivery is told apart by the body) |
| Ready for pickup | "Your Order is Ready for Pickup at <store address>" | `ready` |
| Final receipt | "<name>, Here's Your Final Receipt…" (pickup) / "…Instacart Order." | `completed` |

The first name differs when more than one household member orders; names are
never used for matching. The final receipt has **no order number, items or
totals**: it completes the most recent *ready* pickup order (or *placed*
delivery order) from the last 24 hours, and is ignored otherwise.

**Never seen in a year of emails:** substitution or out-of-stock notices,
"order changed/cancelled", "out for delivery", "delivered", or any list of
shorted items. Kroger most likely sends those as app notifications or texts.
So `shopping`, `out_for_delivery` and `cancelled` are supported but
**unverified**, and shorted-item/substitution parsing is **experimental**.

### Setup

This setup is tested with Gmail. Give order tracking its **own** IMAP
connection, so automations using any existing IMAP connection aren't
affected.

1. **Gmail filter** (gmail.com → Settings → Filters and blocked addresses →
   Create a new filter):
   - **From:** `e.krogermail.com`
   - Actions: **Apply the label** `Kroger` (create it), and **Never send it to
     Spam**.
   - Ticking "Also apply filter to matching conversations" is fine, and
     recommended: the `Kroger` label can and should hold your full order
     history. Old mail is never processed (see *Linking keeps your history*
     below).
2. **New IMAP connection** (Settings → Devices & services → Add integration
   → IMAP), signed in with a Gmail **app password**:
   - **Folder:** `Kroger`
   - **Search:** `FROM "e.krogermail.com"`. **Don't** use the default
     `UnSeen UnDeleted`: once you open a Kroger email on your phone, an
     `UnSeen` search skips it.
   - In the connection's options, under message data for events, turn on
     **text** and **headers**. Headers let Kroger Restock dedupe by
     Message-ID.
   - **Max message size:** the default (2048) is fine. Kroger Restock reads
     the full message with `imap.fetch`, which isn't limited by that setting.
   - Rename the connection to something you'll recognize (e.g. "Gmail –
     Kroger orders"). HA names it after the account, so two connections to one
     mailbox otherwise look the same.
3. **Why not INBOX?** Gmail files recent Kroger receipts under the Promotions
   tab, and archiving moves mail out of INBOX. A label (or `[Gmail]/All Mail`
   with the same search) keeps working either way.

**Linking keeps your history (baseline).** When you pick an IMAP connection
in Order tracking (or pick a different one, or change its folder or search),
Kroger Restock first reads the headers of every message already in that folder
and records them as seen, **without processing them**. Only mail that arrives
afterwards is acted on. The log shows e.g. *"Baselined 100 existing messages
in folder Kroger"*. If the mailbox can't be reached, nothing is processed
until it can: a Repairs issue explains why, and it retries every 5 minutes.
The seen list and baseline are saved, so a Home Assistant restart never
reprocesses anything. (HA's IMAP integration re-announces the newest message
at every start; that's expected and ignored.)

4. In **Kroger Restock → Configure → Order tracking**, pick that connection.
   Each choice is shown as *"<name> — folder: … · search: …"*. If the one you
   pick searches `UnSeen` or watches INBOX, you'll get a warning first.
   - **Notify on order updates** (on by default): ready for pickup, cancelled,
     and **order picked up / delivered**, which asks *"Mark the N in-cart
     items received?"* Items are never checked off automatically, because the
     receipt doesn't list them. The notification has three buttons:
     - **All received:** marks every in-cart item received.
     - **Some missing…:** type what didn't come (e.g. `eggs, milk`). Those
       items go back on the list (stock check, then back into the cart for
       your next order), everything else is marked received, and a follow-up
       notification confirms what matched. Use this for Kroger's last-minute
       out-of-stock and replacement notices, which come by **text message**
       with a link, not email, so the integration can't see them.
     - **Open list:** opens the grocery list; unchecking an item there does
       the same as typing it.
   - **Extra senders**: only if your banner's order emails come from a
     sender that isn't recognized (domains or full addresses).

Only order mail is read: `email@e.krogermail.com` and other Kroger-family
domains. Kroger's developer-portal mail (`krogerapisupport@…`) and anything
not from a Kroger sender is ignored. Each email is processed once, even if it
moves folders.

### The order sensor

`sensor.<store>_kroger_order` shows the current order: `placed`, `ready`,
`completed`, or `none`, plus the unverified `shopping`, `out_for_delivery`
and `cancelled`. A finished order stays visible for two days, then the sensor
goes back to `none`.

Attributes: `order_number`, `window` (e.g. `Mar 4, 2027 4:00pm–5:00pm`),
`window_start` / `window_end` (timestamps; the email's store-local times are
read in Home Assistant's time zone), `modality` (`pickup`/`delivery`),
`item_count`, `total` (estimated), `fee` (the actual fee: a struck-through
`$4.95 $0.00` reads as 0.00), `placed`, `completed`, `updated`,
`last_email`, and `recent_orders`.

`shorted_items` and `substitutions` are **absent** unless an email actually
contained that information (absent = unknown; an empty list = none).

Delivery addresses are never stored or logged.

### Event: `kroger_restock_order_update`

Fired for every order email that changes something. Data: `order_number`,
`status`, `previous_status`, `window`, `window_start`, `window_end`,
`modality`, `shorted`, `shorted_item_ids`, `readded_item_ids` (always empty;
automatic re-adding is disabled), `substitutions`, `subject`,
`config_entry_id`.

### Limitations

- Parsing depends on Kroger's wording, which can change and may differ by
  banner. An unrecognized email is ignored; the sensor keeps its last state.
- **Automatic re-adding of shorted items is disabled** (the v0.6.0 option
  is gone) until a real Kroger email with item-level shortage data turns up.
- If your emails aren't recognized, open an issue describing the subject and
  layout. Don't paste real emails: remove names, addresses, order numbers and
  amounts.

## Printing

Both printouts use the same layout:

- A header with the date and your store
- Items in your cart (and held items) grouped by aisle, in aisle order, with a
  checkbox, name, size and quantity. Items with no aisle come last under
  **Other**.
- **Waiting — check shelf:** out-of-stock items, in case they're on the shelf
  anyway
- **Needs review:** unmatched and needs-review items
- A footer with the item count

**Receipt printer (ESC/POS).** Any network thermal printer that accepts raw
jobs on port 9100 works; no driver is needed. The integration sends plain
ESC/POS: initialize, bold headers, word-wrapped lines and a paper cut. Choose
58 mm (32 columns) or 80 mm (48 columns) paper.

**Letter-size PDF.** The PDF is laid out in two columns (the receipt is one
column). Sections flow down the left column, then the right, and the last page
is balanced so a short list uses both columns. A section that breaks across a
column repeats its heading with "(cont.)". Every PDF is saved to `/media/kroger_restock/` (turn this
off in options), so you can open it from **Media → My media**. If you enter an
IPP printer URL (for example `ipp://printer.local/ipp/print`, or `ipps://…`),
the PDF is also sent as an IPP Print-Job. Most network printers made in the
last decade support IPP and PDF; if yours doesn't accept PDF, use the saved
file instead.

<!-- Screenshot placeholder: receipt and PDF printouts -->

## Scanning with an iPhone Shortcut

Scan a barcode with your iPhone camera and add it straight to the list.

1. Open the **Shortcuts** app and create a new shortcut named **Grocery scan**.
2. Add **Scan QR or Barcode**.
3. Add the Home Assistant app's **Perform Action** (called "Call Service" in
   older app versions). Choose your server, then:
   - **Action:** pick `kroger_restock.scan_upc` **first**. Leaving the Action
     unset while there's text in the data field crashes the Home Assistant
     app.
   - **Data:** exactly this JSON, with the Shortcut's **QR/Barcodes** variable
     (tap the field, then pick it from the variable bar) placed **inside the
     quotes** after `"upc":`:
     ```json
     {"upc": "<QR/Barcodes variable>", "source": "shortcut"}
     ```
     The quotes matter: codes start with 0, and without quotes the leading
     zero is lost.
   - Turn on **Return response** (or "Response data") if it's offered.
4. Add **Show Result** (or **Show Notification**) and insert the action's
   output. To show just the useful bits, add **Get Dictionary Value** for
   `result`, `name` and `aisle` before it, e.g. *"in_cart: Coca-Cola Classic
   Soda (Aisle 7)"*.
5. Make it one tap away:
   - **Action button** (iPhone 15 Pro and later): Settings → Action Button →
     Shortcut → **Grocery scan**.
   - **Back Tap** (any recent iPhone): Settings → Accessibility → Touch →
     Back Tap → Double Tap → **Grocery scan**.

The response `result` is `in_cart`, `waiting`, `unmatched`, `needs_review`,
`duplicate` or `ignored`. For `ignored`, show `message`.

**Cover the QR code.** The iPhone scanner prefers QR codes over barcodes, and
many bags and boxes have one near the UPC. Cover it with a finger and aim at
the barcode. If it catches the QR code anyway, the response is `ignored` with
*"Ignored a QR or non-product code - aim at the barcode and cover any QR
code"*, and you also get a notification if notification targets are set.

The iPhone scanner returns a UPC-A as 13 digits with a leading 0 (e.g.
`0040000579793`). That's expected and matches on the first try.

<!-- Screenshot placeholder: the Shortcut -->

**Does Perform Action return the response?** Not yet tested with this
integration. If your Home Assistant app's Perform Action doesn't hand back
response data, turn on **Notify on every scan** (Settings page of the
options) instead: each scan then sends one short push such as
*"✓ In cart: Coca-Cola Classic Soda 12 fl oz · Aisle 7"*.

### Add from a Kroger product page (Share Sheet)

Add something you found on kroger.com or in the Kroger app without scanning:

1. New shortcut named **Add to Kroger list**. In its details (ⓘ), turn on
   **Show in Share Sheet** and set it to receive **URLs** and **Text**.
2. Add **Perform Action**, action `kroger_restock.scan_upc`, data:
   ```json
   {"url": "[Shortcut Input]", "source": "shortcut"}
   ```
   with the **Shortcut Input** variable inside the quotes.

Then on a product page tap **Share → Add to Kroger list**. A link that
isn't a Kroger product page is ignored.

### Notify on every scan

Off by default (**Configure → Settings → Notify on every scan**). When on,
every scan, typed add or shared link sends one short push to your
notification targets:

| Result | Notification |
| --- | --- |
| Added and pushed | ✓ In cart: *name size* · *aisle* |
| Out of stock | ⏳ Waiting on stock: *name* |
| Unknown barcode | ? Unknown code *code* |
| Already on the list | ↺ Already on list (qty N): *name* |
| Needs you to pick | • Needs review: *what you typed* |
| QR code / not a product | ⊘ Ignored: aim at the barcode |

They share one notification tag, so rapid scans replace each other instead
of piling up. With no notification targets set, nothing is sent.

## Blueprint and examples

### "At the store" blueprint

When a chosen person enters a chosen zone (draw one around your store under
**Settings → Areas, labels & zones → Zones**), their phone gets a notification
with the in-cart, waiting and needs-review counts and a link that opens the
list.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fthrivestorm2%2Fha-kroger-restock%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fkroger_restock%2Farrive_at_store.yaml)

Or import it manually: **Settings → Automations & scenes → Blueprints →
Import blueprint**, and paste
`https://github.com/thrivestorm2/ha-kroger-restock/blob/main/blueprints/automation/kroger_restock/arrive_at_store.yaml`.

### ESPHome wall scanner

An M5Stack **AtomS3 Lite** on an **Atomic QRCode2 Base**: no soldering,
continuous scanning, RGB LED feedback (green in cart, amber waiting, blue
needs review, red unmatched), and the Atom's button prints (short press) or
syncs (long press). A 3D-printable wall housing is in
[`hardware/housing/`](hardware/housing/). See
[`esphome/README.md`](esphome/README.md) for setup. The older ESP32 + GM65
build is still there as an alternative.

### Example automations

In [`examples/`](examples/). Paste one into a new automation with
**⋮ → Edit in YAML**, then change the IDs marked in the comments.

| File | What it does |
| --- | --- |
| [`nfc_print_receipt.yaml`](examples/nfc_print_receipt.yaml) | Tap an NFC tag (say, on the fridge) to print the list on the receipt printer |
| [`vestaboard_order_day.yaml`](examples/vestaboard_order_day.yaml) | Put a one-line summary on a Vestaboard on order day |
| [`notify_unmatched_scan.yaml`](examples/notify_unmatched_scan.yaml) | Notify your phone when a scanned barcode isn't in the catalog |

## Options

**Settings → Devices & services → Kroger Restock → Configure**:

- **Change store** (by ZIP code)
- **Order type:** Pickup or Delivery
- **Scan debounce** (default 3 s)
- **Order days** and **lead time** (default: none, 1 day). With order days
  set, back-in-stock items are held and pushed from `lead time` days before an
  order day through the order day. Example: order day Saturday, lead time 1 →
  pushed on Friday or Saturday.
- **Stock check interval** (default 3 h)
- **Give-up after** (default 30 days)
- **Notification targets:** `notify.mobile_app_*` actions. With none chosen,
  you get a persistent notification in Home Assistant instead.

- **Notify on every scan** (default off): see
  [Notify on every scan](#notify-on-every-scan).

**Cart check** (its own page in the options menu): see
[Pre-order cart check](#pre-order-cart-check).

**Printing** (its own page in the options menu):

- **Receipt printer host** and **port** (default 9100)
- **Paper width:** 58 mm or 80 mm (default 80 mm)
- **PDF printer (IPP URL):** optional
- **Save PDFs to /media/kroger_restock** (default on)

## Pre-order cart check

Kroger's API can't read your cart, so Home Assistant only knows what it
pushed. The cart check asks you to compare before you order:

- **When:** with order days set, `hours before` the start (midnight) of each
  order day (default 6 → 6 pm the evening before). With no order days, weekly
  on the chosen day and time (default Saturday 6 pm). Off by default:
  **Configure → Cart check**.
- **What it says:** *"Home Assistant thinks your Kroger cart has 3 items:
  Coca-Cola ×2, Eggs ×1. 2 waiting on stock."* Unconfirmed pushes (Repairs)
  are listed separately.
- **Buttons:** **Matches** (dismiss) · **Something's missing from HA** (type
  item names, comma-separated; each is recorded with `already_in_cart: true`,
  so it's on the list but not pushed) · **Open list**.
- It **never changes the Kroger cart.** Without notification targets it
  becomes a persistent notification (no buttons).
- Run it any time with `kroger_restock.cart_check`, which returns
  `in_cart`, `unconfirmed` and `waiting`.

## Limitations

These come from Kroger's public API:

- **The cart is write-only.** The API can add to your cart but can't read it
  or remove from it. The integration keeps its own record of what it pushed.
  **If you remove or change items in the Kroger app or website, Home Assistant
  won't know.** Deleting an item from the Home Assistant list doesn't remove it
  from your Kroger cart either.
- **No Kroger Shopping List, order history or checkout.** You still place the
  order in the Kroger app or website. Order *status* can come from Kroger's
  emails instead; see [Order tracking](#order-tracking-from-emails).
- **Daily rate limits** apply per endpoint (about 10,000 product calls, 5,000
  cart calls and 1,600 location calls per day). The integration caches product
  lookups and barcode matches, checks duplicates before calling the API, and
  batches cart pushes. Call counts appear in diagnostics.
- **Stock levels are Kroger's estimate.** Items with no stock data are treated
  as available.
- **Existing cart contents can't be read.** Items already in your cart (added
  in the Kroger app) aren't on the Home Assistant list, and scanning one adds
  another.
- **Setup sign-in needs a computer** (see step 3).
- Items typed in the to-do UI or spoken through Assist are recorded with
  source `manual`; use `add_item` with `source: assist` to tag them yourself.

## API verification status

| Item | Status |
| --- | --- |
| OAuth URLs, HTTP Basic client auth, refresh grant, 30-minute tokens | Verified against Kroger's OpenAPI specs |
| `profile.compact` scope | **Verified live** (HA 2026.11, Nov 2026: the entry's unique ID is the Kroger profile UUID) |
| Cart body, 204 response, 13-digit UPC, PICKUP/DELIVERY | Verified against the specs |
| Rate limits, `stockLevel` values | Verified against the specs |
| Product calls with the **user token** | **Verified live** (v0.6.0, Nov 2026: `products_use_app_token: false`) |
| Barcode normalization with iPhone scans | **Verified live** (13-digit codes with a leading 0 matched on the first candidate) |
| `stockLevel` in product responses | **Verified live** (`HIGH` returned) |
| Cart add | **Verified live** (pushed, `pushed_quantity: 1`; two national-brand items end to end) |
| Store attributes (`store_name`, `store_address`, `location_id`) and the checklane aisle rule | **Verified live** (v0.8.0) |
| Items and debug log level survive an update + restart | **Verified live** (v0.8.0) |
| Order-email folder baseline against real Gmail | **Verified live** (v0.10.0: linking didn't process existing order mail; the "Baselined N" info line wasn't checked because logging was at WARNING) |
| Out-of-stock path | **Verified live** (v0.10.0: scanned item went to `waiting`, `pushed: false`, aisle `Produce`) |
| Named-area aisle rule (`Produce`) | **Verified live** (v0.10.0) |
| Back in stock → pushed + notified | Not yet tested live |
| Kroger store-brand items | Not yet tested live |
| PDF print over IPP | IPP printer configured (Nov 2026); printing not yet tested live |
| Add by product link / `product_id`, Notify on every scan, cart check | New in v0.11.0; tested in CI, not yet live |
| Shortcut Perform Action returning response data | Not yet tested |
| Whether the cart accepts an out-of-stock UPC | Unknown (`tests/test_live_cart.py`, run locally). The integration never pushes out-of-stock items either way |
| Refresh-token lifetime | Unknown |

## Troubleshooting

- **"Kroger sign-in expired" repair:** Kroger rejected the saved refresh token.
  Open the integration and re-authenticate. Scans that fail during this time
  return an error; items already on the list are kept.
- **Diagnostics:** **⋮ → Download diagnostics** on the integration. Tokens,
  your store address and account ID are redacted.
- **Debug logs:**

  ```yaml
  logger:
    logs:
      custom_components.kroger_restock: debug
  ```

  Debug logs show, for each product call, whether the **user** or
  **client-credentials** token was used, and, for each scan, every barcode
  candidate tried in order with hit/miss.

## Development

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff format . && ruff check .
pytest
UPDATE_GOLDEN=1 pytest tests/test_printing.py   # after changing a print layout
python script/gen_translations.py   # after editing strings.json
node script/render_icons.js         # after editing assets/*.svg
```

**Releasing:** bump `version` in `manifest.json` (and optionally add
`docs/releases/v<version>.md`, first line = title). When that reaches `main`
and the Validate workflow passes, the Release workflow tags and publishes it.
A version that's already released is skipped.

**Test environment:** CI runs the tests on Home Assistant 2026.10.4, the newest
version `pytest-homeassistant-custom-component` supports so far, while the
integration's minimum is 2026.11 (`hacs.json`). Bump the pinned test package
once one for 2026.11 is out.

`tests/test_live_cart.py` is an optional, manual check against the real API
(it shows whether Kroger's cart accepts an out-of-stock UPC). It is skipped
unless `KROGER_LIVE_*` environment variables are set, and it adds one unit to
the real cart. Run it locally, never in CI or a cloud session.

## Roadmap

1. ✅ **Core:** OAuth, store selection, API client, barcode normalization,
   storage, to-do list, `scan_upc` / `add_item` / `resolve_item` / `sync`,
   cart push, scan event, tests, CI
2. ✅ Stock re-checks, `held` and order-day window, give-up flag,
   notifications, `readd_item`, check-stock button
3. ✅ Printing: ESC/POS receipt printer and letter-size PDF over IPP
4. ✅ Blueprint, example automations, iOS Shortcut guide
5. ✅ ESPHome wall scanner ([`esphome/`](esphome/))

## Future plans

See [docs/ROADMAP.md](docs/ROADMAP.md): learned name → product matching, and
a Tandoor Recipes shopping-list connector.

## License

[MIT](LICENSE)
