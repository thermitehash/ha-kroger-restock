# Decisions

Decisions made while building, each with a one-line reason. Newest first.

## v0.17.3: items added in the Kroger app

- **Reuse the existing order-email reading (HA's IMAP integration) instead of
  adding a second IMAP client.** Order tracking already reads only
  `email@e.krogermail.com`, parses order number, item count, window and totals,
  is off until an IMAP connection is linked, and auto-marks received items on
  the final receipt; a second mail connection would duplicate it.
- **Open the folder read-only (EXAMINE) on Kroger Restock's own IMAP
  connection** (the baseline). Every fetch already used `BODY.PEEK`; HA's IMAP
  integration's own polling uses SELECT but only ever PEEKs, and Kroger Restock
  never calls its seen/move/delete actions.
- **Stop storing and logging email subjects.** They contain first names (and the
  ready email the store address), beyond the allowed fields. `last_subject` →
  `last_email` (email kind); the order event's `subject` → `email`; stored
  subjects are dropped by a storage migration (1.8).
- **Kept the experimental shorted / substitution lists.** They hold product
  names, not personal data, have never appeared in real Kroger mail, and are
  covered by existing tests; removing them changes nothing in practice.
- **Also parse subtotal, savings and tax** ("totals" in the request); they're
  on the confirmation email and the order sensor shows them.
- **Reconcile once, when the confirmation arrives** (it's the only email with
  the item count), counting units pushed before the order was placed
  (in-cart, check-cart and pushing items).
- **Fire the event and notification at the final receipt, not at
  confirmation:** the message asks the user to scan items "when you unload",
  and `received_at` is part of the payload.
- **Fire once per order** (`untracked_reported_at`), so a receipt seen twice
  (another folder, restart) doesn't repeat it.
- **Units, not lines:** assume Kroger's "NUMBER OF ITEMS" counts units, matching
  how pushed quantities are counted. Unverified against a multi-quantity order.
- **Clamp at 0:** fewer items than pushed means removals in the app or
  shortages, which aren't "untracked".
- **Link pushed items to the order number** (`order_ref` on each item) at
  confirmation, so `kroger_restock_received` carries it even when the item is
  checked off by hand.
- **Sensor entity ID follows the device-name convention:**
  `sensor.<store>_untracked_items_in_last_order`, not
  `sensor.kroger_restock_untracked_items`, matching every other entity of the
  integration.
- **The notification respects "Notify on order updates";** the event always
  fires.
- **Keep a dated window label** when the ready email only says "Today …"
  (found while testing: the dated label was being replaced by one that goes
  stale the next day).
- **Patch release 0.17.3.**
