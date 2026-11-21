"""Turn Kroger's aisleLocations data into labels and print groups.

Kroger's ``number`` isn't always an aisle: an item at a checkout lane can
come back as number "300" with description "CHECKLANE 15". The description
is the reliable part, so:

- "AISLE 12" (or no description but a number) -> a numbered aisle,
- check lanes / registers / front end -> shown by description, grouped under
  "Front of store",
- any other description (seasonal, endcaps, departments) -> shown by
  description, grouped under that name.

Print order: numbered aisles, then named areas, then Front of store, then
items with no location ("Other").
"""

from __future__ import annotations

from dataclasses import dataclass
import re

AISLE_RE = re.compile(r"^\s*AISLE\s+(\d+)\s*$", re.I)
FRONT_RE = re.compile(
    r"\b(?:check\s*-?\s*lanes?|checkouts?|front\s*end|front\s+of\s+store|"
    r"registers?|self[\s-]*check(?:out)?)\b",
    re.I,
)
FRONT_OF_STORE = "Front of store"
OTHER = "Other"


@dataclass(frozen=True, slots=True)
class Location:
    """Where an item is, as shown on the list and printouts."""

    label: str | None  # e.g. "Aisle 12", "Checklane 15", "Seasonal"
    group: str  # print section title
    sort_key: tuple[int, int, str]


def _nice(text: str) -> str:
    """'CHECKLANE 15' -> 'Checklane 15' (word-wise, keeps apostrophes sane)."""
    return " ".join(word[:1].upper() + word[1:].lower() for word in text.split())


def locate(number: str | None, description: str | None) -> Location:
    """Classify an item's aisle data."""
    desc = (description or "").strip()
    if desc and (match := AISLE_RE.match(desc)):
        n = int(match.group(1))
        return Location(f"Aisle {n}", f"Aisle {n}", (0, n, ""))
    if not desc:
        try:
            n = int(str(number))
        except TypeError, ValueError:
            n = 0
        if n > 0:
            return Location(f"Aisle {n}", f"Aisle {n}", (0, n, ""))
        return Location(None, OTHER, (3, 0, ""))
    label = _nice(desc)
    if FRONT_RE.search(desc):
        return Location(label, FRONT_OF_STORE, (2, 0, label.casefold()))
    return Location(label, label, (1, 0, label.casefold()))
