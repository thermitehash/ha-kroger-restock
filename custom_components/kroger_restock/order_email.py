"""Parse Kroger-family order emails into order status updates.

Kroger's public API has no order endpoints, so order status comes from the
emails Kroger sends (order placed, being shopped, ready for pickup / out for
delivery, completed, cancelled, changes). This module is pure Python and has
no Home Assistant dependencies, so the rules are easy to test and adjust
when Kroger changes its wording.

Parsing is deliberately conservative: an email we can't classify returns no
status, and the caller leaves the order unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from html.parser import HTMLParser
import re

# Sender domains of Kroger-family banners. Order emails come from these
# domains or their subdomains (e.g. email.kroger.com).
KROGER_FAMILY_DOMAINS: frozenset[str] = frozenset(
    {
        "kroger.com",
        "bakersplus.com",
        "citymarket.com",
        "dillons.com",
        "food4less.com",
        "foodsco.net",
        "fredmeyer.com",
        "frysfood.com",
        "gerbes.com",
        "harristeeter.com",
        "jaycfoods.com",
        "kingsoopers.com",
        "marianos.com",
        "metromarket.net",
        "pay-less.com",
        "picknsave.com",
        "qfc.com",
        "ralphs.com",
        "smithsfoodanddrug.com",
    }
)


class OrderStatus(StrEnum):
    """Order status shown by the order sensor."""

    NONE = "none"
    PLACED = "placed"
    SHOPPING = "shopping"
    READY = "ready"
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ACTIVE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PLACED,
        OrderStatus.SHOPPING,
        OrderStatus.READY,
        OrderStatus.OUT_FOR_DELIVERY,
    }
)

# A "changes to your order" email updates shorted items and substitutions
# without moving the order to a new status.
UPDATE_ONLY = "updated"

_APOS = "['’]"

# Checked in order against the subject first, then the opening of the body.
# Earlier rules win, so terminal states come first.
_STATUS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        OrderStatus.CANCELLED,
        re.compile(r"\bcancel(?:l)?(?:ed|ation)\b", re.I),
    ),
    (
        OrderStatus.COMPLETED,
        re.compile(
            r"\b(?:has been |was )?delivered\b|\bpicked up\b|"
            r"\bthanks? for (?:shopping|picking up)\b|\border (?:is )?complete\b|"
            r"\byour (?:e-?)?receipt\b",
            re.I,
        ),
    ),
    (
        OrderStatus.READY,
        re.compile(
            r"\bready for pick[ -]?up\b|\border is ready\b|\bready to pick up\b", re.I
        ),
    ),
    (
        OrderStatus.OUT_FOR_DELIVERY,
        re.compile(r"\bon (?:its|the) way\b|\bout for delivery\b|\bdriver\b", re.I),
    ),
    (
        OrderStatus.SHOPPING,
        re.compile(
            rf"\b(?:we{_APOS}re|we are|we{_APOS}ve started|started) shopping\b|"
            r"\bbeing (?:picked|prepared|shopped)\b|\bshopping your order\b",
            re.I,
        ),
    ),
    (
        UPDATE_ONLY,
        re.compile(
            r"\bsubstitut|\bout of stock\b|\bchanges? (?:to|in) your order\b|"
            r"\border (?:was |has been )?(?:updated|modified|changed)\b",
            re.I,
        ),
    ),
    (
        OrderStatus.PLACED,
        re.compile(
            rf"\border (?:is )?confirm|\bthanks? for (?:your|placing your) order\b|"
            rf"\bwe{_APOS}ve (?:got|received) your order\b|\border (?:has been )?placed\b|"
            r"\border (?:is )?scheduled\b",
            re.I,
        ),
    ),
)

_ORDER_NUMBER = re.compile(
    r"\border\s*(?:#|no\.?|number|num\.?)\s*:?\s*#?\s*([0-9][0-9A-Z-]{5,})", re.I
)
_TIME = r"\d{1,2}(?::\d{2})?\s*[ap]\.?\s?m\.?"
_WINDOW = re.compile(rf"{_TIME}\s*(?:-|–|—|to)\s*{_TIME}", re.I)
_MODALITY_DELIVERY = re.compile(r"\bdeliver", re.I)
_MODALITY_PICKUP = re.compile(r"\bpick[ -]?up\b", re.I)

_SHORTED_HEADER = re.compile(
    rf"^(?:out[ -]of[ -]stock(?: items?)?|unavailable(?: items?)?|"
    rf"items? (?:not available|unavailable)|not available|"
    rf"items? (?:we )?couldn{_APOS}?t (?:find|get|fill)|"
    rf"items? not (?:found|picked|filled)|missing items?|"
    rf"we (?:were )?(?:couldn{_APOS}?t|could not|weren{_APOS}?t able to) (?:find|get)\b.*)"
    rf"\s*:?\s*(?:\(\d+\))?$",
    re.I,
)
_SUBSTITUTION_HEADER = re.compile(
    r"^(?:substitut(?:ed|ion|ions)|items? substituted|replacements?)"
    r"(?: items?)?\s*:?\s*(?:\(\d+\))?$",
    re.I,
)
_SECTION_END = re.compile(
    r"^(?:sub-?total|total|order (?:summary|details|total)|estimated total|"
    r"items? (?:in your order|ordered|picked)|questions|need help|"
    r"payment|savings|view (?:your )?order|manage (?:your )?order|"
    r"pick[ -]?up (?:details|location|time)|delivery (?:details|address|time))\b",
    re.I,
)
_QTY_PREFIX = re.compile(r"^(?:qty:?\s*)?\d+\s*(?:x|×|ea\.?)?\s+", re.I)
_QTY_SUFFIX = re.compile(r"\s*(?:qty:?\s*\d+|x\s*\d+|×\s*\d+)\s*$", re.I)
_PRICE = re.compile(r"\s*-?\$\s?\d+(?:[.,]\d{2})?")
_JUNK_LINE = re.compile(r"^[\W\d_]*$")
_MAX_SECTION_LINES = 40


@dataclass(slots=True)
class OrderEmail:
    """What one email told us about an order."""

    status: str | None
    order_number: str | None = None
    window: str | None = None
    modality: str | None = None
    shorted: list[str] = field(default_factory=list)
    substitutions: list[str] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    """Turn an HTML email into lines of text."""

    _BLOCK = frozenset(
        {
            "br",
            "p",
            "div",
            "tr",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "table",
            "td",
            "th",
        }
    )
    _SKIP = frozenset({"style", "script", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def email_to_lines(text: str) -> list[str]:
    """Return the email body as stripped lines (HTML or plain text)."""
    if re.search(r"<(?:html|body|div|table|p|br)\b", text, re.I):
        extractor = _TextExtractor()
        extractor.feed(text)
        text = "".join(extractor.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    # Collapse runs of blank lines to one.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return out


def is_kroger_sender(sender: str) -> bool:
    """Return True if ``sender`` is an address at a Kroger-family domain."""
    domain = sender.rpartition("@")[2].strip().lower().rstrip(">")
    return any(domain == d or domain.endswith(f".{d}") for d in KROGER_FAMILY_DOMAINS)


def _classify(subject: str, lines: list[str]) -> str | None:
    for status, pattern in _STATUS_RULES:
        if pattern.search(subject):
            return str(status)
    opening = " ".join(lines[:12])[:600]
    for status, pattern in _STATUS_RULES:
        if pattern.search(opening):
            return str(status)
    return None


def _clean_item(line: str) -> str | None:
    text = _PRICE.sub("", line)
    text = _QTY_PREFIX.sub("", text)
    text = _QTY_SUFFIX.sub("", text).strip(" -•*·:\t")
    if len(text) < 3 or _JUNK_LINE.match(text):
        return None
    return text


def _section(lines: list[str], header: re.Pattern[str], *, clean: bool) -> list[str]:
    """Collect the lines under every heading matching ``header``."""
    found: list[str] = []
    index = 0
    while index < len(lines):
        if not header.match(lines[index]):
            index += 1
            continue
        index += 1
        blanks = 0
        taken = 0
        while index < len(lines) and taken < _MAX_SECTION_LINES:
            line = lines[index]
            if not line:
                blanks += 1
                if blanks >= 2 and taken:
                    break
                index += 1
                continue
            if (
                _SECTION_END.match(line)
                or _SHORTED_HEADER.match(line)
                or _SUBSTITUTION_HEADER.match(line)
            ):
                break
            blanks = 0
            value = _clean_item(line) if clean else line
            if value and value not in found:
                found.append(value)
                taken += 1
            index += 1
    return found


def parse_order_email(subject: str, text: str) -> OrderEmail:
    """Extract order status and details from one email."""
    lines = email_to_lines(text or "")
    body = "\n".join(lines)
    status = _classify(subject or "", lines)

    order_number = None
    if match := _ORDER_NUMBER.search(f"{subject}\n{body}"):
        order_number = match.group(1).strip("-").upper()

    window = None
    for line in lines:
        if _WINDOW.search(line):
            window = line[:100]
            break

    modality = None
    probe = f"{subject}\n{' '.join(lines[:20])}"
    if status == OrderStatus.OUT_FOR_DELIVERY or _MODALITY_DELIVERY.search(probe):
        modality = "delivery"
    elif status == OrderStatus.READY or _MODALITY_PICKUP.search(probe):
        modality = "pickup"

    return OrderEmail(
        status=status,
        order_number=order_number,
        window=window,
        modality=modality,
        shorted=_section(lines, _SHORTED_HEADER, clean=True),
        substitutions=_section(lines, _SUBSTITUTION_HEADER, clean=False),
    )
