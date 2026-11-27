"""lookup_product (read-only), kroger_restock_received and recent_received."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.kroger_restock.api import KrogerRateLimitError, Product
from custom_components.kroger_restock.barcode import barcode_from_product_id
from custom_components.kroger_restock.const import DOMAIN, ItemStatus

from .helpers import FakeKrogerApi, make_product, product_payload

COKE_ID = "0004900002891"
COKE_UPC = "049000028911"
EGGS_ID = "0001111000101"
TODO = "todo.kroger_test_store"


def product_with_pictures() -> Product:
    data = product_payload(
        COKE_ID,
        "Coca-Cola Classic Soda",
        brand="Coca-Cola",
        size="12 fl oz",
        price=7.99,
    )
    data["images"] = [
        {
            "perspective": "back",
            "sizes": [{"size": "xlarge", "url": "https://img.example/back-xl.jpg"}],
        },
        {
            "perspective": "front",
            "featured": True,
            "sizes": [
                {"size": "thumbnail", "url": "https://img.example/front-thumb.jpg"},
                {"size": "xlarge", "url": "https://img.example/front-xl.jpg"},
                {"size": "medium", "url": "https://img.example/front-md.jpg"},
            ],
        },
    ]
    return Product.from_api(data)


async def lookup(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, "lookup_product", data, blocking=True, return_response=True
    )


async def call(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def test_barcode_from_product_id() -> None:
    assert barcode_from_product_id("0004900002891") == "049000028911"  # UPC-A
    assert barcode_from_product_id("0400638133393") == "4006381333931"  # EAN-13
    assert barcode_from_product_id(None) is None
    assert barcode_from_product_id("abc") is None


# ---------------------------------------------------------------------------
# lookup_product


async def test_lookup_returns_product_and_pictures_without_side_effects(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(product_with_pictures())
    scanned = async_capture_events(hass, f"{DOMAIN}_scanned")
    received = async_capture_events(hass, f"{DOMAIN}_received")
    todo_before = hass.states.get(TODO).state
    result = await lookup(hass, upc=COKE_UPC)
    assert result == {
        "found": True,
        "query": COKE_UPC,
        "cached": False,
        "product_id": COKE_ID,
        "upc": COKE_ID,
        "barcode": COKE_UPC,
        "name": "Coca-Cola Classic Soda",
        "brand": "Coca-Cola",
        "size": "12 fl oz",
        "aisle": "Aisle 12",
        "price": 7.99,
        "stock_level": "HIGH",
        "images": [
            {
                "perspective": "front",
                "size": "xlarge",
                "url": "https://img.example/front-xl.jpg",
            },
            {
                "perspective": "front",
                "size": "medium",
                "url": "https://img.example/front-md.jpg",
            },
            {
                "perspective": "front",
                "size": "thumbnail",
                "url": "https://img.example/front-thumb.jpg",
            },
            {
                "perspective": "back",
                "size": "xlarge",
                "url": "https://img.example/back-xl.jpg",
            },
        ],
        "image_url": "https://img.example/front-xl.jpg",
    }
    await hass.async_block_till_done()
    coordinator = setup_integration.runtime_data.coordinator
    assert coordinator.items == []  # no list item
    assert fake_api.cart_calls == []  # no cart call
    assert hass.states.get(TODO).state == todo_before
    assert scanned == [] and received == []  # no events
    assert coordinator.data.recent == []


async def test_lookup_by_product_id(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product(EGGS_ID, "Large Brown Eggs"))
    result = await lookup(hass, product_id=EGGS_ID)
    assert result["found"] is True
    assert result["name"] == "Large Brown Eggs"
    assert result["image_url"] == f"https://img.example/{EGGS_ID}.jpg"
    assert (await lookup(hass, product_id="12345"))["reason"] == "invalid_product_id"


async def test_lookup_cache_hit_and_expiry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    fake_api.add(make_product(COKE_ID, "Coca-Cola"))
    first = await lookup(hass, upc=COKE_UPC)
    calls = len(fake_api.product_calls)
    assert first["cached"] is False
    second = await lookup(hass, upc=COKE_UPC)
    assert second["cached"] is True
    assert second["name"] == "Coca-Cola"
    assert len(fake_api.product_calls) == calls  # free
    # Survives a restart (persistent cache).
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert (await lookup(hass, upc=COKE_UPC))["cached"] is True
    # Expires after 7 days.
    freezer.tick(timedelta(days=7, minutes=1))
    setup_integration.runtime_data.coordinator._product_cache.clear()
    third = await lookup(hass, upc=COKE_UPC)
    assert third["cached"] is False
    assert len(fake_api.product_calls) > calls


async def test_lookup_not_found_plu_and_qr_never_search(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    assert await lookup(hass, upc="0123456789012") == {
        "found": False,
        "query": "0123456789012",
        "reason": "not_found",
    }
    assert (await lookup(hass, upc="4011"))["reason"] == "plu_code"
    assert (await lookup(hass, upc="https://example.com/qr"))["reason"] == (
        "not_a_product_barcode"
    )
    assert fake_api.search_calls == []  # never a fuzzy name search
    assert setup_integration.runtime_data.coordinator.items == []


async def test_lookup_rate_limited(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    async def limited(*_args: Any) -> None:
        raise KrogerRateLimitError("429")

    fake_api.async_get_product = limited  # type: ignore[method-assign]
    result = await lookup(hass, upc=COKE_UPC)
    assert result["found"] is False
    assert result["reason"] == "rate_limited"
    assert setup_integration.runtime_data.coordinator.data.lookup_cache == {}


async def test_lookup_is_response_only(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "lookup_product", {"upc": COKE_UPC}, blocking=True
        )


# ---------------------------------------------------------------------------
# kroger_restock_received


async def cart(hass: HomeAssistant, fake_api: FakeKrogerApi) -> dict[str, str]:
    fake_api.add(make_product(COKE_ID, "Coca-Cola", price=7.99))
    fake_api.add(make_product(EGGS_ID, "Large Brown Eggs", price=4.29))
    coke = await call(hass, "scan_upc", upc=COKE_UPC, quantity=2)
    eggs = await call(hass, "scan_upc", product_id=EGGS_ID)
    return {"coke": coke["item_id"], "eggs": eggs["item_id"]}


async def test_received_fires_per_item_and_skips_missing(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    ids = await cart(hass, fake_api)
    events = async_capture_events(hass, f"{DOMAIN}_received")
    await setup_integration.runtime_data.coordinator.async_mark_cart_received(
        missing=["eggs"], order_ref="112-123"
    )
    await hass.async_block_till_done()
    [event] = events
    data = event.data
    assert data["item_id"] == ids["coke"]
    assert data["quantity_received"] == 2
    assert data["upc"] == COKE_ID
    assert data["barcode"] == COKE_UPC  # the code as scanned
    assert data["product_id"] == COKE_ID
    assert data["name"] == "Coca-Cola"
    assert data["price"] == 7.99
    assert data["image_url"] == f"https://img.example/{COKE_ID}.jpg"
    assert data["order_ref"] == "112-123"
    assert data["received_at"]
    assert data["config_entry_id"] == setup_integration.entry_id


async def test_received_never_twice_for_the_same_units(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    ids = await cart(hass, fake_api)
    coordinator = setup_integration.runtime_data.coordinator
    events = async_capture_events(hass, f"{DOMAIN}_received")
    await coordinator.async_set_received(ids["eggs"])  # to-do check-off
    await hass.async_block_till_done()
    assert [e.data["item_id"] for e in events] == [ids["eggs"]]
    # Added by product ID: the barcode is rebuilt with its check digit.
    assert events[0].data["barcode"] == "011110001016"

    # Unchecked while out of stock: back to waiting, not pushed again...
    fake_api.set_stock(EGGS_ID, "TEMPORARILY_OUT_OF_STOCK")
    await coordinator.async_readd(ids["eggs"])
    assert coordinator.get_item(ids["eggs"]).status is ItemStatus.WAITING
    # ...so checking it off again reports nothing new.
    await coordinator.async_set_received(ids["eggs"])
    await hass.async_block_till_done()
    assert len(events) == 1

    # Re-added while in stock: pushed again = new units, reported once more.
    fake_api.set_stock(EGGS_ID, "HIGH")
    await coordinator.async_readd(ids["eggs"])
    assert coordinator.get_item(ids["eggs"]).status is ItemStatus.IN_CART
    await coordinator.async_set_received(ids["eggs"])
    await hass.async_block_till_done()
    assert [e.data["item_id"] for e in events] == [ids["eggs"], ids["eggs"]]


async def test_items_never_in_the_cart_are_not_reported(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.search_results["unobtainium"] = []
    added = await call(hass, "add_item", name="unobtainium")
    events = async_capture_events(hass, f"{DOMAIN}_received")
    await setup_integration.runtime_data.coordinator.async_set_received(
        added["item_id"]
    )
    await hass.async_block_till_done()
    assert events == []


async def test_recent_received_catch_up(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids = await cart(hass, fake_api)
    coordinator = setup_integration.runtime_data.coordinator
    await coordinator.async_set_received(ids["coke"])
    # Kept across a restart.
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert len((await call(hass, "recent_received"))["items"]) == 1
    coordinator = setup_integration.runtime_data.coordinator
    freezer.tick(timedelta(days=3))
    await coordinator.async_set_received(ids["eggs"])
    result = await call(hass, "recent_received")
    assert result["days"] == 14
    assert [i["item_id"] for i in result["items"]] == [ids["eggs"], ids["coke"]]
    assert result["items"][1]["quantity_received"] == 2
    assert [
        i["item_id"] for i in (await call(hass, "recent_received", days=2))["items"]
    ] == [ids["eggs"]]
    # Gone after 14 days.
    freezer.tick(timedelta(days=12))
    assert [i["item_id"] for i in (await call(hass, "recent_received"))["items"]] == [
        ids["eggs"]
    ]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "recent_received", {}, blocking=True)
