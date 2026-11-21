"""Printer-independent shopping-list layout shared by receipt and PDF."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
import unicodedata

from ..aisles import OTHER, locate
from ..const import ItemStatus
from ..store import ListItem

OTHER_AISLE = OTHER
SECTION_WAITING = "Waiting — check shelf"
SECTION_REVIEW = "Needs review"

# Statuses printed in the aisle-grouped main list.
_MAIN_STATUSES = (
    ItemStatus.IN_CART,
    ItemStatus.HELD,
    ItemStatus.CHECK_CART,
    ItemStatus.PUSHING,
)
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
    return locate(item.aisle_number, item.aisle_description).sort_key


def _aisle_title(item: ListItem) -> str:
    return locate(item.aisle_number, item.aisle_description).group


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
