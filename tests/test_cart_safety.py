"""Save-before-push crash safety, CHECK_CART recovery, and already_in_cart."""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kroger_restock.api import KrogerConnectionError
from custom_components.kroger_restock.const import DOMAIN, ItemStatus
from custom_components.kroger_restock.repairs import async_create_fix_flow

from .helpers import FakeKrogerApi, make_product

PB_UPC = "051500255162"
PB_ID = "0005150025516"
OOS = "TEMPORARILY_OUT_OF_STOCK"


def storage_key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}"


def coord(entry: MockConfigEntry):
    return entry.runtime_data.coordinator


async def scan(hass: HomeAssistant, upc: str = PB_UPC, **kwargs: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": upc, **kwargs}, blocking=True, return_response=True
    )


async def crash_after_cart_call(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    fake_api: FakeKrogerApi,
    hass_storage: dict[str, Any],
) -> str:
    """Scan, then restart HA from what was on disk during the cart call."""
    fake_api.add(make_product(PB_ID, "Jif Creamy Peanut Butter"))
    snapshot: dict[str, Any] = {}

    def at_cart_call(_items: Any) -> None:
        snapshot.update(copy.deepcopy(hass_storage[storage_key(entry)]))

    fake_api.on_cart = at_cart_call
    result = await scan(hass)
    fake_api.on_cart = None
    # Saved BEFORE the cart call, marked as in flight.
    [saved] = snapshot["data"]["items"]
    assert saved["status"] == "pushing"
    assert saved["pending_push"] == 1
    assert saved["pushed_quantity"] == 0

    # "Crash": the save after the 204 never happened.
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass_storage[storage_key(entry)] = snapshot
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return result["item_id"]


async def test_push_is_saved_first_and_recovered_after_crash(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    hass_storage: dict[str, Any],
    issue_registry: ir.IssueRegistry,
) -> None:
    item_id = await crash_after_cart_call(
        hass, setup_integration, fake_api, hass_storage
    )
    item = coord(setup_integration).get_item(item_id)
    assert item.status is ItemStatus.CHECK_CART
    assert len(fake_api.cart_lines) == 1
    issue_id = f"check_cart_{setup_integration.entry_id}_{item_id}"
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.is_fixable
    assert issue.translation_placeholders == {
        "name": "Jif Creamy Peanut Butter",
        "quantity": "1",
    }
    # Never pushed again automatically, not even by sync.
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    assert len(fake_api.cart_lines) == 1
    todo = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": "todo.kroger_test_store"},
        blocking=True,
        return_response=True,
    )
    assert todo["todo.kroger_test_store"]["items"][0]["description"].startswith(
        "May already be in your Kroger cart"
    )


@pytest.mark.parametrize(
    ("choice", "status", "cart_calls"),
    [("confirm", "in_cart", 1), ("push_again", "in_cart", 2), ("remove", None, 1)],
)
async def test_check_cart_fix_flow(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    hass_storage: dict[str, Any],
    issue_registry: ir.IssueRegistry,
    choice: str,
    status: str | None,
    cart_calls: int,
) -> None:
    item_id = await crash_after_cart_call(
        hass, setup_integration, fake_api, hass_storage
    )
    issue_id = f"check_cart_{setup_integration.entry_id}_{item_id}"
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    flow = await async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["menu_options"] == ["confirm", "push_again", "remove"]
    result = await getattr(flow, f"async_step_{choice}")()
    assert result["type"] == "create_entry"
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
    assert len(fake_api.cart_calls) == cart_calls
    coordinator = coord(setup_integration)
    if status is None:
        assert coordinator.items == []
    else:
        item = coordinator.get_item(item_id)
        assert item.status == status
        assert item.pushed_quantity == 1
        assert item.pending_push == 0


async def test_check_cart_item_action(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    hass_storage: dict[str, Any],
) -> None:
    item_id = await crash_after_cart_call(
        hass, setup_integration, fake_api, hass_storage
    )
    result = await hass.services.async_call(
        DOMAIN,
        "check_cart_item",
        {"item_id": item_id, "action": "confirm"},
        blocking=True,
        return_response=True,
    )
    assert result["status"] == "in_cart"
    assert result["pushed"] is False
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "check_cart_item",
            {"item_id": item_id, "action": "confirm"},
            blocking=True,
        )


