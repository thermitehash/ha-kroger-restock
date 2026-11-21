"""Printer-independent shopping-list layout shared by receipt and PDF."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
import unicodedata

from ..const import ItemStatus
from ..store import ListItem

OTHER_AISLE = "Other"
SECTION_WAITING = "Waiting — check shelf"
SECTION_REVIEW = "Needs review"

# Statuses printed in the aisle-grouped main list.
_MAIN_STATUSES = (ItemStatus.IN_CART, ItemStatus.HELD)
_REVIEW_STATUSES = (ItemStatus.NEEDS_REVIEW, ItemStatus.UNMATCHED)


@dataclass(frozen=True, slots=True)
class PrintLine:
    """One checkbox line."""

    name: str
    size: str | None
    quantity: int

    @property
    def text(self) -> str:
        """Return ``name (size) ×qty`` without the checkbox."""
        text = self.name
        if self.size:
            text += f" ({self.size})"
        if self.quantity > 1:
            text += f" ×{self.quantity}"
        return text


@dataclass(slots=True)
class PrintSection:
    """A titled group of lines."""

    title: str
    lines: list[PrintLine] = field(default_factory=list)


@dataclass(slots=True)
class PrintDocument:
    """Everything a printer needs."""

    title: str
    store: str
    printed_at: datetime
    sections: list[PrintSection]

    @property
    def item_count(self) -> int:
        """Number of lines across all sections."""
        return sum(len(s.lines) for s in self.sections)

    @property
    def date_label(self) -> str:
        """E.g. 'Sat Nov 21, 2026 3:05 PM'."""
        hour = self.printed_at.strftime("%I").lstrip("0") or "12"
        return (
            f"{self.printed_at:%a %b} {self.printed_at.day}, {self.printed_at:%Y} "
            f"{hour}:{self.printed_at:%M %p}"
        )

    @property
    def footer(self) -> str:
        """E.g. '12 items'."""
        count = self.item_count
        return f"{count} item" if count == 1 else f"{count} items"


def _line(item: ListItem) -> PrintLine:
    return PrintLine(name=item.name, size=item.size, quantity=item.quantity)


def _aisle_key(item: ListItem) -> tuple[int, int, str]:
    number = item.aisle_number
    try:
        return (0, int(str(number)), "")
    except TypeError, ValueError:
        pass
    if item.aisle_description:
        return (1, 0, item.aisle_description.casefold())
    return (2, 0, "")


def _aisle_title(item: ListItem) -> str:
    if item.aisle_number and item.aisle_number != "0":
        title = f"Aisle {item.aisle_number}"
        if item.aisle_description:
            title += f" · {item.aisle_description.title()}"
        return title
    if item.aisle_description:
        return item.aisle_description.title()
    return OTHER_AISLE


def build_document(
    items: Iterable[ListItem], store: str, printed_at: datetime
) -> PrintDocument:
    """Group active items by aisle, then the waiting and review sections."""
    items = list(items)
    main = [i for i in items if i.status in _MAIN_STATUSES]
    main.sort(key=lambda i: (_aisle_key(i), i.name.casefold()))
    sections: list[PrintSection] = []
    for item in main:
        title = _aisle_title(item)
        if not sections or sections[-1].title != title:
            sections.append(PrintSection(title))
        sections[-1].lines.append(_line(item))
    # Items without an aisle go last under "Other", even if sort put a
    # description-only aisle after them.
    other = [s for s in sections if s.title == OTHER_AISLE]
    sections = [s for s in sections if s.title != OTHER_AISLE] + other

    waiting = sorted(
        (i for i in items if i.status == ItemStatus.WAITING),
        key=lambda i: (_aisle_key(i), i.name.casefold()),
    )
    if waiting:
        sections.append(PrintSection(SECTION_WAITING, [_line(i) for i in waiting]))
    review = [i for i in items if i.status in _REVIEW_STATUSES]
    if review:
        sections.append(PrintSection(SECTION_REVIEW, [_line(i) for i in review]))
    return PrintDocument(
        title="Grocery list", store=store, printed_at=printed_at, sections=sections
    )


_REPLACEMENTS = {
    "×": "x",
    "—": "-",
    "–": "-",
    "·": "-",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "®": "(R)",
    "™": "(TM)",
}


def to_plain(text: str, encoding: str) -> str:
    """Transliterate ``text`` so it encodes cleanly in a legacy code page."""
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        decomposed = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in decomposed if not unicodedata.combining(c))
        text = text.encode(encoding, "replace").decode(encoding)
    return text
