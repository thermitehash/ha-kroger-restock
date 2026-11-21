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

**Status:** Phase 1 (core) is done: sign-in, store selection, barcode and
text lookup, the to-do list, cart push and the scan event. Stock re-checks,
order-day holds, notifications, printing and the ESPHome scanner come in
later phases. See [Roadmap](#roadmap).

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
- [Options](#options)
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

## 3. Add the integration

1. **Settings → Devices & services → Add integration → Kroger Restock.**
2. When asked for application credentials, enter the Client ID and Client
   Secret from step 1. (You can also add them first under
   **Settings → Application credentials**.)
3. Sign in to your Kroger shopping account and approve access.
4. Enter your ZIP code and pick your store. Stock levels, prices and aisles
   come from this store.
5. Choose **Pickup** (default) or **Delivery**.

You get a to-do list called **Grocery list** (entity ID based on your store
name, e.g. `todo.kroger_downtown`), plus sensors and a **Sync now** button.

## How the list works

Home Assistant's list is the source of truth. Every item has a status:

| Status | Meaning | Pushed to cart? |
| --- | --- | --- |
| `in_cart` | Found and in stock; pushed to your Kroger cart | Yes |
| `waiting` | Found but temporarily out of stock | No |
| `held` | Back in stock, waiting for the order-day window *(Phase 2)* | Not yet |
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
- **Checking an item off** marks it `received`. That's the only way it leaves
  the active list.
- **Unchecking a received item** ("they shorted me at pickup") checks stock
  again and pushes it again.
- **No double pushes.** The integration records how many units of each item it
  has pushed. Syncing only sends what hasn't been sent yet.
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

## Entities

| Entity | Description |
| --- | --- |
| `todo.<store>` | The grocery list (create, edit, check off, delete, reorder) |
| `sensor.<store>_in_cart` | Number of items pushed to the cart |
| `sensor.<store>_waiting_on_stock` | Number of out-of-stock items |
| `sensor.<store>_needs_review` | Number of items to review |
| `sensor.<store>_unmatched` | Number of unknown barcodes |
| `sensor.<store>_last_stock_check` | When stock was last checked |
| `button.<store>_sync_now` | Push any pending cart items |

Print and stock-check buttons arrive in later phases.

## Actions

Every action returns response data (optional), so an iOS Shortcut or script
can show the result. If you have more than one Kroger Restock entry, pass
`config_entry_id`.

### `kroger_restock.scan_upc`

| Field | Required | Default | Description |
| --- | --- | --- | --- |
| `upc` | yes | | UPC-A, UPC-E, EAN-13 or PLU code |
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

### `kroger_restock.add_item`

Adds an item by name (`name`, `quantity`, `source`). Same response shape. If
the item needs review, the response includes `candidates`.

### `kroger_restock.resolve_item`

Fixes an `unmatched` or `needs_review` item: `item_id`, plus `product_id`
(the 13-digit Kroger product ID, or a UPC). The barcode is remembered.

### `kroger_restock.sync`

Pushes any `in_cart` items whose push is still pending (for example after a
network error). Returns `pushed`, `pending` and the items pushed. Units that
were already pushed are never sent again.

## Events

### `kroger_restock_scanned`

Fired after every scan or text add (not for debounced repeats).

| Key | Example |
| --- | --- |
| `result` | `in_cart`, `waiting`, `unmatched`, `needs_review` or `duplicate` |
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

## Options

**Settings → Devices & services → Kroger Restock → Configure**:

- **Change store** (by ZIP code)
- **Order type:** Pickup or Delivery
- **Scan debounce** (default 3 s)
- **Order days**, **lead time**, **stock check interval** (default 3 h),
  **give-up after** (default 30 days) and **notification targets** are saved
  now and used from Phase 2.

## Limitations

These come from Kroger's public API:

- **The cart is write-only.** The API can add to your cart but can't read it
  or remove from it. The integration keeps its own record of what it pushed.
  **If you remove or change items in the Kroger app or website, Home Assistant
  won't know.** Deleting an item from the Home Assistant list doesn't remove it
  from your Kroger cart either.
- **No Kroger Shopping List, order history or checkout.** You still place the
  order in the Kroger app or website.
- **Daily rate limits** apply per endpoint (about 10,000 product calls, 5,000
  cart calls and 1,600 location calls per day). The integration caches product
  lookups and barcode matches, checks duplicates before calling the API, and
  batches cart pushes. Call counts appear in diagnostics.
- **Stock levels are Kroger's estimate.** Items with no stock data are treated
  as available.
- Items typed in the to-do UI or spoken through Assist are recorded with
  source `manual`; use `add_item` with `source: assist` to tag them yourself.

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

## Development

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff format . && ruff check .
pytest
python script/gen_translations.py   # after editing strings.json
node script/render_icons.js         # after editing assets/*.svg
```

`tests/test_live_cart.py` is an optional, manual check against the real API
(it shows whether Kroger's cart accepts an out-of-stock UPC). It is skipped
unless `KROGER_LIVE_*` environment variables are set, and it adds one unit to
the real cart.

## Roadmap

1. ✅ **Core:** OAuth, store selection, API client, barcode normalization,
   storage, to-do list, `scan_upc` / `add_item` / `resolve_item` / `sync`,
   cart push, scan event, tests, CI
2. Stock re-checks, `held` and order-day window, give-up flag, notifications,
   `readd_item`, check-stock button
3. Printing: ESC/POS receipt printer and letter-size PDF over IPP
4. Blueprint, example automations, iOS Shortcut guide
5. ESPHome wall scanner

## License

[MIT](LICENSE)
