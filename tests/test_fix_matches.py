"""Possible matches for the card's Fix pop-up: ranking, sensor, search, pick."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kroger_restock.const import DOMAIN, ItemStatus
from custom_components.kroger_restock.coordinator import rank_products

from .helpers import FakeKrogerApi, make_product

SENSOR = "sensor.kroger_test_store_recently_scanned"


async def call(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def milks() -> list:
    return [
        make_product("0001111041000", "Chocolate Milk", size="1/2 gal", aisle="5"),
        make_product("0001111041700", "2% Reduced Fat Milk", size="1 gal", price=2.99),
        make_product("0001111041600", "Whole Milk", size="1 gal"),
        make_product("0001111041800", "Skim Milk", size="1 gal"),
        make_product(
            "0001111041900",
            "Almond Milk",
            size="64 oz",
            stock="TEMPORARILY_OUT_OF_STOCK",
        ),
        make_product("0001111042000", "Lactose Free Milk", size="1/2 gal"),
        make_product("0001111042100", "Oat Milk", size="64 oz"),
    ]


def test_rank_closest_first_keeps_kroger_order_for_ties() -> None:
    products = [
        make_product("1", "Kroger Chocolate Milk", brand="Kroger"),
        make_product("2", "Whole Milk", brand="Kroger"),
        make_product("3", "Simple Truth Organic Whole Milk", brand="Simple Truth"),
    ]
    ranked = rank_products("whole milk", products)
    assert [p.product_id for p in ranked] == ["2", "3", "1"]
    assert rank_products("", products) == products


async def test_review_item_has_up_to_five_ranked_candidates_on_the_sensor(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.search_results["milk"] = milks()
    added = await call(hass, "add_item", name="milk")
    assert added["result"] == "needs_review"
    await hass.async_block_till_done()
    [row] = [
        i for i in hass.states.get(SENSOR).attributes["items"] if i["name"] == "milk"
    ]
    candidates = row["candidates"]
    assert len(candidates) == 5
    first = candidates[0]
    assert set(first) == {
        "product_id",
        "name",
        "brand",
        "size",
        "price",
        "image_url",
        "aisle",
        "in_stock",
    }
    assert first["aisle"] == "Aisle 5"
    assert first["price"] == 3.49
    almond = next(c for c in candidates if c["name"] == "Almond Milk")
    assert almond["in_stock"] is False


async def test_in_cart_items_have_no_candidates(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product("0004900002891", "Coca-Cola"))
    await call(hass, "scan_upc", upc="049000028911")
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["items"][0]["candidates"] == []


async def test_search_products_closest_first(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.search_results["skim milk"] = milks()
    result = await call(hass, "search_products", query="  skim   milk ")
    assert result["query"] == "skim milk"
    assert len(result["products"]) == 5
    assert result["products"][0]["name"] == "Skim Milk"
    result = await call(hass, "search_products", query="skim milk", limit=2)
    assert len(result["products"]) == 2
    fake_api.search_results["nothing"] = []
    assert (await call(hass, "search_products", query="nothing"))["products"] == []
    with pytest.raises(ServiceValidationError):
        await call(hass, "search_products", query="   ")
    assert fake_api.cart_calls == []


async def test_picking_a_candidate_resolves_and_pushes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    for p in milks():
        fake_api.add(p)
    fake_api.search_results["milk"] = milks()
    added = await call(hass, "add_item", name="milk", quantity=2)
    await hass.async_block_till_done()
    row = hass.states.get(SENSOR).attributes["items"][0]
    pick = next(c for c in row["candidates"] if c["name"] == "2% Reduced Fat Milk")
    result = await call(
        hass, "resolve_item", item_id=added["item_id"], product_id=pick["product_id"]
    )
    assert result["result"] == "in_cart"
    assert result["name"] == "2% Reduced Fat Milk"
    item = setup_integration.runtime_data.coordinator.get_item(added["item_id"])
    assert item.status is ItemStatus.IN_CART
    assert item.candidates == []
    assert fake_api.cart_lines == [("0001111041700", 2)]
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["items"][0]["candidates"] == []


async def test_needs_fix_lists_every_item_to_fix_oldest_first(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    for p in milks():
        fake_api.add(p)
    fake_api.search_results["milk"] = milks()
    fake_api.add(make_product("0004900002891", "Coca-Cola"))
    await hass.async_block_till_done()
    attrs = hass.states.get(SENSOR).attributes
    assert (attrs["needs_fix"], attrs["needs_fix_count"]) == ([], 0)

    milk = await call(hass, "add_item", name="milk")
    unknown = await call(hass, "add_item", name="unobtainium")
    # Push both out of the recent list: needs_fix still has them.
    for n in range(30):
        fake_api.search_results[f"thing {n}"] = []
        await call(hass, "add_item", name=f"thing {n}")
    await hass.async_block_till_done()
    attrs = hass.states.get(SENSOR).attributes
    recent_ids = {i["item_id"] for i in attrs["items"]}
    assert milk["item_id"] not in recent_ids
    assert attrs["needs_fix_count"] == 32
    first, second = attrs["needs_fix"][:2]
    assert (first["item_id"], second["item_id"]) == (
        milk["item_id"],
        unknown["item_id"],
    )
    assert len(first["candidates"]) == 5
    assert first["status"] == "needs_review"
    assert second["status"] == "unmatched"
    assert first["at"]

    await call(
        hass,
        "resolve_item",
        item_id=milk["item_id"],
        product_id=first["candidates"][0]["product_id"],
    )
    await hass.async_block_till_done()
    attrs = hass.states.get(SENSOR).attributes
    assert attrs["needs_fix_count"] == 31
    assert all(i["item_id"] != milk["item_id"] for i in attrs["needs_fix"])
