"""Recently scanned list (sensor) and the scanner card registration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kroger_restock import (
    CARD_DIR,
    CARD_FILE,
    CARD_URL_BASE,
    _async_register_card,
)
from custom_components.kroger_restock.const import DOMAIN
from custom_components.kroger_restock.store import MAX_RECENT

from .helpers import FakeKrogerApi, make_product

SENSOR = "sensor.kroger_test_store_recently_scanned"
RANCH = "0001111085141"
EGGS = "0000000000033"


async def call(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def recent(hass: HomeAssistant) -> list[dict[str, Any]]:
    return hass.states.get(SENSOR).attributes["items"]


@pytest.fixture
def products(fake_api: FakeKrogerApi) -> None:
    fake_api.add(make_product(RANCH, "Creamy Ranch Dressing", size="16 fl oz"))
    fake_api.add(make_product(EGGS, "Large Eggs", stock="TEMPORARILY_OUT_OF_STOCK"))


async def test_newest_first_with_card_fields(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    assert hass.states.get(SENSOR).state == "unknown"
    assert recent(hass) == []
    await call(hass, "scan_upc", product_id=RANCH, source="card")
    await call(hass, "scan_upc", product_id=EGGS)
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "Large Eggs (1 gal)"
    items = state.attributes["items"]
    assert [i["name"] for i in items] == ["Large Eggs", "Creamy Ranch Dressing"]
    ranch = items[1]
    assert ranch["status"] == "in_cart"
    assert ranch["status_text"].startswith("In cart")
    assert ranch["source"] == "card"
    assert ranch["result"] == "in_cart"
    assert ranch["can_undo"] is False
    assert ranch["at"]
    assert state.attributes["config_entry_id"] == setup_integration.entry_id
    assert state.attributes["todo_entity_id"] == "todo.kroger_test_store"


async def test_duplicate_moves_to_top_and_can_undo(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    await call(hass, "scan_upc", product_id=RANCH)
    await call(hass, "scan_upc", product_id=EGGS)
    clock[0] += 10
    dup = await call(hass, "scan_upc", product_id=RANCH)
    await hass.async_block_till_done()
    items = recent(hass)
    assert [i["name"] for i in items] == ["Creamy Ranch Dressing", "Large Eggs"]
    assert items[0]["result"] == "duplicate"
    assert (items[0]["quantity"], items[0]["added"], items[0]["can_undo"]) == (
        2,
        1,
        True,
    )
    await call(hass, "set_quantity", item_id=dup["item_id"], quantity=1)
    await hass.async_block_till_done()
    assert recent(hass)[0]["can_undo"] is False  # quantity changed since


async def test_only_items_that_landed_on_the_list(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    await call(hass, "scan_upc", upc="https://example.com/qr")  # ignored
    await call(hass, "scan_upc", url="https://example.com/p/x/0001111085141")
    await call(hass, "scan_upc", product_id=RANCH)
    await call(hass, "scan_upc", product_id=RANCH)  # debounced
    await call(hass, "add_item", name="unobtainium")  # unmatched: on the list
    await hass.async_block_till_done()
    items = recent(hass)
    assert [i["result"] for i in items] == ["unmatched", "in_cart"]


async def test_removed_items_drop_out_and_list_is_capped(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    eggs = await call(hass, "scan_upc", product_id=EGGS)
    for n in range(MAX_RECENT + 3):
        await call(hass, "add_item", name=f"thing {n}")
    coordinator = setup_integration.runtime_data.coordinator
    assert len(coordinator.data.recent) == MAX_RECENT
    await call(hass, "scan_upc", product_id=RANCH)
    await call(hass, "set_quantity", item_id=eggs["item_id"], quantity=0)
    await hass.async_block_till_done()
    items = recent(hass)
    assert len(items) == MAX_RECENT
    assert items[0]["name"] == "Creamy Ranch Dressing"
    assert all(i["name"] != "Large Eggs" for i in items)


async def test_recent_survives_reload(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api, products, clock
) -> None:
    await call(hass, "scan_upc", product_id=RANCH)
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert [i["name"] for i in recent(hass)] == ["Creamy Ranch Dressing"]


async def test_list_kept_out_of_history(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    from custom_components.kroger_restock.sensor import KrogerRecentSensor

    assert "items" in KrogerRecentSensor._unrecorded_attributes


async def test_card_is_built_and_registered(hass: HomeAssistant) -> None:
    assert (CARD_DIR / CARD_FILE).is_file()
    assert (CARD_DIR / "zxing_reader.wasm").is_file()
    hass.http = Mock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    [paths] = hass.http.async_register_static_paths.call_args.args
    assert paths[0].url_path == CARD_URL_BASE
    assert paths[0].path == str(CARD_DIR)
    url = add_js.call_args.args[1]
    assert url.startswith(f"{CARD_URL_BASE}/{CARD_FILE}?v=")
    assert url.endswith(hass_version())


def hass_version() -> str:
    import json
    from pathlib import Path

    manifest = Path(CARD_DIR).parent / "manifest.json"
    return json.loads(manifest.read_text())["version"]


async def test_card_registration_skipped_without_http(hass: HomeAssistant) -> None:
    hass.http = None
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await _async_register_card(hass)
    add_js.assert_not_called()
