"""Kroger Restock: sync a Home Assistant grocery list to a Kroger cart."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import KrogerApiClient, KrogerError
from .application_credentials import KrogerOAuth2Implementation
from .cart_check import CartCheck
from .const import CONF_LOCATION_ADDRESS, CONF_LOCATION_ID, CONF_LOCATION_NAME, DOMAIN
from .coordinator import (
    ISSUE_AUTH_EXPIRED,
    KrogerRestockCoordinator,
    async_create_auth_issue,
    entry_option,
)
from .orders import OrderWatcher
from .services import async_setup_services
from .store import RestockStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class KrogerRuntimeData:
    """Runtime objects for a loaded entry."""

    coordinator: KrogerRestockCoordinator
    api: KrogerApiClient
    orders: OrderWatcher
    cart_check: CartCheck


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
    await _async_backfill_store_address(hass, entry, api)

    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_AUTH_EXPIRED}_{entry.entry_id}")
    orders = OrderWatcher(hass, coordinator)
    cart_check = CartCheck(hass, coordinator)
    entry.runtime_data = KrogerRuntimeData(
        coordinator=coordinator, api=api, orders=orders, cart_check=cart_check
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Options changes reload the entry via OptionsFlowWithReload. There is
    # deliberately no update listener: token refreshes update the entry's data
    # every ~30 minutes, and a listener would reload (and restart the
    # stock-check timer) each time.
    coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    orders.async_start()
    entry.async_on_unload(orders.async_stop)
    cart_check.async_start()
    entry.async_on_unload(cart_check.async_stop)
    return True


async def _async_backfill_store_address(
    hass: HomeAssistant, entry: KrogerConfigEntry, api: KrogerApiClient
) -> None:
    """Entries created before 0.7 have no separate store address; fetch it once."""
    if entry_option(entry, CONF_LOCATION_ADDRESS):
        return
    location_id = entry_option(entry, CONF_LOCATION_ID)
    try:
        location = await api.async_get_location(str(location_id))
    except KrogerError as err:
        _LOGGER.debug("Could not look up store address: %s", err)
        return
    if location is None:
        return
    target = "options" if CONF_LOCATION_ID in entry.options else "data"
    values = {
        CONF_LOCATION_NAME: location.name,
        CONF_LOCATION_ADDRESS: location.address or "",
    }
    if target == "options":
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, **values}
        )
    else:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **values})


async def async_unload_entry(hass: HomeAssistant, entry: KrogerConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.coordinator.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: KrogerConfigEntry) -> None:
    """Delete stored list data when the entry is removed."""
    await RestockStore(hass, entry.entry_id).async_remove()
