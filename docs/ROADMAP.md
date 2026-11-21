# Roadmap

Planned work that is **not built yet**. Nothing here is in the integration.

## Learned name → product matching

Typed, spoken and imported items ("flour", "milk") usually land in
`needs_review`, because a catalog search returns many plausible products.

- When the user resolves a text item with `resolve_item`, remember the
  normalized name → product ID, the same way barcode fixes are remembered.
- Next time the same name is added, use the remembered product directly
  (still subject to the stock check).
- Show learned mappings in diagnostics; add a way to forget one.

This should come first: it makes every text source better (typing, Assist,
and Tandoor below).

## Tandoor Recipes connector

Pull the household's Tandoor shopping list into Kroger Restock.

**Why Tandoor specifically (not just "any to-do list"):** Tandoor's shopping
list API returns structured entries (food, amount, unit, supermarket
category) instead of free text, which makes product matching much better
than parsing "2 cups flour". Tandoor's supermarket categories can also fill in
an aisle for products Kroger has no aisle data for.

Plan:

- Options flow page "Tandoor": server URL + API token (stored in the config
  entry; redacted in diagnostics).
- Poll `GET /api/shopping-list-entry/?checked=false` on an interval (default
  15 min). Confirm endpoint names and filters against the user's Tandoor
  version first; the API changed in Tandoor 2.x.
- For each new entry (tracked by Tandoor entry ID): `add_item` with the food
  name, `source: tandoor`, and quantity from the amount when the unit is a
  count. Use learned matches (above) to skip review.
- When an item is checked off in Home Assistant (`received`), check the entry
  off in Tandoor (`PATCH .../shopping-list-entry/{id}/` with `checked: true`).
- Two-way deletes are out of scope at first; deleting in HA doesn't delete in
  Tandoor.
- Tests with a mocked Tandoor API.

Alternative considered: a generic "import from any to-do entity" feature
(covers Bring!, Local To-do, a Tandoor HACS integration). Less code, but it
loses amount/unit/category.

## Smaller ideas

- Read the GTIN out of GS1 Digital Link QR codes
  (`https://id.gs1.org/01/<gtin>/…`) instead of ignoring them.
- ~~Mark in-cart items received after pickup~~: done in 0.7.0 as a
  confirmation prompt (actionable notification + `mark_cart_received`); never
  automatic, since receipts don't list items.
- Re-enable automatic re-adding of shorted items once a real Kroger email
  with item-level shortage or substitution data has been seen (disabled in
  0.7.0; none exists in a year of sample mail).
- **Parked:** anything beyond the manual `already_in_cart: true` recording
  added in 0.9.0 (e.g. a dedicated "Already in cart" Shortcut or button).
  The public API still can't read the cart, so recording stays manual.
