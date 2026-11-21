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

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
import html
from html.parser import HTMLParser
import re

# Sender domains of Kroger-family banners. Kroger's transactional order
# emails come from email@e.krogermail.com. More senders (domains or full
# addresses) can be added in the options.
KROGER_FAMILY_DOMAINS: frozenset[str] = frozenset(
    {
        "kroger.com",
        "krogermail.com",
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


# Kroger's mail domain also sends non-order mail (e.g. the developer portal's
# krogerapisupport@ verification email). For these domains only the listed
# local parts count as order mail.
ORDER_SENDER_LOCAL_PARTS: dict[str, frozenset[str]] = {
    "krogermail.com": frozenset({"email"}),
}
IGNORED_LOCAL_PARTS: frozenset[str] = frozenset({"krogerapisupport"})


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
            r"\byour (?:e-?)?receipt\b|\bfinal receipt\b",
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
# Instacart delivery confirmations: "We received your order 1234... and ..."
_ORDER_NUMBER_INLINE = re.compile(r"\border\s+#?\s*(\d{12,})\b", re.I)
_TIME = r"\d{1,2}(?::\d{2})?\s*[ap]\.?\s?m\.?"
# "between 4:00pm and 5:00pm", "3:00 PM - 4:00 PM", "3 pm to 4 pm"
_WINDOW = re.compile(rf"({_TIME})\s*(?:-|–|—|to|and)\s*({_TIME})", re.I)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_WEEKDAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?"
_DATE = re.compile(
    rf"\b(?:{_WEEKDAY}[\s,-]*)?{_MONTH}\s+\d{{1,2}}(?:,\s*\d{{4}})?\b|\btoday\b|\btomorrow\b",
    re.I,
)
_ITEM_COUNT = re.compile(r"\bnumber of items\s*:?\s*(\d+)", re.I)
# "Pickup Fee | $4.95 $0.00 |": a struck-through original then the actual
# charge, so the last amount on the line wins.
_FEE_LINE = re.compile(r"\b(?:pick[ -]?up|delivery|service) fee\b(.*)$", re.I)
_AMOUNT = re.compile(r"\$\s?([\d,]+\.\d{2})")
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad\u034f]")
_HTML_TAG = re.compile(r"<(?:html|body|div|table|tr|td|p|br|span|b|strong)\b", re.I)
_DELIVERY_BODY = re.compile(
    r"\bdelivery (?:date|address|window|time)\b|\bwill be delivered\b|"
    r"\binstacart\b|\bout for delivery\b",
    re.I,
)
_PICKUP_BODY = re.compile(
    r"\bpick[ -]?up (?:date|location|window|time|today)\b|"
    r"\bready for pick[ -]?up\b|\byour pick[ -]?up order\b|\bpick up today\b",
    re.I,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ),
        start=1,
    )
}
_TOTAL = re.compile(r"(?<![a-z])total\*?\s*:?\s*\$\s?([\d,]+\.\d{2})", re.I)

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
    # Structured window (local store time, no time zone in the email).
    window_date: date | None = None
    # "today" / "tomorrow" when the email says so instead of a date.
    window_relative: str | None = None
    window_start: time | None = None
    window_end: time | None = None
    modality: str | None = None
    # None means "this email had no such section" (unknown), [] means the
    # section was there but empty.
    shorted: list[str] | None = None
    substitutions: list[str] | None = None
    item_count: int | None = None
    total: float | None = None
    fee: float | None = None


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
    """Return the email body as clean lines.

    Handles HTML bodies, plain-text parts that contain literal HTML tags and
    entities (Kroger's "ready for pickup" email does), zero-width spacer
    characters (``&zwnj;`` runs), and markdown-style table pipes.
    """
    if _HTML_TAG.search(text):
        extractor = _TextExtractor()
        extractor.feed(text)
        extractor.close()
        text = "".join(extractor.parts)
    else:
        text = html.unescape(text)
    text = _ZERO_WIDTH.sub("", text).replace("\xa0", " ")
    lines = [" ".join(line.replace("|", " ").split()) for line in text.splitlines()]
    # Collapse runs of blank lines to one.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return out


def _split_address(sender: str) -> tuple[str, str]:
    address = sender.strip().lower()
    if "<" in address:
        address = address.rpartition("<")[2]
    address = address.strip().rstrip(">")
    local, _, domain = address.rpartition("@")
    return local, domain


def _domain_match(domain: str, base: str) -> bool:
    return domain == base or domain.endswith(f".{base}")


def is_kroger_sender(sender: str, extra: tuple[str, ...] = ()) -> bool:
    """Return True if ``sender`` is at a Kroger-family domain (any local part)."""
    _local, domain = _split_address(sender)
    if not domain:
        return False
    domains = KROGER_FAMILY_DOMAINS | {
        d.strip().lower().lstrip("@") for d in extra if d and "@" not in d.strip("@")
    }
    return any(_domain_match(domain, d) for d in domains)


