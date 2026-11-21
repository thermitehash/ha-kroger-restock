"""Config, reauth and options flow tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.kroger_restock.api import KrogerConnectionError, Location
from custom_components.kroger_restock.application_credentials import (
    KrogerOAuth2Implementation,
)
from custom_components.kroger_restock.const import (
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
)

from .conftest import CLIENT_ID
from .helpers import LOCATION_ID, FakeKrogerApi

REDIRECT_URI = "https://example.com/auth/external/callback"


@pytest.fixture
def flow_api(fake_api: FakeKrogerApi) -> Generator[FakeKrogerApi]:
    with patch(
        "custom_components.kroger_restock.config_flow.KrogerApiClient",
        return_value=fake_api,
    ):
        yield fake_api


async def start_flow(hass: HomeAssistant) -> dict:
    """Start the flow and get past the 'use a computer' intro step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def _sign_in(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    flow_id: str,
    result_url: str,
) -> dict:
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": flow_id, "redirect_uri": REDIRECT_URI}
    )
    query = parse_qs(urlparse(result_url).query)
    assert result_url.startswith(OAUTH2_AUTHORIZE)
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["scope"] == ["product.compact cart.basic:write profile.compact"]
    assert query["state"] == [state]

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "refresh_token": "mock-refresh-token",
            "access_token": "mock-access-token",
            "token_type": "bearer",
            "expires_in": 1800,
        },
    )
    return await hass.config_entries.flow.async_configure(flow_id)


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    flow_api: FakeKrogerApi,
) -> None:
    result = await start_flow(hass)
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    result = await _sign_in(
        hass, hass_client_no_auth, aioclient_mock, result["flow_id"], result["url"]
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "store"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"zip_code": "nope"}
    )
    assert result["errors"] == {"zip_code": "invalid_zip"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"zip_code": "99999"}
    )
    assert result["errors"] == {"base": "no_stores"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"zip_code": "45202"}
    )
    assert result["step_id"] == "pick_store"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location_id": LOCATION_ID}
    )
    assert result["step_id"] == "modality"

    with patch(
        "custom_components.kroger_restock.async_setup_entry", return_value=True
    ) as mock_setup:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"modality": "delivery"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kroger Test Store"
    entry = result["result"]
    assert entry.unique_id == "profile-123"
    assert entry.data["location_id"] == LOCATION_ID
    assert entry.data["modality"] == "delivery"
    assert entry.data["token"]["access_token"] == "mock-access-token"
    assert len(mock_setup.mock_calls) == 1


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_store_lookup_error(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    flow_api: FakeKrogerApi,
) -> None:
    result = await start_flow(hass)
    result = await _sign_in(
        hass, hass_client_no_auth, aioclient_mock, result["flow_id"], result["url"]
    )
    flow_api.async_get_locations = AsyncMock(side_effect=KrogerConnectionError("x"))  # type: ignore[method-assign]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"zip_code": "45202"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_already_configured(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    flow_api: FakeKrogerApi,
    config_entry: MockConfigEntry,
) -> None:
    result = await start_flow(hass)
    result = await _sign_in(
        hass, hass_client_no_auth, aioclient_mock, result["flow_id"], result["url"]
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
async def test_profile_error_aborts(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    flow_api: FakeKrogerApi,
) -> None:
    flow_api.async_get_profile_id = AsyncMock(side_effect=KrogerConnectionError("x"))  # type: ignore[method-assign]
    result = await start_flow(hass)
    result = await _sign_in(
        hass, hass_client_no_auth, aioclient_mock, result["flow_id"], result["url"]
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("current_request_with_host", "setup_credentials")
@pytest.mark.parametrize(
    ("profile_id", "reason"),
    [("profile-123", "reauth_successful"), ("someone-else", "wrong_account")],
)
async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    flow_api: FakeKrogerApi,
    config_entry: MockConfigEntry,
    profile_id: str,
    reason: str,
) -> None:
    flow_api.profile_id = profile_id
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    with patch("custom_components.kroger_restock.async_setup_entry", return_value=True):
        result = await _sign_in(
            hass, hass_client_no_auth, aioclient_mock, result["flow_id"], result["url"]
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    if reason == "reauth_successful":
        assert config_entry.data["token"]["access_token"] == "mock-access-token"
        # Store selection is preserved.
        assert config_entry.data["location_id"] == LOCATION_ID
    else:
        assert config_entry.data["token"]["access_token"] == "user-access-token"


async def test_options_settings(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    hass.services.async_register("notify", "mobile_app_pixel", lambda call: None)
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["step_id"] == "settings"
    schema = result["data_schema"].schema
    notify = next(v for k, v in schema.items() if k == "notify_targets")
    assert "notify.mobile_app_pixel" in [
        o if isinstance(o, str) else o["value"] for o in notify.config["options"]
    ]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "modality": "delivery",
            "order_days": ["sat"],
            "lead_time_days": 1,
            "stock_check_hours": 6,
            "give_up_days": 14,
            "debounce_seconds": 2,
            "notify_targets": ["notify.mobile_app_pixel"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_integration.options["modality"] == "delivery"
    assert setup_integration.options["give_up_days"] == 14
    coordinator = setup_integration.runtime_data.coordinator
    assert coordinator.modality == "DELIVERY"
    assert coordinator.debounce_seconds == 2


async def test_options_change_store(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    entity_registry: er.EntityRegistry,
) -> None:
    """Changing the store takes effect without reinstalling."""
    from custom_components.kroger_restock.api import Location

    from .helpers import make_product

    # An item scanned at the original store: aisle 7, in stock.
    fake_api.add(make_product("0004900002891", "Coca-Cola", aisle="7", stock="HIGH"))
    await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": "049000028911"}, blocking=True
    )
    entity_ids = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(
            entity_registry, setup_integration.entry_id
        )
    )
    old_coordinator = setup_integration.runtime_data.coordinator

    new_store = "02100123"
    fake_api.locations = [
        Location(
            location_id=new_store,
            name="Kroger Uptown",
            address_line="200 High St",
            city="Columbus",
            state="OH",
            zip_code="43215",
        )
    ]
    fake_api.store_products[new_store] = {
        "0004900002891": make_product(
            "0004900002891",
            "Coca-Cola",
            aisle="3",
            aisle_description="AISLE 3",
            stock="LOW",
        )
    }

    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "store"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"zip_code": "1234"}
    )
    assert result["errors"] == {"zip_code": "invalid_zip"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"zip_code": "45202"}
    )
    assert result["step_id"] == "pick_store"
    # The picker shows the street address next to Kroger's store name.
    selector = result["data_schema"].schema["location_id"]
    assert selector.config["options"][0]["label"] == (
        "Kroger Uptown — 200 High St, Columbus, OH 43215"
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"location_id": new_store}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # Reloaded with the new location ID; title follows the store.
    coordinator = setup_integration.runtime_data.coordinator
    assert coordinator is not old_coordinator
    assert coordinator.location_id == new_store
    assert setup_integration.title == "Kroger Uptown"
    assert setup_integration.options["debounce_seconds"] == 3.0  # others kept

    # Per-store data was cleared and re-read from the new store.
    item = coordinator.active_items[0]
    assert item.aisle_number == "3"
    assert item.stock_level == "LOW"
    assert coordinator.data.location_id == new_store
    assert len(fake_api.cart_lines) == 1  # revalidation never pushes

    # Same entities, same IDs; the to-do list shows the new store.
    assert (
        sorted(
            e.entity_id
            for e in er.async_entries_for_config_entry(
                entity_registry, setup_integration.entry_id
            )
        )
        == entity_ids
    )
    todo = hass.states.get("todo.kroger_test_store")
    assert todo.attributes["store_name"] == "Kroger Uptown"
    assert todo.attributes["store_address"] == "200 High St, Columbus, OH 43215"
    assert todo.attributes["location_id"] == new_store