async def test_no_response_from_kroger_asks_instead_of_retrying(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A timeout may still have added the item: flag it, don't retry blindly."""
    fake_api.add(make_product(PB_ID, "Jif Creamy Peanut Butter"))
    fake_api.fail_cart = KrogerConnectionError("timed out")
    result = await scan(hass)
    item = coord(setup_integration).get_item(result["item_id"])
    assert item.status is ItemStatus.CHECK_CART
    assert issue_registry.async_get_issue(
        DOMAIN, f"check_cart_{setup_integration.entry_id}_{item.id}"
    )
    fake_api.fail_cart = None
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    assert fake_api.cart_calls == []


# --- already_in_cart --------------------------------------------------------


async def test_scan_already_in_cart_records_without_cart_call(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product(PB_ID, "Jif Creamy Peanut Butter", stock=OOS))
    result = await scan(hass, already_in_cart=True)
    assert result["result"] == "in_cart"
    assert result["already_in_cart"] is True
    assert result["pushed"] is False
    item = coord(setup_integration).get_item(result["item_id"])
    assert item.status is ItemStatus.IN_CART  # even though Kroger says out of stock
    assert item.pushed_quantity == 1
    assert fake_api.cart_calls == []
    # Later scans add only the new unit; sync never pushes the recorded one.
    await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)
    assert fake_api.cart_calls == []


async def test_already_in_cart_duplicate_is_recorded(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    clock: list[float],
) -> None:
    fake_api.add(make_product(PB_ID, "Jif Creamy Peanut Butter"))
    await scan(hass, already_in_cart=True)
    clock[0] += 10
    result = await scan(hass, already_in_cart=True)
    assert result["result"] == "duplicate"
    item = coord(setup_integration).get_item(result["item_id"])
    assert (item.quantity, item.pushed_quantity) == (2, 2)
    assert fake_api.cart_calls == []


async def test_add_item_already_in_cart_then_resolve(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    """A needs-review item added as already-in-cart is recorded when resolved."""
    jif = fake_api.add(make_product(PB_ID, "Jif Creamy Peanut Butter"))
    fake_api.search_results["peanut butter"] = [
        jif,
        make_product("0001111000777", "Kroger Creamy Peanut Butter"),
    ]
    added = await hass.services.async_call(
        DOMAIN,
        "add_item",
        {"name": "peanut butter", "already_in_cart": True},
        blocking=True,
        return_response=True,
    )
    assert added["result"] == "needs_review"
    result = await hass.services.async_call(
        DOMAIN,
        "resolve_item",
        {"item_id": added["item_id"], "product_id": PB_ID},
        blocking=True,
        return_response=True,
    )
    assert result["status"] == "in_cart"
    assert result["already_in_cart"] is True
    assert fake_api.cart_calls == []


async def test_resolve_item_already_in_cart_flag(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product(PB_ID, "Jif Creamy Peanut Butter"))
    unmatched = await scan(hass, "012345678905")
    result = await hass.services.async_call(
        DOMAIN,
        "resolve_item",
        {"item_id": unmatched["item_id"], "product_id": PB_ID, "already_in_cart": True},
        blocking=True,
        return_response=True,
    )
    assert result["status"] == "in_cart"
    assert fake_api.cart_calls == []


async def test_storage_migrates_to_1_4(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    from custom_components.kroger_restock.store import RestockStore

    hass_storage["kroger_restock.m4"] = {
        "version": 1,
        "minor_version": 3,
        "key": "kroger_restock.m4",
        "data": {
            "items": [
                {
                    "id": "a",
                    "name": "Old",
                    "status": "in_cart",
                    "source": "scan",
                    "added_at": "2026-10-01T00:00:00+00:00",
                }
            ],
            "barcode_cache": {},
            "orders": [],
            "seen_emails": [],
        },
    }
    data = await RestockStore(hass, "m4").async_load()
    assert data.items[0].pending_push == 0
    assert data.items[0].already_in_cart is False
