# Order email fixtures

`kroger_*` are real Kroger order emails (Kroger, pickup, November 2026),
transcribed from the rendered emails. `kroger_ready.html` is rebuilt as
simple HTML with the same text and line structure, to exercise the HTML path.
Personal details are replaced: customer name → "Alex",
store address → "100 Main St Anytown OH 45000", order number →
1234567890123456789, email addresses removed. Totals and item counts are
kept as received.

Subject lines are in `SUBJECTS` in `tests/test_order_email.py`.

`synthetic_*.txt` are made up, for features none of the real samples show yet
(out-of-stock items and substitutions). Replace them with redacted real
emails when available.
