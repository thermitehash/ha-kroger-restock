"""Item lifecycle tests: scans, text adds, resolve, sync, check-off."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.kroger_restock.api import KrogerResponseError
from custom_components.kroger_restock.const import DOMAIN, EVENT_SCANNED, ItemStatus
from custom_components.kroger_restock.coordinator import KrogerRestockCoordinator

from .helpers import FakeKrogerApi, make_product

COKE_UPC = "049000028911"
COKE_ID = "0004900002891"
TODO = "todo.kroger_test_store"


def coordinator(entry: MockConfigEntry) -> KrogerRestockCoordinator:
    return entry.runtime_data.coordinator


async def scan(hass: HomeAssistant, upc: str, **kwargs: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN,
        "scan_upc",
        {"upc": upc, **kwargs},
        blocking=True,
        return_response=True,
    )


async def add(hass: HomeAssistant, name: str, **kwargs: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN,
        "add_item",
        {"name": name, **kwargs},
        blocking=True,
        return_response=True,
    )


@pytest.fixture
def coke(fake_api: FakeKrogerApi):
    return fake_api.add(
        make_product(
            COKE_ID,
            "Coca-Cola Classic Soda",
            brand="Coca-Cola",
            size="12 fl oz",
            aisle="7",
            aisle_description="AISLE 7",
        )
    )


# --- Scan ----------------------------------------------------------------


async def test_scan_in_stock_pushes_to_cart(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    events = async_capture_events(hass, EVENT_SCANNED)
    result = await scan(hass, COKE_UPC, source="shortcut")

    assert result["result"] == "in_cart"
    assert result["pushed"] is True
    assert result["name"] == "Coca-Cola Classic Soda"
    assert result["aisle"] == "Aisle 7"
    assert fake_api.cart_lines == [(COKE_ID, 1)]
    assert fake_api.cart_calls[0][0].modality == "PICKUP"
    item = coordinator(setup_integration).get_item(result["item_id"])
    assert item.status is ItemStatus.IN_CART
    assert item.source == "shortcut"
    assert item.cart_pushed_at is not None
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["result"] == "in_cart"
    assert events[0].data["source"] == "shortcut"
    assert events[0].data["aisle"] == "Aisle 7"
    assert events[0].data["price"] == 3.49

    state = hass.states.get(TODO)
    assert state is not None and state.state == "1"
    assert hass.states.get("sensor.kroger_test_store_in_cart").state == "1"


async def test_scan_out_of_stock_waits_and_is_not_pushed(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    fake_api.set_stock(COKE_ID, "TEMPORARILY_OUT_OF_STOCK")
    result = await scan(hass, COKE_UPC)
    assert result["result"] == "waiting"
    assert result["pushed"] is False
    assert fake_api.cart_calls == []
    item = coordinator(setup_integration).get_item(result["item_id"])
    assert item.status is ItemStatus.WAITING
    assert item.out_of_stock_since is not None
    assert hass.states.get("sensor.kroger_test_store_waiting_on_stock").state == "1"

    # Sync never pushes waiting items either.
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    assert fake_api.cart_calls == []


async def test_scan_low_stock_and_unknown_stock_are_pushed(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    fake_api.add(make_product("0000000000011", "Low thing", stock="LOW"))
    fake_api.add(make_product("0000000000022", "No inventory data", stock=None))
    assert (await scan(hass, "0000000000011"))["result"] == "in_cart"
    assert (await scan(hass, "0000000000022"))["result"] == "in_cart"
    assert len(fake_api.cart_lines) == 2


async def test_scan_unmatched_kept_on_list(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    events = async_capture_events(hass, EVENT_SCANNED)
    result = await scan(hass, "012345678905")
    assert result["result"] == "unmatched"
    item = coordinator(setup_integration).get_item(result["item_id"])
    assert item.status is ItemStatus.UNMATCHED
    assert item.name == "012345678905"
    assert fake_api.cart_calls == []
    # Tried rule 1 then the fallback.
    assert fake_api.product_calls == ["0001234567890", "0012345678905"]
    await hass.async_block_till_done()
    assert events[0].data["result"] == "unmatched"
    assert hass.states.get("sensor.kroger_test_store_unmatched").state == "1"


async def test_barcode_mapping_is_cached(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    # Product only exists under the fallback (full-code) candidate.
    fake_api.add(make_product("0049000028911", "Odd ID product"))
    result = await scan(hass, COKE_UPC)
    assert result["result"] == "in_cart"
    coord = coordinator(setup_integration)
    assert coord.data.barcode_cache[COKE_UPC] == "0049000028911"


async def test_plu_goes_to_review(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    fake_api.search_results["bananas"] = [
        make_product("0000000004011", "Banana", brand=None, size="1 lb"),
        make_product("0000000094011", "Organic Banana", brand=None, size="1 lb"),
    ]
    result = await scan(hass, "4011")
    assert result["result"] == "needs_review"
    assert result["name"] == "Bananas"
    assert len(result["candidates"]) == 2
    assert fake_api.product_calls == []
    assert fake_api.cart_calls == []


# --- Duplicates, debounce and no double pushes ----------------------------


async def test_debounce_ignores_rapid_repeat(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    events = async_capture_events(hass, EVENT_SCANNED)
    await scan(hass, COKE_UPC)
    clock[0] += 1.0
    second = await scan(hass, COKE_UPC)
    assert second == {"result": "duplicate", "debounced": True, "upc": COKE_UPC}
    item = coordinator(setup_integration).active_items[0]
    assert item.quantity == 1
    assert fake_api.cart_lines == [(COKE_ID, 1)]
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_duplicate_scan_after_window_bumps_quantity(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    events = async_capture_events(hass, EVENT_SCANNED)
    await scan(hass, COKE_UPC)
    clock[0] += 5
    result = await scan(hass, COKE_UPC)
    assert result["result"] == "duplicate"
    assert result["quantity"] == 2
    coord = coordinator(setup_integration)
    assert len(coord.active_items) == 1
    # Only the extra unit is pushed; the first unit is never re-sent.
    assert fake_api.cart_lines == [(COKE_ID, 1), (COKE_ID, 1)]
    assert coord.active_items[0].pushed_quantity == 2
    await hass.async_block_till_done()
    assert [e.data["result"] for e in events] == ["in_cart", "duplicate"]
    assert hass.states.get(TODO).attributes is not None


async def test_duplicate_of_waiting_item_does_not_push(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    fake_api.set_stock(COKE_ID, "TEMPORARILY_OUT_OF_STOCK")
    await scan(hass, COKE_UPC)
    clock[0] += 5
    result = await scan(hass, COKE_UPC)
    assert result["result"] == "duplicate"
    assert result["status"] == "waiting"
    assert fake_api.cart_calls == []


async def test_duplicate_detected_without_api_call(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    await scan(hass, COKE_UPC)
    calls = len(fake_api.product_calls)
    clock[0] += 5
    await scan(hass, COKE_UPC)
    assert len(fake_api.product_calls) == calls


async def test_sync_never_double_pushes(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    await scan(hass, COKE_UPC)
    for _ in range(3):
        result = await hass.services.async_call(
            DOMAIN, "sync", {}, blocking=True, return_response=True
        )
        assert result["pushed"] == 0
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.kroger_test_store_sync_now"},
        blocking=True,
    )
    assert fake_api.cart_lines == [(COKE_ID, 1)]


async def test_failed_push_is_retried_by_sync(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    fake_api.fail_cart = KrogerResponseError(500, "boom")
    result = await scan(hass, COKE_UPC)
    assert result["result"] == "in_cart"
    assert result["pushed"] is False
    assert "error" in result
    item = coordinator(setup_integration).get_item(result["item_id"])
    assert item.pushed_quantity == 0

    fake_api.fail_cart = None
    sync = await hass.services.async_call(
        DOMAIN, "sync", {}, blocking=True, return_response=True
    )
    assert sync["pushed"] == 1
    assert fake_api.cart_lines == [(COKE_ID, 1)]
    sync = await hass.services.async_call(
        DOMAIN, "sync", {}, blocking=True, return_response=True
    )
    assert sync["pushed"] == 0
    assert fake_api.cart_lines == [(COKE_ID, 1)]


# --- Text adds and resolve ------------------------------------------------


async def test_add_item_single_match_is_pushed(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    fake_api.search_results["greek yogurt"] = [
        make_product("0001111000001", "Kroger Plain Greek Yogurt", size="32 oz"),
        make_product("0001111000002", "Kroger Vanilla Yogurt", size="32 oz"),
    ]
    result = await add(hass, "Greek yogurt", quantity=2)
    assert result["result"] == "in_cart"
    assert result["product_id"] == "0001111000001"
    assert fake_api.cart_lines == [("0001111000001", 2)]


async def test_add_item_ambiguous_needs_review(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    fake_api.search_results["milk"] = [
        make_product("0001111041700", "Kroger 2% Reduced Fat Milk"),
        make_product("0001111041600", "Kroger Whole Milk"),
    ]
    result = await add(hass, "milk")
    assert result["result"] == "needs_review"
    assert [c["product_id"] for c in result["candidates"]] == [
        "0001111041700",
        "0001111041600",
    ]
    assert fake_api.cart_calls == []
    assert hass.states.get("sensor.kroger_test_store_needs_review").state == "1"


async def test_add_item_no_results_unmatched(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    result = await add(hass, "unobtainium")
    assert result["result"] == "unmatched"
    assert result["name"] == "unobtainium"


async def test_add_same_text_twice_bumps_quantity(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    await add(hass, "unobtainium")
    result = await add(hass, "Unobtainium")
    assert result["result"] == "duplicate"
    assert result["quantity"] == 2


async def test_resolve_needs_review(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    milk = make_product("0001111041700", "Kroger 2% Reduced Fat Milk")
    fake_api.add(milk)
    fake_api.search_results["milk"] = [
        milk,
        make_product("0001111041600", "Kroger Whole Milk"),
    ]
    added = await add(hass, "milk")
    result = await hass.services.async_call(
        DOMAIN,
        "resolve_item",
        {"item_id": added["item_id"], "product_id": "0001111041700"},
        blocking=True,
        return_response=True,
    )
    assert result["result"] == "in_cart"
    assert result["name"] == "Kroger 2% Reduced Fat Milk"
    assert fake_api.cart_lines == [("0001111041700", 1)]


async def test_resolve_unmatched_scan_remembers_barcode(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    scanned = await scan(hass, "012345678905")
    assert scanned["result"] == "unmatched"
    # Accepts a 12-digit UPC as the product ID too.
    result = await hass.services.async_call(
        DOMAIN,
        "resolve_item",
        {"item_id": scanned["item_id"], "product_id": COKE_UPC},
        blocking=True,
        return_response=True,
    )
    assert result["product_id"] == COKE_ID
    coord = coordinator(setup_integration)
    assert coord.data.barcode_cache["012345678905"] == COKE_ID

    # Check it off, then scanning the odd code again resolves directly.
    await coord.async_set_received(scanned["item_id"])
    clock[0] += 10
    again = await scan(hass, "012345678905")
    assert again["result"] == "in_cart"
    assert again["product_id"] == COKE_ID


async def test_resolve_into_existing_item_merges(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    await scan(hass, COKE_UPC)
    unmatched = await scan(hass, "012345678905")
    result = await hass.services.async_call(
        DOMAIN,
        "resolve_item",
        {"item_id": unmatched["item_id"], "product_id": COKE_ID},
        blocking=True,
        return_response=True,
    )
    assert result["result"] == "duplicate"
    assert result["quantity"] == 2
    assert len(coordinator(setup_integration).active_items) == 1
    assert fake_api.cart_lines == [(COKE_ID, 1), (COKE_ID, 1)]


async def test_resolve_errors(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    in_cart = await scan(hass, COKE_UPC)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "resolve_item",
            {"item_id": in_cart["item_id"], "product_id": COKE_ID},
            blocking=True,
        )
    unmatched = await scan(hass, "012345678905")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "resolve_item",
            {"item_id": unmatched["item_id"], "product_id": "0000000000999"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "resolve_item",
            {"item_id": "nope", "product_id": COKE_ID},
            blocking=True,
        )


@pytest.mark.parametrize(
    "code",
    ["https://id.gs1.org/01/00049000028911", "(01)00049000028911(17)271231", "abc"],
)
async def test_qr_and_other_codes_are_ignored(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    code: str,
) -> None:
    events = async_capture_events(hass, EVENT_SCANNED)
    result = await scan(hass, code, source="shortcut")
    assert result == {
        "result": "ignored",
        "reason": "not_a_product_barcode",
        "message": (
            "Ignored a QR or non-product code - aim at the barcode and cover any "
            "QR code"
        ),
    }
    assert coordinator(setup_integration).items == []
    assert fake_api.product_calls == []
    await hass.async_block_till_done()
    # An event fires so ESPHome feedback can flash; no item is created.
    assert [e.data["result"] for e in events] == ["ignored"]
    assert events[0].data["source"] == "shortcut"


async def test_ignored_scan_notifies_when_configured(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    clock,
) -> None:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await scan(hass, "5088394_V2")  # a bag's QR code, as seen live
    await hass.async_block_till_done()
    assert calls == []  # no notify targets configured: response + event only

    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            "notify_targets": ["notify.mobile_app_pixel"],
        },
    )
    await scan(hass, "5088394_V2")
    await scan(hass, "https://example.com/recycle")  # within 30 s: not repeated
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["title"] == "Scan ignored"
    assert "cover any QR code" in calls[0].data["message"]
    clock[0] += 31
    await scan(hass, "5088394_V2")
    await hass.async_block_till_done()
    assert len(calls) == 2


# --- To-do entity ---------------------------------------------------------


async def get_items(hass: HomeAssistant) -> list[dict[str, Any]]:
    result = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    return result[TODO]["items"]


async def test_todo_summary_and_description(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    await scan(hass, COKE_UPC, quantity=3)
    fake_api.add(
        make_product(
            "0000000000033",
            "Eggs",
            size="12 ct",
            stock="TEMPORARILY_OUT_OF_STOCK",
            aisle=None,
        )
    )
    await scan(hass, "0000000000033")
    items = await get_items(hass)
    assert items[0]["summary"] == "Coca-Cola Classic Soda (12 fl oz) ×3"
    assert items[0]["description"] == "In cart · Aisle 7"
    assert items[1]["summary"] == "Eggs (12 ct)"
    assert items[1]["description"].startswith("Waiting on stock since ")


async def test_todo_create_does_text_search(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock,
) -> None:
    fake_api.search_results["milk"] = [
        make_product("0001111041700", "Kroger 2% Milk"),
        make_product("0001111041600", "Kroger Whole Milk"),
    ]
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": TODO, "item": "milk"}, blocking=True
    )
    items = await get_items(hass)
    assert items[0]["summary"] == "milk"
    assert items[0]["description"] == "Needs review · 2 possible matches"


async def test_check_off_marks_received_and_uncheck_repushes(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    scanned = await scan(hass, COKE_UPC)
    coord = coordinator(setup_integration)
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": scanned["item_id"], "status": "completed"},
        blocking=True,
    )
    item = coord.get_item(scanned["item_id"])
    assert item.status is ItemStatus.RECEIVED
    assert item.received_at is not None
    assert hass.states.get(TODO).state == "0"
    # Received items stay in storage but leave the active list.
    assert coord.active_items == []

    # A fresh scan after check-off is a new active item, not a duplicate.
    clock[0] += 10
    rescan = await scan(hass, COKE_UPC)
    assert rescan["result"] == "in_cart"
    assert rescan["item_id"] != scanned["item_id"]
    await coord.async_delete([rescan["item_id"]])

    # Uncheck = shorted at pickup: stock check and push again.
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": TODO, "item": scanned["item_id"], "status": "needs_action"},
        blocking=True,
    )
    assert item.status is ItemStatus.IN_CART
    assert item.received_at is None
    assert fake_api.cart_lines == [(COKE_ID, 1), (COKE_ID, 1), (COKE_ID, 1)]


async def test_uncheck_out_of_stock_goes_to_waiting(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    scanned = await scan(hass, COKE_UPC)
    coord = coordinator(setup_integration)
    await coord.async_set_received(scanned["item_id"])
    fake_api.set_stock(COKE_ID, "TEMPORARILY_OUT_OF_STOCK")
    await coord.async_readd(scanned["item_id"])
    assert coord.get_item(scanned["item_id"]).status is ItemStatus.WAITING
    assert fake_api.cart_lines == [(COKE_ID, 1)]


async def test_todo_edit_quantity_pushes_delta(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    scanned = await scan(hass, COKE_UPC)
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": TODO,
            "item": scanned["item_id"],
            "rename": "Coca-Cola Classic Soda (12 fl oz) ×3",
            "description": "In cart · Aisle 7\nget the cold ones",
        },
        blocking=True,
    )
    item = coordinator(setup_integration).get_item(scanned["item_id"])
    assert item.quantity == 3
    assert item.name == "Coca-Cola Classic Soda"
    assert item.note == "get the cold ones"
    assert fake_api.cart_lines == [(COKE_ID, 1), (COKE_ID, 2)]


async def test_todo_delete_and_move(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    a = await scan(hass, COKE_UPC)
    b = await add(hass, "unobtainium")
    c = await add(hass, "other thing")
    coord = coordinator(setup_integration)
    await coord.async_move(c["item_id"], None)
    assert [i.id for i in coord.items] == [c["item_id"], a["item_id"], b["item_id"]]
    await coord.async_move(c["item_id"], b["item_id"])
    assert [i.id for i in coord.items] == [a["item_id"], b["item_id"], c["item_id"]]
    await hass.services.async_call(
        "todo",
        "remove_item",
        {"entity_id": TODO, "item": [b["item_id"]]},
        blocking=True,
    )
    assert [i.id for i in coord.items] == [a["item_id"], c["item_id"]]


async def test_state_persists_across_reload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    coke,
    clock,
) -> None:
    await scan(hass, COKE_UPC)
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    coord = coordinator(setup_integration)
    assert len(coord.active_items) == 1
    assert coord.active_items[0].pushed_quantity == 1
    assert coord.data.barcode_cache[COKE_UPC] == COKE_ID
    # Still no double push after reload.
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    assert fake_api.cart_lines == [(COKE_ID, 1)]
