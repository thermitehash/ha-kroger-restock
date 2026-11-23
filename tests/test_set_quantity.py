"""set_quantity, to-do ×N edits and "Undo +N"."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.kroger_restock.const import DOMAIN, ItemStatus

from .helpers import FakeKrogerApi, make_product

RANCH = "0001111085141"
EGGS = "0000000000033"
TODO = "todo.kroger_test_store"
PHONE = "notify.mobile_app_pixel"


async def call(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


@pytest.fixture
def products(fake_api: FakeKrogerApi) -> None:
    fake_api.add(make_product(RANCH, "Kroger Creamy Ranch Dressing", size="16 fl oz"))
    fake_api.add(make_product(EGGS, "Large Eggs", stock="TEMPORARILY_OUT_OF_STOCK"))


@pytest.fixture
async def phone(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> list[ServiceCall]:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.config_entries.async_update_entry(
        setup_integration,
        options={**setup_integration.options, "notify_targets": [PHONE]},
    )
    return calls


def coordinator(entry: MockConfigEntry):  # type: ignore[no-untyped-def]
    return entry.runtime_data.coordinator


async def test_not_pushed_just_changes_quantity(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    eggs = await call(hass, "scan_upc", product_id=EGGS, quantity=3)
    assert eggs["result"] == "waiting"
    result = await call(hass, "set_quantity", item_id=eggs["item_id"], quantity=1)
    assert result["result"] == "updated"
    assert (result["previous_quantity"], result["quantity"]) == (3, 1)
    assert result["kroger_cart_remove"] == 0
    assert "warning" not in result
    assert coordinator(setup_integration).get_item(eggs["item_id"]).quantity == 1
    await call(hass, "set_quantity", item_id=eggs["item_id"], quantity=4)
    assert coordinator(setup_integration).get_item(eggs["item_id"]).quantity == 4
    assert fake_api.cart_calls == []


async def test_raise_pushed_item_pushes_only_extra(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    ranch = await call(hass, "scan_upc", product_id=RANCH)
    result = await call(hass, "set_quantity", item_id=ranch["item_id"], quantity=3)
    assert result["pushed"] == 2
    assert fake_api.cart_lines == [(RANCH, 1), (RANCH, 2)]
    item = coordinator(setup_integration).get_item(ranch["item_id"])
    assert (item.quantity, item.pushed_quantity) == (3, 3)


async def test_lower_pushed_item_warns_and_lowers_record(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api,
    products,
    clock,
    phone: list[ServiceCall],
) -> None:
    ranch = await call(hass, "scan_upc", product_id=RANCH, quantity=3)
    result = await call(hass, "set_quantity", item_id=ranch["item_id"], quantity=1)
    await hass.async_block_till_done()
    assert result["kroger_cart_remove"] == 2
    assert result["warning"].startswith("Remove 2 from the Kroger app cart")
    item = coordinator(setup_integration).get_item(ranch["item_id"])
    assert (item.quantity, item.pushed_quantity) == (1, 1)
    assert fake_api.cart_lines == [(RANCH, 3)]  # no cart call for lowering
    [note] = phone
    assert note.data["title"] == "Kroger cart"
    assert "Remove 2 from the Kroger app cart" in note.data["message"]
    # Raising again later pushes from the lowered record.
    await call(hass, "set_quantity", item_id=ranch["item_id"], quantity=2)
    assert fake_api.cart_lines == [(RANCH, 3), (RANCH, 1)]


async def test_zero_removes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    eggs = await call(hass, "scan_upc", product_id=EGGS)
    ranch = await call(hass, "scan_upc", product_id=RANCH, quantity=2)
    result = await call(hass, "set_quantity", item_id=eggs["item_id"], quantity=0)
    assert result["result"] == "removed"
    assert "warning" not in result
    result = await call(hass, "set_quantity", item_id=ranch["item_id"], quantity=0)
    assert result["result"] == "removed"
    assert result["kroger_cart_remove"] == 2
    assert "Remove 2 from the Kroger app cart" in result["warning"]
    assert coordinator(setup_integration).items == []


async def test_by_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    ranch = await call(hass, "scan_upc", product_id=RANCH, quantity=2)
    await call(hass, "scan_upc", product_id=EGGS)
    result = await call(hass, "set_quantity", name="creamy ranch", quantity=1)
    assert result["item_id"] == ranch["item_id"]
    result = await call(
        hass, "set_quantity", name="Kroger Creamy Ranch Dressing", quantity=4
    )
    assert result["quantity"] == 4
    with pytest.raises(ServiceValidationError):
        await call(hass, "set_quantity", name="peanut butter", quantity=1)


async def test_check_cart_item_refused(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    ranch = await call(hass, "scan_upc", product_id=RANCH)
    coordinator(setup_integration).get_item(
        ranch["item_id"]
    ).status = ItemStatus.CHECK_CART
    with pytest.raises(ServiceValidationError):
        await call(hass, "set_quantity", item_id=ranch["item_id"], quantity=2)


async def test_todo_summary_quantity_edits(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api,
    products,
    clock,
    phone: list[ServiceCall],
) -> None:
    ranch = await call(hass, "scan_upc", product_id=RANCH, quantity=3)
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    summary = items[TODO]["items"][0]["summary"]
    assert summary == "Kroger Creamy Ranch Dressing (16 fl oz) ×3"

    async def rename(text: str) -> None:
        await hass.services.async_call(
            "todo",
            "update_item",
            {"entity_id": TODO, "item": ranch["item_id"], "rename": text},
            blocking=True,
        )
        await hass.async_block_till_done()

    await rename("Kroger Creamy Ranch Dressing (16 fl oz) ×1")
    item = coordinator(setup_integration).get_item(ranch["item_id"])
    assert (item.quantity, item.pushed_quantity) == (1, 1)
    assert "Remove 2 from the Kroger app cart" in phone[-1].data["message"]
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": TODO}, blocking=True, return_response=True
    )
    assert (
        items[TODO]["items"][0]["summary"] == "Kroger Creamy Ranch Dressing (16 fl oz)"
    )
    # No ×N: quantity unchanged.
    await rename("Kroger Creamy Ranch Dressing (16 fl oz)")
    assert item.quantity == 1
    await rename("Kroger Creamy Ranch Dressing ×0")
    assert coordinator(setup_integration).items == []
    assert fake_api.cart_lines == [(RANCH, 3)]


@pytest.fixture
async def scan_pushes(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> list[ServiceCall]:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            "notify_targets": [PHONE],
            "notify_scans": True,
        },
    )
    return calls


async def test_duplicate_push_has_undo_and_undo_works(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api,
    products,
    clock,
    scan_pushes: list[ServiceCall],
) -> None:
    await call(hass, "scan_upc", product_id=RANCH)
    clock[0] += 10
    dup = await call(hass, "scan_upc", product_id=RANCH)
    await hass.async_block_till_done()
    assert dup["result"] == "duplicate"
    assert dup["added"] == 1
    push = scan_pushes[-1]
    assert push.data["message"].startswith("↺ Already on list (qty 2)")
    assert push.data["data"]["tag"] == "kroger_restock_scan"
    [undo] = push.data["data"]["actions"]
    assert undo["title"] == "Undo +1"
    assert fake_api.cart_lines == [(RANCH, 1), (RANCH, 1)]

    hass.bus.async_fire("mobile_app_notification_action", {"action": undo["action"]})
    await hass.async_block_till_done()
    item = coordinator(setup_integration).get_item(dup["item_id"])
    assert item.quantity == 1
    assert "Remove 1 from the Kroger app cart" in scan_pushes[-1].data["message"]

    # A second tap does nothing (quantity no longer matches).
    hass.bus.async_fire("mobile_app_notification_action", {"action": undo["action"]})
    await hass.async_block_till_done()
    assert item.quantity == 1


async def test_undo_waiting_item_no_warning(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api,
    products,
    clock,
    scan_pushes: list[ServiceCall],
) -> None:
    await call(hass, "scan_upc", product_id=EGGS)
    clock[0] += 10
    dup = await call(hass, "scan_upc", product_id=EGGS, quantity=2)
    await hass.async_block_till_done()
    [undo] = scan_pushes[-1].data["data"]["actions"]
    assert undo["title"] == "Undo +2"
    count = len(scan_pushes)
    hass.bus.async_fire("mobile_app_notification_action", {"action": undo["action"]})
    await hass.async_block_till_done()
    assert coordinator(setup_integration).get_item(dup["item_id"]).quantity == 1
    assert len(scan_pushes) == count  # nothing to remove from the cart
    assert fake_api.cart_calls == []


async def test_first_scan_push_has_no_undo(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api,
    products,
    clock,
    scan_pushes: list[ServiceCall],
) -> None:
    await call(hass, "scan_upc", product_id=RANCH)
    await hass.async_block_till_done()
    assert "actions" not in scan_pushes[-1].data["data"]
