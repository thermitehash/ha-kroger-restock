"""Order email parser tests.

``kroger_*`` fixtures are real Kroger emails with personal details replaced
(see tests/fixtures/emails/README.md). ``synthetic_*`` fixtures are made up,
for out-of-stock items and substitutions, which no real sample shows yet.
"""

from __future__ import annotations

from datetime import date, time
import itertools
from pathlib import Path

import pytest

from custom_components.kroger_restock.order_email import (
    UPDATE_ONLY,
    OrderStatus,
    email_to_lines,
    is_kroger_sender,
    is_order_sender,
    parse_order_email,
)

FIXTURES = Path(__file__).parent / "fixtures" / "emails"
KROGER_SENDER = "email@e.krogermail.com"
DEVELOPER_SENDER = "krogerapisupport@e.krogermail.com"
ORDER_NUMBER = "1111222233334444555"
DELIVERY_ORDER_NUMBER = "3333444455556666777"

# Synthetic subjects in Kroger's patterns; two household first names.
SUBJECTS = {
    "confirmed": "Pickup Order Confirmed, Alex",
    "confirmed_old": "Order Confirmed,  Sam",  # double space, as seen
    "delivery_confirmed": "Order Confirmed,  Alex",  # same subject as the old pickup
    "ready": "Your Order is Ready for Pickup at 100 Main St Anytown OH 45000",
    "receipt": "Alex, Here’s Your Final Receipt. Tell Us How We Did with Your Order.",
    "receipt_sam": "Sam, Here’s Your Final Receipt. Tell Us How We Did with Your Order.",
    "instacart_receipt": (
        "Alex, Here's Your Final Receipt. Tell Us How We Did with Your Instacart Order."
    ),
    "developer": "Kroger Developers - verify your email address",
}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


CONFIRMED_TEXT = fixture("01_pickup_confirmed.txt")
CONFIRMED_OLD_TEXT = fixture("02_pickup_confirmed_old.txt")
DELIVERY_TEXT = fixture("03_delivery_confirmed.txt")
READY_TEXT = fixture("04_ready_literal_html.txt")
READY_HTML = READY_TEXT  # alias used by older tests
RECEIPT_TEXT = fixture("05_pickup_receipt.txt")
INSTACART_RECEIPT_TEXT = fixture("06_instacart_receipt.txt")
DEVELOPER_TEXT = fixture("07_developer_verify.txt")
SHORTED_HTML = fixture("synthetic_ready_shorted.html")
CHANGES_TEXT = fixture("synthetic_changes.txt")


# --- Kroger email patterns (synthetic fixtures 1-8) ---------------------------


def test_pickup_confirmed_current() -> None:
    parsed = parse_order_email(SUBJECTS["confirmed"], CONFIRMED_TEXT)
    assert parsed.status == OrderStatus.PLACED
    assert parsed.order_number == ORDER_NUMBER
    assert parsed.window == "Mar 4, 2027 4:00pm–5:00pm"
    assert parsed.window_date == date(2027, 3, 4)
    assert (parsed.window_start, parsed.window_end) == (time(16, 0), time(17, 0))
    assert parsed.modality == "pickup"
    assert parsed.item_count == 12
    assert parsed.total == 48.75  # not the subtotal
    # "We'll notify you if substitutions are needed" is not a substitution
    # section, and the email has no item list: both unknown, not empty.
    assert parsed.substitutions is None
    assert parsed.shorted is None


def test_pickup_fee_takes_last_amount() -> None:
    """Fixture 8: "Pickup Fee | $4.95 $0.00 |" means the fee was waived."""
    assert parse_order_email(SUBJECTS["confirmed"], CONFIRMED_TEXT).fee == 0.0
    assert parse_order_email(SUBJECTS["confirmed_old"], CONFIRMED_OLD_TEXT).fee == 0.0
    assert parse_order_email(SUBJECTS["delivery_confirmed"], DELIVERY_TEXT).fee == 3.99


def test_pickup_confirmed_old_subject_double_space() -> None:
    parsed = parse_order_email(SUBJECTS["confirmed_old"], CONFIRMED_OLD_TEXT)
    assert parsed.status == OrderStatus.PLACED
    assert parsed.order_number == "2222333344445555666"
    assert parsed.modality == "pickup"  # from the body, not the subject
    assert parsed.window == "Oct 7, 2026 10:00am–11:00am"


def test_delivery_confirmed_same_subject_inline_order_number() -> None:
    parsed = parse_order_email(SUBJECTS["delivery_confirmed"], DELIVERY_TEXT)
    assert parsed.status == OrderStatus.PLACED
    assert parsed.order_number == DELIVERY_ORDER_NUMBER  # inline in a sentence
    assert parsed.modality == "delivery"  # DELIVERY DATE in the body
    assert parsed.window == "Nov 20, 2026 2:00pm–3:00pm"
    assert parsed.item_count == 5


