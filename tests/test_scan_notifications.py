"""'Notify on every scan': one short, replaceable push per scan."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.kroger_restock.const import DOMAIN

from .helpers import FakeKrogerApi, make_product

TARGET = "notify.mobile_app_pixel"


async def scan(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, "scan_upc", data, blocking=True, return_response=True
    )


@pytest.fixture
async def notified(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> list[ServiceCall]:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            "notify_targets": [TARGET],
            "notify_scans": True,
        },
    )
    return calls


async def test_one_tagged_push_per_scan(
    hass: HomeAssistant,
    notified: list[ServiceCall],
    fake_api: FakeKrogerApi,
    clock: list[float],
) -> None:
    fake_api.add(
        make_product(
            "0004900002891",
            "Coca-Cola",
            size="12 fl oz",
            aisle="7",
            aisle_description="AISLE 7",
        )
    )
    fake_api.add(
        make_product("0000000000033", "Eggs", stock="TEMPORARILY_OUT_OF_STOCK")
    )
    fake_api.search_results["milk"] = [
        make_product("0001111041700", "Kroger 2% Milk"),
        make_product("0001111041600", "Kroger Whole Milk"),
    ]
    await scan(hass, upc="049000028911")
    clock[0] += 10
    await scan(hass, upc="049000028911")
    await scan(hass, upc="0000000000033")
    await scan(hass, upc="012345678905")
    await scan(hass, upc="https://example.com/qr")
    await hass.services.async_call(
        DOMAIN, "add_item", {"name": "milk"}, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    messages = [c.data["message"] for c in notified]
    assert messages == [
        "✓ In cart: Coca-Cola 12 fl oz · Aisle 7",
        "↺ Already on list (qty 2): Coca-Cola",
        "⏳ Waiting on stock: Eggs",
        "? Unknown code 012345678905",
        "⊘ Ignored: aim at the barcode",
        "• Needs review: milk",
    ]
    # Same tag on every push, so rapid scans replace each other.
    assert {c.data["data"]["tag"] for c in notified} == {"kroger_restock_scan"}
    assert all("title" not in c.data for c in notified)


async def test_off_by_default(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.config_entries.async_update_entry(
        setup_integration,
        options={**setup_integration.options, "notify_targets": [TARGET]},
    )
    fake_api.add(make_product("0004900002891", "Coca-Cola"))
    await scan(hass, upc="049000028911")
    await hass.async_block_till_done()
    assert calls == []


async def test_recorded_and_link_messages(
    hass: HomeAssistant, notified: list[ServiceCall], fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product("0082415011716", "POM Arils", size="8 oz", aisle=None))
    await scan(hass, product_id="0082415011716", already_in_cart=True)
    await hass.services.async_call(
        DOMAIN,
        "add_item",
        {"url": "https://www.example.com/p/x/0082415011716"},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    assert [c.data["message"] for c in notified] == [
        "✓ In cart (recorded): POM Arils 8 oz",
        "⊘ Ignored: not a Kroger product link",
    ]
