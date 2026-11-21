"""Phase 2: stock checks, held items, order window, give-up, re-add."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.kroger_restock.const import (
    DOMAIN,
    EVENT_BACK_IN_STOCK,
    ItemStatus,
)
from custom_components.kroger_restock.coordinator import KrogerRestockCoordinator
from custom_components.kroger_restock.repairs import async_create_fix_flow
from custom_components.kroger_restock.store import RestockStore

from .helpers import FakeKrogerApi, make_product

COKE_UPC = "049000028911"
COKE_ID = "0004900002891"
OOS = "TEMPORARILY_OUT_OF_STOCK"
TODO = "todo.kroger_test_store"
WEDNESDAY = "2026-11-18 12:00:00-08:00"
FRIDAY = "2026-11-20 12:00:00-08:00"


@pytest.fixture(autouse=True)
async def set_time_zone(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("America/Los_Angeles")


def coord(entry: MockConfigEntry) -> KrogerRestockCoordinator:
    return entry.runtime_data.coordinator


async def set_options(
    hass: HomeAssistant, entry: MockConfigEntry, **options: Any
) -> KrogerRestockCoordinator:
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.async_block_till_done()
    return coord(entry)


async def scan_waiting(hass: HomeAssistant, fake_api: FakeKrogerApi) -> str:
    fake_api.add(make_product(COKE_ID, "Coca-Cola", size="12 fl oz", stock=OOS))
    result = await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": COKE_UPC}, blocking=True, return_response=True
    )
    assert result["result"] == "waiting"
    return result["item_id"]


async def check_stock(hass: HomeAssistant) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, "check_stock", {}, blocking=True, return_response=True
    )


async def test_back_in_stock_pushes_and_notifies(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    item_id = await scan_waiting(hass, fake_api)
    events = async_capture_events(hass, EVENT_BACK_IN_STOCK)

    result = await check_stock(hass)
    assert result["back_in_stock"] == 0
    assert result["still_waiting"] == 1
    assert fake_api.cart_calls == []

    fake_api.set_stock(COKE_ID, "LOW")
    result = await check_stock(hass)
    await hass.async_block_till_done()
    assert result["back_in_stock"] == 1
    assert [p["item_id"] for p in result["pushed"]] == [item_id]
    item = coord(setup_integration).get_item(item_id)
    assert item.status is ItemStatus.IN_CART
    assert item.out_of_stock_since is None
    assert fake_api.cart_lines == [(COKE_ID, 1)]
    assert events[0].data["pushed"][0]["name"] == "Coca-Cola"
    # No notify targets configured -> persistent notification.
    notifications = hass.states.async_all("persistent_notification")
    assert notifications or hass.data.get("persistent_notification")

    # A second check doesn't push again.
    await check_stock(hass)
    assert fake_api.cart_lines == [(COKE_ID, 1)]
    assert hass.states.get("sensor.kroger_test_store_last_stock_check").state not in (
        "unknown",
        None,
    )


async def test_notify_targets_are_called(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await set_options(
        hass, setup_integration, notify_targets=["notify.mobile_app_pixel"]
    )
    await scan_waiting(hass, fake_api)
    fake_api.set_stock(COKE_ID, "HIGH")
    await check_stock(hass)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["title"] == "Back in stock"
    assert "Coca-Cola" in calls[0].data["message"]


async def test_order_day_holds_then_pushes_in_window(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to(WEDNESDAY)
    coordinator = await set_options(
        hass, setup_integration, order_days=["sat"], lead_time_days=1
    )
    item_id = await scan_waiting(hass, fake_api)
    fake_api.set_stock(COKE_ID, "HIGH")

    result = await check_stock(hass)
    assert [h["item_id"] for h in result["held"]] == [item_id]
    item = coordinator.get_item(item_id)
    assert item.status is ItemStatus.HELD
    assert fake_api.cart_calls == []
    assert hass.states.get("sensor.kroger_test_store_held_for_order_day").state == "1"

    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    assert items[TODO]["items"][0]["description"] == (
        "Back in stock · cart push Fri 20 · Aisle 12"
    )

    # Hourly tick on Wednesday: still outside the window.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, seconds=1))
    await hass.async_block_till_done()
    assert fake_api.cart_calls == []

    # Friday is inside the window (Saturday order, 1 day lead).
    freezer.move_to(FRIDAY)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=1, seconds=1))
    await hass.async_block_till_done()
    assert item.status is ItemStatus.IN_CART
    assert fake_api.cart_lines == [(COKE_ID, 1)]


async def test_back_in_stock_inside_window_pushes_now(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to(FRIDAY)
    await set_options(hass, setup_integration, order_days=["sat"], lead_time_days=1)
    await scan_waiting(hass, fake_api)
    fake_api.set_stock(COKE_ID, "HIGH")
    result = await check_stock(hass)
    assert len(result["pushed"]) == 1
    assert fake_api.cart_lines == [(COKE_ID, 1)]


async def test_held_item_out_again_goes_back_to_waiting(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to(WEDNESDAY)
    coordinator = await set_options(
        hass, setup_integration, order_days=["sat"], lead_time_days=1
    )
    item_id = await scan_waiting(hass, fake_api)
    fake_api.set_stock(COKE_ID, "HIGH")
    await check_stock(hass)
    fake_api.set_stock(COKE_ID, OOS)
    freezer.move_to(FRIDAY)
    result = await coordinator.async_push_held()
    assert result["pushed"] == 0
    assert coordinator.get_item(item_id).status is ItemStatus.WAITING
    assert fake_api.cart_calls == []


async def test_scheduled_check_runs_on_interval(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = await set_options(hass, setup_integration, stock_check_hours=3)
    item_id = await scan_waiting(hass, fake_api)
    fake_api.set_stock(COKE_ID, "HIGH")
    freezer.tick(timedelta(hours=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.get_item(item_id).status is ItemStatus.WAITING
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.get_item(item_id).status is ItemStatus.IN_CART


async def test_give_up_raises_repair_and_keep_waiting(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    item_id = await scan_waiting(hass, fake_api)
    issue_id = f"gave_up_{setup_integration.entry_id}_{item_id}"
    freezer.tick(timedelta(days=29))
    await check_stock(hass)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    freezer.tick(timedelta(days=2))
    await check_stock(hass)
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Coca-Cola", "days": "31"}
    # Never removed automatically.
    assert coord(setup_integration).get_item(item_id).status is ItemStatus.WAITING

    flow = await async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["menu_options"] == ["keep_waiting", "remove"]
    result = await flow.async_step_keep_waiting()
    assert result["type"] == "create_entry"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
    item = coord(setup_integration).get_item(item_id)
    assert item.give_up_snoozed_at is not None
    assert item.status is ItemStatus.WAITING

    # Clock restarted: no new issue until another 30 days pass.
    freezer.tick(timedelta(days=5))
    await check_stock(hass)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_give_up_remove(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    item_id = await scan_waiting(hass, fake_api)
    issue_id = f"gave_up_{setup_integration.entry_id}_{item_id}"
    freezer.tick(timedelta(days=31))
    await check_stock(hass)
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    flow = await async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    await flow.async_step_remove()
    assert coord(setup_integration).items == []
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_give_up_issue_cleared_when_item_arrives(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    item_id = await scan_waiting(hass, fake_api)
    issue_id = f"gave_up_{setup_integration.entry_id}_{item_id}"
    freezer.tick(timedelta(days=31))
    await check_stock(hass)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is not None
    fake_api.set_stock(COKE_ID, "HIGH")
    await check_stock(hass)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_readd_item_action_repushes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product(COKE_ID, "Coca-Cola"))
    scanned = await hass.services.async_call(
        DOMAIN,
        "scan_upc",
        {"upc": COKE_UPC, "quantity": 2},
        blocking=True,
        return_response=True,
    )
    await coord(setup_integration).async_set_received(scanned["item_id"])
    result = await hass.services.async_call(
        DOMAIN,
        "readd_item",
        {"item_id": scanned["item_id"]},
        blocking=True,
        return_response=True,
    )
    assert result["result"] == "in_cart"
    assert result["pushed"] is True
    assert fake_api.cart_lines == [(COKE_ID, 2), (COKE_ID, 2)]


async def test_check_stock_button(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    item_id = await scan_waiting(hass, fake_api)
    fake_api.set_stock(COKE_ID, "HIGH")
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.kroger_test_store_check_stock_now"},
        blocking=True,
    )
    assert coord(setup_integration).get_item(item_id).status is ItemStatus.IN_CART


async def test_storage_migrates_from_1_1(hass: HomeAssistant, hass_storage) -> None:
    hass_storage["kroger_restock.abc"] = {
        "version": 1,
        "minor_version": 1,
        "key": "kroger_restock.abc",
        "data": {
            "items": [
                {
                    "id": "x1",
                    "name": "Old item",
                    "status": "waiting",
                    "source": "scan",
                    "added_at": "2026-10-01T00:00:00+00:00",
                }
            ],
            "barcode_cache": {"049000028911": COKE_ID},
        },
    }
    data = await RestockStore(hass, "abc").async_load()
    assert data.items[0].name == "Old item"
    assert data.items[0].give_up_snoozed_at is None
    assert data.barcode_cache == {"049000028911": COKE_ID}
