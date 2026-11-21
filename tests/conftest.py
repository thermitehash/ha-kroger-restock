"""Fixtures for Kroger Restock tests."""

from __future__ import annotations

from collections.abc import Generator
import time
from typing import Any
from unittest.mock import patch

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kroger_restock.const import (
    CONF_LOCATION_ADDRESS,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_MODALITY,
    DOMAIN,
)

from .helpers import LOCATION_ID, FakeKrogerApi

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
async def setup_credentials(hass: HomeAssistant) -> None:
    """Register application credentials."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), DOMAIN
    )


def token_data(expires_in: float = 3600) -> dict[str, Any]:
    """Return token data like HA stores it."""
    return {
        "access_token": "user-access-token",
        "refresh_token": "user-refresh-token",
        "token_type": "bearer",
        "expires_in": expires_in,
        "expires_at": time.time() + expires_in,
        "scope": "product.compact cart.basic:write profile.compact",
    }


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a Kroger Restock entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kroger Test Store",
        unique_id="profile-123",
        data={
            "auth_implementation": DOMAIN,
            "token": token_data(),
            CONF_LOCATION_ID: LOCATION_ID,
            CONF_LOCATION_NAME: "Kroger Test Store",
            CONF_LOCATION_ADDRESS: "1 Main St, Cincinnati, OH 45202",
            CONF_MODALITY: "pickup",
        },
        options={"debounce_seconds": 3.0},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def fake_api() -> FakeKrogerApi:
    """Return the fake API."""
    return FakeKrogerApi()


@pytest.fixture
def patch_api(fake_api: FakeKrogerApi) -> Generator[FakeKrogerApi]:
    """Make the integration use the fake API."""
    with patch(
        "custom_components.kroger_restock.KrogerApiClient",
        return_value=fake_api,
    ):
        yield fake_api


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    patch_api: FakeKrogerApi,
) -> MockConfigEntry:
    """Set up the integration with the fake API."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def clock() -> Generator[list[float]]:
    """Controllable monotonic clock for debounce/caches."""
    now = [1000.0]
    with patch(
        "custom_components.kroger_restock.coordinator.monotonic",
        side_effect=lambda: now[0],
    ):
        yield now