def test_ready_with_literal_html_and_entities() -> None:
    parsed = parse_order_email(SUBJECTS["ready"], READY_TEXT)
    assert parsed.status == OrderStatus.READY
    assert parsed.order_number == ORDER_NUMBER  # value on the line after the label
    assert parsed.window == "Today 4:00pm–5:00pm"
    assert parsed.window_relative == "today"
    assert parsed.modality == "pickup"
    lines = email_to_lines(READY_TEXT)
    assert "We'll see you soon, Alex." in lines[0]  # &apos; unescaped
    assert "\u200c" not in "".join(lines)  # &zwnj; runs removed
    assert not any("<span" in line for line in lines)
    assert "PICK UP TODAY BETWEEN:" in lines and "ORDER NUMBER:" in lines


def test_pickup_receipt_curly_apostrophe() -> None:
    parsed = parse_order_email(SUBJECTS["receipt"], RECEIPT_TEXT)
    assert parsed.status == OrderStatus.COMPLETED
    assert parsed.order_number is None
    assert parsed.window is None
    assert parsed.modality is None


def test_instacart_receipt_straight_apostrophe() -> None:
    parsed = parse_order_email(SUBJECTS["instacart_receipt"], INSTACART_RECEIPT_TEXT)
    assert parsed.status == OrderStatus.COMPLETED
    assert parsed.order_number is None
    assert parsed.modality == "delivery"


def test_developer_email_is_not_order_mail() -> None:
    assert not is_order_sender(DEVELOPER_SENDER)
    assert is_kroger_sender(DEVELOPER_SENDER)  # right domain, wrong sender
    assert parse_order_email(SUBJECTS["developer"], DEVELOPER_TEXT).status is None


def test_order_sender() -> None:
    assert is_order_sender(KROGER_SENDER)
    assert is_order_sender(f"Kroger <{KROGER_SENDER}>")
    assert not is_order_sender("promo@e.krogermail.com")
    assert is_order_sender("orders@e.ralphsmail.com", ("ralphsmail.com",))
    assert is_order_sender("orders@e.ralphsmail.com", ("orders@e.ralphsmail.com",))
    assert not is_order_sender("other@e.ralphsmail.com", ("orders@e.ralphsmail.com",))


def test_confirmed_body_alone_classifies() -> None:
    """If the subject were unhelpful, the body's opening still says placed."""
    assert parse_order_email("", CONFIRMED_TEXT).status == OrderStatus.PLACED


# --- Subject rules ------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        *[
            (s, OrderStatus.PLACED)
            for s in (
                "Thanks for your order!",
                SUBJECTS["confirmed"],
                SUBJECTS["confirmed_old"],
            )
        ],
        ("We've started shopping your order", OrderStatus.SHOPPING),
        (SUBJECTS["ready"], OrderStatus.READY),
        ("Your groceries are on the way", OrderStatus.OUT_FOR_DELIVERY),
        ("Your order has been delivered", OrderStatus.COMPLETED),
        (SUBJECTS["receipt"], OrderStatus.COMPLETED),
        (SUBJECTS["instacart_receipt"], OrderStatus.COMPLETED),
        (SUBJECTS["developer"], None),
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
    assert parsed.order_number == "112233445566"  # inline "your order 1122..."
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


def test_three_kroger_email_shapes() -> None:
    """Confirmed, ready, final receipt: what each gives (and doesn't)."""
    confirmed = parse_order_email(SUBJECTS["confirmed"], CONFIRMED_TEXT)
    assert confirmed.status == OrderStatus.PLACED
    assert confirmed.order_number == "1111222233334444555"  # 19 digits
    assert confirmed.item_count == 12
    assert confirmed.window == "Mar 4, 2027 4:00pm–5:00pm"
    assert (confirmed.subtotal, confirmed.savings, confirmed.tax, confirmed.total) == (
        50.0,
        2.5,
        1.25,
        48.75,
    )
    ready = parse_order_email(SUBJECTS["ready"], READY_TEXT)
    assert ready.status == OrderStatus.READY
    assert ready.order_number == "1111222233334444555"
    assert ready.window is not None
    assert ready.item_count is None
    receipt = parse_order_email(SUBJECTS["receipt"], RECEIPT_TEXT)
    assert receipt.status == OrderStatus.COMPLETED
    assert (receipt.order_number, receipt.item_count, receipt.total) == (
        None,
        None,
        None,
    )
