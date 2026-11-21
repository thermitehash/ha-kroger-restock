"""Match free-text item names (from emails or the user) to list items."""

from __future__ import annotations

import re

from .store import ListItem

MATCH_THRESHOLD = 0.6


def tokens(text: str) -> set[str]:
    """Lowercase word set with simple plural folding."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {
        w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if len(w) > 1
    }


def match_item(name: str, items: list[ListItem]) -> ListItem | None:
    """Return the one list item that clearly matches ``name``, else None.

    A match needs most of the words in ``name`` to appear in the item's brand
    and name. Ties are treated as ambiguous and return None.
    """
    wanted = tokens(name)
    if not wanted:
        return None
    scored: list[tuple[float, ListItem]] = []
    for item in items:
        have = tokens(f"{item.brand or ''} {item.name}")
        if not have:
            continue
        score = len(wanted & have) / len(wanted)
        if score >= MATCH_THRESHOLD:
            scored.append((score, item))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def split_names(text: str) -> list[str]:
    """Split "eggs, milk and bread" into ["eggs", "milk", "bread"]."""
    parts = re.split(r"[,;\n]|\band\b|&|\+", text, flags=re.I)
    return [p.strip(" .") for p in parts if p.strip(" .")]
