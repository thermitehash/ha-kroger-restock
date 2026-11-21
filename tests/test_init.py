"""Setup, unload, re-auth, repairs and diagnostics tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.kroger_restock.api import KrogerAuthError
from custom_components.kroger_restock.const import DOMAIN, OAUTH2_TOKEN

from .conftest import token_data
from .helpers import FakeKrogerApi, make_product


async def test_setup_and_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert setup_integration.state is ConfigEntryState.LOADED
    assert hass.states.get("todo.kroger_test_store") is not None
    assert hass.services.has_service(DOMAIN, "scan_upc")
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.usefixtures("setup_credentials", "patch_api")
async def test_expired_token_is_refreshed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "token": token_data(-10)}
    )
    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={"access_token": "fresh", "refresh_token": "r2", "expires_in": 1800},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data["token"]["access_token"] == "fresh"
    # Basic client auth header is sent.
    assert aioclient_mock.mock_calls[0][3]["Authorization"].startswith("Basic ")


@pytest.mark.usefixtures("setup_credentials", "patch_api")
async def test_dead_refresh_token_starts_reauth_and_repair(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    issue_registry: ir.IssueRegistry,
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "token": token_data(-10)}
    )
    aioclient_mock.post(
        OAUTH2_TOKEN,
        status=400,
        json={"error": "invalid_request", "error_description": "invalid refresh_token"},
    )
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    assert issue_registry.async_get_issue(
        DOMAIN, f"auth_expired_{config_entry.entry_id}"
    )


@pytest.mark.usefixtures("setup_credentials", "patch_api")
async def test_transient_token_error_retries(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "token": token_data(-10)}
    )
    aioclient_mock.post(OAUTH2_TOKEN, status=503)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_error_during_scan(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    issue_registry: ir.IssueRegistry,
) -> None:
    fake_api.async_get_product = AsyncMock(side_effect=KrogerAuthError("expired"))  # type: ignore[method-assign]
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "scan_upc", {"upc": "049000028911"}, blocking=True
        )
    await hass.async_block_till_done()
    assert issue_registry.async_get_issue(
        DOMAIN, f"auth_expired_{setup_integration.entry_id}"
    )
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_auth_error_on_push_keeps_item_pending(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product("0004900002891", "Coke"))
    fake_api.fail_cart = KrogerAuthError("expired")
    result = await hass.services.async_call(
        DOMAIN,
        "scan_upc",
        {"upc": "049000028911"},
        blocking=True,
        return_response=True,
    )
    assert result["result"] == "in_cart"
    assert result["pushed"] is False
    assert len(setup_integration.runtime_data.coordinator.active_items) == 1


async def test_service_errors(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "sync", {"config_entry_id": "missing"}, blocking=True
        )
    await hass.config_entries.async_unload(setup_integration.entry_id)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "sync", {}, blocking=True)


async def test_service_without_response(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    fake_api.add(make_product("0004900002891", "Coke"))
    assert (
        await hass.services.async_call(
            DOMAIN,
            "scan_upc",
            {"upc": "049000028911", "config_entry_id": setup_integration.entry_id},
            blocking=True,
        )
        is None
    )
    assert fake_api.cart_lines == [("0004900002891", 1)]


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    snapshot: SnapshotAssertion,
) -> None:
    fake_api.add(make_product("0004900002891", "Coke"))
    await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": "049000028911"}, blocking=True
    )
    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )
    text = str(diagnostics)
    assert "user-access-token" not in text
    assert "user-refresh-token" not in text
    assert "Main St" not in text
    assert diagnostics == snapshot(
        exclude=props(
            "id",
            "added_at",
            "last_stock_check",
            "cart_pushed_at",
            "created_at",
            "modified_at",
        )
    )
