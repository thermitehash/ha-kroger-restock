"""Order email parser tests.

``kroger_*`` fixtures are real Kroger emails with personal details replaced
(see tests/fixtures/emails/README.md). ``synthetic_*`` fixtures are made up,
for out-of-stock items and substitutions, which no real sample shows yet.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from custom_components.kroger_restock.order_email import (
    UPDATE_ONLY,
    OrderStatus,
    email_to_lines,
    is_kroger_sender,
    parse_order_email,
)

FIXTURES = Path(__file__).parent / "fixtures" / "emails"
KROGER_SENDER = "email@e.krogermail.com"
ORDER_NUMBER = "1234567890123456789"

SUBJECTS = {
    "confirmed": "Pickup Order Confirmed, Alex",
    "ready": "Your Order is Ready for Pickup at 100 Main St Anytown OH 45000",
    "receipt": "Alex, Here’s Your Final Receipt. Tell Us How We Did with Your Order.",
}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


CONFIRMED_TEXT = fixture("kroger_confirmed.txt")
READY_HTML = fixture("kroger_ready.html")
RECEIPT_TEXT = fixture("kroger_receipt.txt")
SHORTED_HTML = fixture("synthetic_ready_shorted.html")
CHANGES_TEXT = fixture("synthetic_changes.txt")


# --- Real Kroger emails -----------------------------------------------------


def test_real_confirmed() -> None:
    parsed = parse_order_email(SUBJECTS["confirmed"], CONFIRMED_TEXT)
    assert parsed.status == OrderStatus.PLACED
    assert parsed.order_number == ORDER_NUMBER
    assert parsed.window == "Mar 4, 2027 4:00pm–5:00pm"
    assert parsed.modality == "pickup"
    assert parsed.item_count == 12
    assert parsed.total == 48.75  # not the subtotal
    # "We'll notify you if substitutions are needed" is not a substitution.
    assert parsed.substitutions == []
    assert parsed.shorted == []


def test_real_ready() -> None:
    parsed = parse_order_email(SUBJECTS["ready"], READY_HTML)
    assert parsed.status == OrderStatus.READY
    assert parsed.order_number == ORDER_NUMBER  # number on the line after the label
    assert parsed.window == "Today 4:00pm–5:00pm"
    assert parsed.modality == "pickup"
    assert parsed.shorted == []


def test_real_receipt() -> None:
    parsed = parse_order_email(SUBJECTS["receipt"], RECEIPT_TEXT)
    assert parsed.status == OrderStatus.COMPLETED
    assert parsed.order_number is None  # Kroger's receipt email has none
    assert parsed.window is None


def test_real_sender() -> None:
    assert is_kroger_sender(KROGER_SENDER)
    assert is_kroger_sender(f"Kroger <{KROGER_SENDER}>")


def test_real_confirmed_body_alone_classifies() -> None:
    """If the subject were unhelpful, the body's opening still says placed."""
    assert parse_order_email("", CONFIRMED_TEXT).status == OrderStatus.PLACED


# --- Subject rules ------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        *[
            (s, OrderStatus.PLACED)
            for s in ("Thanks for your order!", SUBJECTS["confirmed"])
        ],
        ("We've started shopping your order", OrderStatus.SHOPPING),
        (SUBJECTS["ready"], OrderStatus.READY),
        ("Your groceries are on the way", OrderStatus.OUT_FOR_DELIVERY),
        ("Your order has been delivered", OrderStatus.COMPLETED),
        (SUBJECTS["receipt"], OrderStatus.COMPLETED),
        ("Your order has been cancelled", OrderStatus.CANCELLED),
        ("Changes to your order", UPDATE_ONLY),
        ("Weekly deals just for you", None),
        ("Digital coupons: save on snacks", None),
    ],
)
def test_classify_by_subject(subject: str, expected: str | None) -> None:
    assert parse_order_email(subject, "").status == expected


def test_cancelled_beats_other_words() -> None:
    assert (
        parse_order_email("Your pickup order has been cancelled", "").status
        == OrderStatus.CANCELLED
    )


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("between 4:00pm and 5:00pm", "4:00pm–5:00pm"),
        ("Pickup time: Sat, Nov 21 3:00 PM - 4:00 PM", "Sat, Nov 21 3:00pm–4:00pm"),
        ("Delivery window 10 a.m. to 11 a.m. tomorrow", "Tomorrow 10am–11am"),
    ],
)
def test_window_formats(line: str, expected: str) -> None:
    assert parse_order_email("Order confirmed", line).window == expected


# --- Synthetic: shorted items and substitutions -------------------------------


def test_synthetic_ready_with_shorted_and_substitutions() -> None:
    parsed = parse_order_email("Your order is ready for pickup!", SHORTED_HTML)
    assert parsed.status == OrderStatus.READY
    assert parsed.order_number == "112233445566"
    assert parsed.window == "Today 3:00pm–4:00pm"
    assert parsed.shorted == [
        "Simple Truth Organic Large Brown Eggs 12 ct",
        "Coca-Cola Classic Soda 12 pk",
    ]
    assert parsed.substitutions == ["Kroger Whole Milk 1 gal → Kroger 2% Milk 1 gal"]


def test_synthetic_changes_email() -> None:
    parsed = parse_order_email("Changes to your order", CHANGES_TEXT)
    assert parsed.status == UPDATE_ONLY
    assert parsed.order_number is None  # "order 1122..." without a label
    assert parsed.shorted == ["Häagen-Dazs Vanilla Ice Cream 14 oz", "Birthday Candles"]


def test_html_to_lines_drops_style_and_collapses_blanks() -> None:
    lines = email_to_lines(SHORTED_HTML)
    assert ".x{color:red}" not in "\n".join(lines)
    assert all(not (a == "" and b == "") for a, b in itertools.pairwise(lines))


@pytest.mark.parametrize(
    ("sender", "extra", "expected"),
    [
        ("orders@kroger.com", (), True),
        ("no-reply@email.kroger.com", (), True),
        ("Ralphs <orders@ralphs.com>", (), True),
        ("orders@harristeeter.com", (), True),
        ("orders@e.ralphsmail.com", (), False),
        ("orders@e.ralphsmail.com", ("ralphsmail.com",), True),
        ("someone@notkroger.com", (), False),
        ("kroger.com@phish.example", (), False),
        ("x@krogermail.com.evil.example", (), False),
        ("", (), False),
    ],
)
def test_is_kroger_sender(sender: str, extra: tuple[str, ...], expected: bool) -> None:
    assert is_kroger_sender(sender, extra) is expected
