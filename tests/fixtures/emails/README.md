# Order email fixtures (all synthetic)

Every file here is **hand-written** from the structural patterns of Kroger's
order emails (labels, line layout, HTML quirks). None is a copy of a real
email, and none contains real personal data: names are "Alex" / "Sam", the
store is "100 Main St Anytown OH 45000", order numbers and amounts are made
up.

| File | Pattern |
| --- | --- |
| `01_pickup_confirmed.txt` | "Pickup Order Confirmed, <name>": markdown-table pipes, labeled lines, struck-through pickup fee (`$4.95 $0.00`) |
| `02_pickup_confirmed_old.txt` | Older "Order Confirmed,  <name>" (double space) pickup format |
| `03_delivery_confirmed.txt` | Instacart delivery: same subject as 02, order number inline in a sentence, `DELIVERY DATE` |
| `04_ready_literal_html.txt` | "Ready for Pickup" plain-text part containing literal HTML tags, `&zwnj;` runs and `&apos;` |
| `05_pickup_receipt.txt` | Final receipt (curly apostrophe subject): survey/promo body, no order number |
| `06_instacart_receipt.txt` | Instacart final receipt (straight apostrophe subject) |
| `07_developer_verify.txt` | Kroger Developers verification email (must be ignored) |
| `synthetic_ready_shorted.html` | Invented out-of-stock + substitution sections (no real email has shown these) |
| `synthetic_changes.txt` | Invented "changes to your order" email |

Subjects and senders are defined in `tests/test_order_email.py`.
