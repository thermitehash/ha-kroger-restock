"""Kroger Restock: sync a Home Assistant grocery list to a Kroger cart."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import KrogerApiClient
from .application_credentials import KrogerOAuth2Implementation
from .const import DOMAIN
from .coordinator import (
    ISSUE_AUTH_EXPIRED,
    KrogerRestockCoordinator,
    async_create_auth_issue,
)
from .services import async_setup_services
from .store import RestockStore

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class KrogerRuntimeData:
    """Runtime objects for a loaded entry."""

    coordinator: KrogerRestockCoordinator
    api: KrogerApiClient


type KrogerConfigEntry = ConfigEntry[KrogerRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions once for the integration."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KrogerConfigEntry) -> bool:
    """Set up Kroger Restock from a config entry."""
    # HA maps a missing implementation to re-auth (or a retry if a provider
    # is temporarily down), and maps token-refresh failures the same way.
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    try:
        await session.async_ensure_token_valid()
    except ConfigEntryAuthFailed:
        async_create_auth_issue(hass, entry)
        raise

    async def user_token() -> str:
        await session.async_ensure_token_valid()
        return str(session.token["access_token"])

    app_token = (
        implementation.async_get_app_token
        if isinstance(implementation, KrogerOAuth2Implementation)
        else None
    )
    api = KrogerApiClient(async_get_clientsession(hass), user_token, app_token)
    coordinator = KrogerRestockCoordinator(
        hass, entry, api, RestockStore(hass, entry.entry_id)
    )
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()

    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_AUTH_EXPIRED}_{entry.entry_id}")
    entry.runtime_data = KrogerRuntimeData(coordinator=coordinator, api=api)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: KrogerConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KrogerConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.coordinator.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: KrogerConfigEntry) -> None:
    """Delete stored list data when the entry is removed."""
    await RestockStore(hass, entry.entry_id).async_remove()
