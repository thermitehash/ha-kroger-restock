"""Order-window and spacing helper tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from custom_components.kroger_restock.schedule import (
    MAX_SPACING_SECONDS,
    check_spacing,
    in_order_window,
    next_window_start,
    waited_too_long,
)

WED = date(2026, 11, 18)
THU = date(2026, 11, 19)
FRI = date(2026, 11, 20)
SAT = date(2026, 11, 21)
SUN = date(2026, 11, 22)


@pytest.mark.parametrize(
    ("today", "lead", "expected"),
    [
        (WED, 1, False),
        (THU, 1, False),
        (FRI, 1, True),
        (SAT, 1, True),
        (SUN, 1, False),
        (FRI, 0, False),
        (SAT, 0, True),
        (WED, 3, True),
    ],
)
def test_in_order_window(today: date, lead: int, expected: bool) -> None:
    assert in_order_window(today, ["sat"], lead) is expected


def test_no_order_days_means_no_window() -> None:
    assert in_order_window(SAT, [], 1) is False
    assert next_window_start(SAT, [], 1) is None


def test_multiple_order_days() -> None:
    assert in_order_window(WED, ["tue", "sat"], 1) is False
    assert in_order_window(date(2026, 11, 16), ["tue", "sat"], 1) is True  # Mon


def test_next_window_start() -> None:
    assert next_window_start(WED, ["sat"], 1) == FRI
    assert next_window_start(FRI, ["sat"], 1) == FRI
    assert next_window_start(SUN, ["sat"], 0) == SAT + timedelta(days=7)


def test_check_spacing() -> None:
    assert check_spacing(10_800, 0) == 0
    assert check_spacing(10_800, 1) == 0
    assert check_spacing(10_800, 1000) == pytest.approx(2.7)
    assert check_spacing(10_800, 2) == MAX_SPACING_SECONDS


def test_waited_too_long() -> None:
    now = datetime(2026, 11, 21, tzinfo=UTC)
    assert not waited_too_long(now, None, None, 30)
    assert not waited_too_long(now, now - timedelta(days=29), None, 30)
    assert waited_too_long(now, now - timedelta(days=31), None, 30)
    # Snoozing restarts the clock.
    assert not waited_too_long(
        now, now - timedelta(days=60), now - timedelta(days=5), 30
    )