def is_order_sender(sender: str, extra: tuple[str, ...] = ()) -> bool:
    """Return True if ``sender`` sends Kroger order emails.

    ``extra`` may hold domains (``ralphsmail.com``) or full addresses
    (``orders@e.ralphsmail.com``); those are always accepted.
    """
    local, domain = _split_address(sender)
    if not domain or not local:
        return False
    address = f"{local}@{domain}"
    for item in extra:
        value = item.strip().lower()
        if "@" in value.strip("@"):
            if address == value:
                return True
        elif value and _domain_match(domain, value.lstrip("@")):
            return local not in IGNORED_LOCAL_PARTS
    if local in IGNORED_LOCAL_PARTS or not is_kroger_sender(sender):
        return False
    for base, allowed in ORDER_SENDER_LOCAL_PARTS.items():
        if _domain_match(domain, base):
            return local in allowed
    return True


def _parse_time(text: str) -> time | None:
    match = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([ap])", text.replace(".", ""), re.I)
    if not match:
        return None
    hour, minute = int(match.group(1)) % 12, int(match.group(2) or 0)
    if match.group(3).lower() == "p":
        hour += 12
    return time(hour, minute) if minute < 60 else None


def _parse_date(text: str) -> tuple[date | None, str | None]:
    """Return (date, relative) from a matched date label."""
    lowered = text.lower()
    if "today" in lowered:
        return None, "today"
    if "tomorrow" in lowered:
        return None, "tomorrow"
    match = re.search(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?", lowered)
    if not match or match.group(1) not in _MONTHS:
        return None, None
    year = int(match.group(3)) if match.group(3) else 1900  # 1900 = unknown year
    try:
        return date(year, _MONTHS[match.group(1)], int(match.group(2))), None
    except ValueError:
        return None, None


def _norm_time(text: str) -> str:
    return re.sub(r"[\s.]", "", text).lower()


@dataclass(slots=True)
class _Window:
    label: str
    start: time | None
    end: time | None
    day: date | None = None
    relative: str | None = None


def _find_window(lines: list[str]) -> _Window | None:
    """Find the pickup/delivery window, e.g. 'Mar 4, 2027 4:00pm–5:00pm'.

    Kroger writes the window as "between 4:00pm and 5:00pm", sometimes with
    the date on the same line and sometimes under a heading such as
    "PICK UP TODAY BETWEEN:". A window with a date is preferred.
    """
    first: _Window | None = None
    for index, line in enumerate(lines):
        match = _WINDOW.search(line)
        if not match:
            continue
        start, end = _parse_time(match.group(1)), _parse_time(match.group(2))
        times = f"{_norm_time(match.group(1))}–{_norm_time(match.group(2))}"
        for probe in (line, *reversed(lines[max(0, index - 2) : index])):
            if found := _DATE.search(probe):
                label = " ".join(found.group(0).replace(" - ", " ").split())
                if label.isupper():  # "PICK UP TODAY BETWEEN:"
                    label = label.title()
                day, relative = _parse_date(label)
                return _Window(
                    f"{label[0].upper()}{label[1:]} {times}", start, end, day, relative
                )
        first = first or _Window(times, start, end)
    return first


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


def _section(
    lines: list[str], header: re.Pattern[str], *, clean: bool
) -> list[str] | None:
    """Collect the lines under every heading matching ``header``.

    Returns None when no such heading exists, so callers can tell "no data"
    from "nothing listed".
    """
    if not any(header.match(line) for line in lines):
        return None
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
    match = _ORDER_NUMBER.search(f"{subject}\n{body}") or _ORDER_NUMBER_INLINE.search(
        body
    )
    if match:
        order_number = match.group(1).strip("-").upper()

    window = _find_window(lines)
    item_count = int(m.group(1)) if (m := _ITEM_COUNT.search(body)) else None
    total = float(m.group(1).replace(",", "")) if (m := _TOTAL.search(body)) else None
    fee = None
    for line in lines:
        if (m := _FEE_LINE.search(line)) and (amounts := _AMOUNT.findall(m.group(1))):
            fee = float(amounts[-1].replace(",", ""))
            break

    # Pickup vs delivery comes from the body: Kroger uses the same subject
    # ("Order Confirmed, <name>") for both. Only "Instacart" in a subject
    # (the delivery receipt) is trusted.
    modality = None
    if (
        status == OrderStatus.OUT_FOR_DELIVERY
        or _DELIVERY_BODY.search(body)
        or re.search(r"\binstacart\b", subject or "", re.I)
    ):
        modality = "delivery"
    elif status == OrderStatus.READY or _PICKUP_BODY.search(body):
        modality = "pickup"

    return OrderEmail(
        status=status,
        order_number=order_number,
        window=window.label if window else None,
        window_date=window.day if window else None,
        window_relative=window.relative if window else None,
        window_start=window.start if window else None,
        window_end=window.end if window else None,
        fee=fee,
        modality=modality,
        shorted=_section(lines, _SHORTED_HEADER, clean=True),
        substitutions=_section(lines, _SUBSTITUTION_HEADER, clean=False),
        item_count=item_count,
        total=total,
    )
