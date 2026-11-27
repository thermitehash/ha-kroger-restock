"""Recently scanned list (sensor) and the scanner card registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kroger_restock.card import (
    CARD_DIR,
    CARD_FILE,
    CARD_URL,
    async_register_card,
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


def manifest_version() -> str:
    import json

    manifest = Path(CARD_DIR).parent / "manifest.json"
    return json.loads(manifest.read_text())["version"]


def test_card_is_built() -> None:
    assert (CARD_DIR / CARD_FILE).is_file()
    assert (CARD_DIR / "zxing_reader.wasm").is_file()
    assert any((CARD_DIR / "chunks").glob("*.js"))


async def test_card_served_yaml_fallback(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_client
) -> None:
    # No storage-mode dashboards: fall back to the frontend's extra-module hook.
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await async_register_card(hass)
    add_js.assert_called_once()
    assert add_js.call_args[0][1] == f"{CARD_URL}?v={manifest_version()}"
    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert "kroger-restock-card" in await response.text()
    wasm = await client.get(CARD_URL.rsplit("/", 1)[0] + "/zxing_reader.wasm")
    assert wasm.status == 200


class FakeResources:
    """Stands in for Lovelace's storage-mode resource collection."""

    def __init__(self, items: list[dict[str, str]]) -> None:
        self.items = {i["id"]: dict(i) for i in items}

    async def async_get_info(self) -> dict[str, int]:
        return {"resources": len(self.items)}

    def async_items(self) -> list[dict[str, str]]:
        return list(self.items.values())

    async def async_create_item(self, data: dict[str, str]) -> dict[str, str]:
        item = {
            "id": f"id{len(self.items)}",
            "type": data["res_type"],
            "url": data["url"],
        }
        self.items[item["id"]] = item
        return item

    async def async_update_item(self, item_id: str, data: dict[str, str]) -> dict:
        self.items[item_id]["url"] = data["url"]
        return self.items[item_id]

    async def async_delete_item(self, item_id: str) -> None:
        del self.items[item_id]


@pytest.mark.parametrize(
    "existing",
    [
        [],
        [{"id": "old", "type": "module", "url": f"{CARD_URL}?v=0.13.0"}],
        [
            {"id": "a", "type": "module", "url": f"{CARD_URL}?v=0.12.0"},
            {"id": "b", "type": "module", "url": CARD_URL},
            {"id": "other", "type": "module", "url": "/local/other.js"},
        ],
    ],
)
async def test_card_added_to_dashboard_resources(
    hass: HomeAssistant, setup_integration: MockConfigEntry, existing
) -> None:
    from types import SimpleNamespace

    from homeassistant.components.lovelace.const import LOVELACE_DATA

    resources = FakeResources(existing)
    hass.data[LOVELACE_DATA] = SimpleNamespace(
        resource_mode="storage", resources=resources
    )
    assert await async_setup_component(hass, "http", {})
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await async_register_card(hass)
    add_js.assert_not_called()
    mine = [i for i in resources.async_items() if i["url"].startswith(CARD_URL)]
    assert [i["url"] for i in mine] == [f"{CARD_URL}?v={manifest_version()}"]
    assert len(resources.items) == len(mine) + sum(
        1 for i in existing if not i["url"].startswith(CARD_URL)
    )
    # Removing the last entry removes the resource.
    assert await hass.config_entries.async_remove(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert not [i for i in resources.async_items() if i["url"].startswith(CARD_URL)]
    assert len(resources.items) == len(existing) - sum(
        1 for i in existing if i["url"].startswith(CARD_URL)
    )


async def test_card_files_missing_warns(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    hass.http = Mock(async_register_static_paths=AsyncMock())
    with patch("custom_components.kroger_restock.card.CARD_DIR", tmp_path):
        await async_register_card(hass)
    hass.http.async_register_static_paths.assert_not_called()
    assert "scanner card files are missing" in caplog.text


async def test_card_registration_skipped_without_http(hass: HomeAssistant) -> None:
    hass.http = None
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await async_register_card(hass)
    add_js.assert_not_called()


async def test_card_added_with_real_lovelace(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Against Home Assistant's own storage-mode resource collection."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "lovelace", {})
    await async_register_card(hass)
    await async_register_card(hass)  # a second start doesn't duplicate it
    resources = hass.data[LOVELACE_DATA].resources
    mine = [i for i in resources.async_items() if i["url"].startswith(CARD_URL)]
    assert mine == [
        {
            "id": mine[0]["id"],
            "type": "module",
            "url": f"{CARD_URL}?v={manifest_version()}",
        }
    ]
