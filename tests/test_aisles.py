"""Aisle labels and print groups from Kroger's aisleLocations."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kroger_restock.aisles import FRONT_OF_STORE, OTHER, locate
from custom_components.kroger_restock.const import DOMAIN

from .helpers import FakeKrogerApi, make_product


@pytest.mark.parametrize(
    ("number", "description", "label", "group"),
    [
        ("12", "AISLE 12", "Aisle 12", "Aisle 12"),
        ("12", "aisle 12", "Aisle 12", "Aisle 12"),
        ("12", None, "Aisle 12", "Aisle 12"),
        # Seen live: a checkout-lane item comes back as "aisle 300".
        ("300", "CHECKLANE 15", "Checklane 15", FRONT_OF_STORE),
        ("0", "CHECK LANE 3", "Check Lane 3", FRONT_OF_STORE),
        ("", "FRONT END", "Front End", FRONT_OF_STORE),
        ("99", "SEASONAL", "Seasonal", "Seasonal"),
        ("45", "ENDCAP 4", "Endcap 4", "Endcap 4"),
        ("12", "DAIRY", "Dairy", "Dairy"),
        ("0", None, None, OTHER),
        (None, None, None, OTHER),
    ],
)
def test_locate(
    number: str | None, description: str | None, label: str | None, group: str
) -> None:
    location = locate(number, description)
    assert location.label == label
    assert location.group == group


def test_sort_order() -> None:
    keys = [
        locate(*args).sort_key
        for args in (
            (None, None),
            ("300", "CHECKLANE 15"),
            ("99", "SEASONAL"),
            ("12", "AISLE 12"),
            ("3", "AISLE 3"),
        )
    ]
    assert sorted(keys) == [
        locate("3", "AISLE 3").sort_key,
        locate("12", "AISLE 12").sort_key,
        locate("99", "SEASONAL").sort_key,
        locate("300", "CHECKLANE 15").sort_key,
        locate(None, None).sort_key,
    ]


async def test_todo_shows_checklane_not_aisle_300(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(
        make_product(
            "0004000057979",
            "M&M's Peanut Chocolate Candy",
            aisle="300",
            aisle_description="CHECKLANE 15",
        )
    )
    result = await hass.services.async_call(
        DOMAIN,
        "scan_upc",
        {"upc": "0040000579793"},
        blocking=True,
        return_response=True,
    )
    assert result["aisle"] == "Checklane 15"
    items = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": "todo.kroger_test_store"},
        blocking=True,
        return_response=True,
    )
    assert items["todo.kroger_test_store"]["items"][0]["description"] == (
        "In cart · Checklane 15"
    )
