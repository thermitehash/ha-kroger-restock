"""Order email parser tests.

The sample emails are SYNTHETIC, modelled on typical grocery order emails;
they are not copies of real Kroger emails. Replace or extend them with
redacted real samples when available.
"""

from __future__ import annotations

import itertools

import pytest

from custom_components.kroger_restock.order_email import (
    UPDATE_ONLY,
    OrderStatus,
    email_to_lines,
    is_kroger_sender,
    parse_order_email,
)

PLACED_TEXT = """
Thanks for your order!

Order #: 112233445566
Pickup time: Sat, Nov 21 between 3:00 PM - 4:00 PM
Kroger Downtown

Items in your order (14)
Kroger 2% Milk 1 gal   $3.49
"""

READY_HTML = """
<html><head><style>.x{color:red}</style></head><body>
<table><tr><td><h1>Your order is ready for pickup!</h1></td></tr>
<tr><td>Order Number: 112233445566</td></tr>
<tr><td>Pickup window: 3:00 pm &ndash; 4:00 pm today</td></tr>
<tr><td><h2>Out of Stock (2)</h2></td></tr>
<tr><td>1 x Simple Truth Organic Large Brown Eggs 12 ct</td></tr>
<tr><td>Coca-Cola Classic Soda 12 pk &nbsp; $7.99</td></tr>
<tr><td><h2>Substitutions</h2></td></tr>
<tr><td>Kroger Whole Milk 1 gal &rarr; Kroger 2% Milk 1 gal</td></tr>
<tr><td><h2>Order Summary</h2></td></tr>
<tr><td>Subtotal $54.20</td></tr>
</table></body></html>
"""

CHANGES_TEXT = """
Hi there,

We've made some changes to your order 112233445566.

Unavailable items:
Häagen-Dazs Vanilla Ice Cream 14 oz
Qty: 1 Birthday Candles


Questions? Visit our help center.
"""


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Thanks for your order!", OrderStatus.PLACED),
        ("Your order is confirmed", OrderStatus.PLACED),
        ("We've started shopping your order", OrderStatus.SHOPPING),
        ("Your order is ready for pickup", OrderStatus.READY),
        ("Your groceries are on the way", OrderStatus.OUT_FOR_DELIVERY),
        ("Your order has been delivered", OrderStatus.COMPLETED),
        ("Thanks for shopping with us - your receipt", OrderStatus.COMPLETED),
        ("Your order has been cancelled", OrderStatus.CANCELLED),
        ("Changes to your order", UPDATE_ONLY),
        ("Weekly deals just for you", None),
    ],
)
def test_classify_by_subject(subject: str, expected: str | None) -> None:
    assert parse_order_email(subject, "").status == expected


def test_cancelled_beats_other_words() -> None:
    assert (
        parse_order_email("Your pickup order has been cancelled", "").status
        == OrderStatus.CANCELLED
    )


def test_classify_falls_back_to_body_opening() -> None:
    parsed = parse_order_email(
        "An update from Kroger", "Your order is ready for pickup."
    )
    assert parsed.status == OrderStatus.READY


def test_placed_plain_text() -> None:
    parsed = parse_order_email("Order confirmation", PLACED_TEXT)
    assert parsed.status == OrderStatus.PLACED
    assert parsed.order_number == "112233445566"
    assert parsed.window == "Pickup time: Sat, Nov 21 between 3:00 PM - 4:00 PM"
    assert parsed.modality == "pickup"
    assert parsed.shorted == []


def test_ready_html_with_shorted_and_substitutions() -> None:
    parsed = parse_order_email("Your order is ready for pickup!", READY_HTML)
    assert parsed.status == OrderStatus.READY
    assert parsed.order_number == "112233445566"
    assert parsed.window == "Pickup window: 3:00 pm – 4:00 pm today"
    assert parsed.shorted == [
        "Simple Truth Organic Large Brown Eggs 12 ct",
        "Coca-Cola Classic Soda 12 pk",
    ]
    assert parsed.substitutions == ["Kroger Whole Milk 1 gal → Kroger 2% Milk 1 gal"]


def test_changes_email() -> None:
    parsed = parse_order_email("Changes to your order", CHANGES_TEXT)
    assert parsed.status == UPDATE_ONLY
    assert parsed.order_number is None  # "order 1122..." without a label
    assert parsed.shorted == ["Häagen-Dazs Vanilla Ice Cream 14 oz", "Birthday Candles"]


def test_html_to_lines_drops_style_and_collapses_blanks() -> None:
    lines = email_to_lines(READY_HTML)
    assert ".x{color:red}" not in "\n".join(lines)
    assert "" in lines
    assert all(not (a == "" and b == "") for a, b in itertools.pairwise(lines))


@pytest.mark.parametrize(
    ("sender", "expected"),
    [
        ("orders@kroger.com", True),
        ("no-reply@email.kroger.com", True),
        ("Ralphs <orders@ralphs.com>", True),
        ("orders@harristeeter.com", True),
        ("someone@notkroger.com", False),
        ("kroger.com@phish.example", False),
        ("", False),
    ],
)
def test_is_kroger_sender(sender: str, expected: bool) -> None:
    assert is_kroger_sender(sender) is expected
