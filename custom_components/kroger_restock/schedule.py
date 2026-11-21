"""Order-day window and stock-check spacing helpers (pure functions)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from .const import WEEKDAYS

# Never wait longer than this between two stock-check calls in one cycle.
MAX_SPACING_SECONDS = 30.0


def _weekday_numbers(order_days: Iterable[str]) -> list[int]:
    return sorted({WEEKDAYS.index(day) for day in order_days if day in WEEKDAYS})


def in_order_window(today: date, order_days: Iterable[str], lead_days: int) -> bool:
    """Return True if held items should be pushed today.

    The window opens ``lead_days`` days before an order day and lasts
    through the order day itself. With no order days there is no window
    (items are pushed as soon as they're back in stock).
    """
    days = _weekday_numbers(order_days)
    if not days:
        return False
    return any((day - today.weekday()) % 7 <= lead_days for day in days)


def next_window_start(
    today: date, order_days: Iterable[str], lead_days: int
) -> date | None:
    """Return the first day (today or later) on which held items get pushed."""
    days = _weekday_numbers(order_days)
    if not days:
        return None
    for offset in range(8):
        candidate = today + timedelta(days=offset)
        if in_order_window(candidate, days_to_keys(days), lead_days):
            return candidate
    return None  # pragma: no cover - unreachable with at least one order day


def days_to_keys(days: Iterable[int]) -> list[str]:
    """Convert weekday numbers back to keys."""
    return [WEEKDAYS[d] for d in days]


def check_spacing(interval_seconds: float, count: int) -> float:
    """Seconds to wait between stock-check calls so a cycle is spread out.

    Spreads the calls over a quarter of the interval, capped so a cycle
    never takes unreasonably long.
    """
    if count <= 1:
        return 0.0
    return min(MAX_SPACING_SECONDS, interval_seconds / 4 / count)


def waited_too_long(
    now: datetime,
    out_of_stock_since: datetime | None,
    snoozed_at: datetime | None,
    give_up_days: int,
) -> bool:
    """Return True if an item has waited longer than the give-up setting."""
    starts = [t for t in (out_of_stock_since, snoozed_at) if t is not None]
    if not starts:
        return False
    return now - max(starts) > timedelta(days=give_up_days)