async def test_token_refresh_does_not_reload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Token refreshes rewrite the entry's data; that must not reload it."""
    coordinator = setup_integration.runtime_data.coordinator
    hass.config_entries.async_update_entry(
        setup_integration,
        data={
            **setup_integration.data,
            "token": {**setup_integration.data["token"], "access_token": "new"},
        },
    )
    await hass.async_block_till_done()
    assert setup_integration.runtime_data.coordinator is coordinator


@pytest.mark.usefixtures("setup_credentials")
async def test_store_address_backfilled_for_old_entries(
    hass: HomeAssistant, config_entry: MockConfigEntry, patch_api: FakeKrogerApi
) -> None:
    """Entries from before 0.7 get the store address looked up once."""
    data = dict(config_entry.data)
    data.pop("location_address")
    data["location_name"] = "Kroger Test Store — 1 Main St, Cincinnati, OH"
    hass.config_entries.async_update_entry(config_entry, data=data)
    patch_api.locations[0] = Location(
        location_id=LOCATION_ID,
        name="Kroger Test Store",
        address_line="1 Main St",
        city="Cincinnati",
        state="OH",
        zip_code="45202",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert patch_api.location_calls == [LOCATION_ID]
    assert config_entry.data["location_name"] == "Kroger Test Store"
    assert config_entry.data["location_address"] == "1 Main St, Cincinnati, OH 45202"
    todo = hass.states.get("todo.kroger_test_store")
    assert todo.attributes["store_address"] == "1 Main St, Cincinnati, OH 45202"


@pytest.mark.usefixtures("setup_credentials")
async def test_token_request_uses_basic_auth(hass: HomeAssistant) -> None:
    from homeassistant.components.application_credentials import ClientCredential

    from custom_components.kroger_restock.application_credentials import (
        async_get_auth_implementation,
    )

    impl = await async_get_auth_implementation(
        hass, DOMAIN, ClientCredential("cid", "secret")
    )
    assert isinstance(impl, KrogerOAuth2Implementation)
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={"access_token": "app", "expires_in": 1800})
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with patch(
        "custom_components.kroger_restock.application_credentials.async_get_clientsession",
        return_value=session,
    ):
        assert await impl.async_get_app_token() == "app"
        # Cached until it nears expiry.
        assert await impl.async_get_app_token() == "app"
        await impl._token_request({"grant_type": "refresh_token", "refresh_token": "r"})

    assert session.post.call_count == 2
    first = session.post.call_args_list[0]
    # base64("cid:secret")
    assert first.kwargs["headers"]["Authorization"] == "Basic Y2lkOnNlY3JldA=="
    assert first.kwargs["data"] == {
        "grant_type": "client_credentials",
        "scope": "product.compact",
    }
    second = session.post.call_args_list[1]
    assert "client_secret" not in second.kwargs["data"]
