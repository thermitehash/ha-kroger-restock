"""Adding by Kroger product ID or kroger.com product link."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.kroger_restock.const import DOMAIN, ItemStatus
from custom_components.kroger_restock.links import product_id_from_text

from .helpers import FakeKrogerApi, make_product

ARILS = "0082415011716"
LINK = f"https://www.kroger.com/p/pom-wonderful-pomegranate-arils-8-oz-2pk/{ARILS}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LINK, ARILS),
        (f"{LINK}?fulfillment=PICKUP&ref=share", ARILS),
        (f"{LINK}#reviews", ARILS),
        (f"{LINK}/", ARILS),
        (f"Check out POM Wonderful Arils on Kroger! {LINK}", ARILS),
        (f"https://kroger.com/p/item/{ARILS}", ARILS),
        (f"https://www.ralphs.com/p/pom-arils/{ARILS}", ARILS),
        (f"https://www.fredmeyer.com/p/pom-arils/{ARILS}?x=1", ARILS),
        ("https://www.example.com/p/pom-arils/0082415011716", None),
        ("https://www.kroger.com/weeklyad", None),
        ("https://www.kroger.com/p/pom-arils/12345", None),
        ("https://kroger.com.evil.example/p/x/0082415011716", None),
        ("no link here", None),
    ],
)
def test_product_id_from_text(text: str, expected: str | None) -> None:
    assert product_id_from_text(text).product_id == expected


async def call(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


@pytest.fixture
def arils(fake_api: FakeKrogerApi):
    return fake_api.add(
        make_product(ARILS, "POM Wonderful Pomegranate Arils", size="2 ct / 8 oz")
    )


async def test_scan_by_product_id_is_direct(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    arils,
) -> None:
    result = await call(hass, "scan_upc", product_id=ARILS, source="shortcut")
    assert result["result"] == "in_cart"
    assert result["product_id"] == ARILS
    # Looked up as-is: no EAN-13 "drop the check digit" candidate first.
    assert fake_api.product_calls == [ARILS]


@pytest.mark.parametrize(
    "url",
    [
        LINK,
        f"{LINK}?ref=share",
        f"{LINK}#x",
        f"Look at this: {LINK} (shared from Kroger)",
    ],
)
async def test_scan_and_add_by_link(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    arils,
    url: str,
) -> None:
    result = await call(hass, "add_item", url=url, source="shortcut")
    assert result["result"] == "in_cart"
    assert result["product_id"] == ARILS
    assert fake_api.product_calls == [ARILS]


async def test_link_in_the_barcode_field(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    arils,
) -> None:
    result = await call(hass, "scan_upc", upc=LINK)
    assert result["product_id"] == ARILS


async def test_non_kroger_link_is_ignored(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    result = await call(
        hass, "add_item", url="https://www.example.com/p/thing/0082415011716"
    )
    assert result == {
        "result": "ignored",
        "reason": "not_a_kroger_product_link",
        "message": "Ignored a link that isn't a Kroger product page",
    }
    assert fake_api.product_calls == []
    assert setup_integration.runtime_data.coordinator.items == []


async def test_product_id_with_already_in_cart(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    arils,
) -> None:
    result = await call(hass, "scan_upc", product_id=ARILS, already_in_cart=True)
    assert result["already_in_cart"] is True
    item = setup_integration.runtime_data.coordinator.get_item(result["item_id"])
    assert item.status is ItemStatus.IN_CART
    assert item.pushed_quantity == 1
    assert fake_api.cart_calls == []


async def test_bad_product_id_and_missing_fields(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await call(hass, "scan_upc", product_id="12345")
    with pytest.raises(vol.Invalid):
        await call(hass, "scan_upc", quantity=1)
    with pytest.raises(vol.Invalid):
        await call(hass, "add_item", quantity=1)
