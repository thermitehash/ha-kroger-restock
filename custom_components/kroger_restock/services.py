"""Actions for Kroger Restock."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ITEM_ID,
    ATTR_NAME,
    ATTR_PRODUCT_ID,
    ATTR_QUANTITY,
    ATTR_SOURCE,
    ATTR_UPC,
    DOMAIN,
    SERVICE_ADD_ITEM,
    SERVICE_CHECK_STOCK,
    SERVICE_READD_ITEM,
    SERVICE_RESOLVE_ITEM,
    SERVICE_SCAN_UPC,
    SERVICE_SYNC,
    ItemSource,
)

if TYPE_CHECKING:
    from .coordinator import KrogerRestockCoordinator

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
_QTY = vol.All(vol.Coerce(int), vol.Range(min=1, max=99))

SCAN_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_UPC): vol.All(vol.Coerce(str), cv.string),
        vol.Optional(ATTR_QUANTITY, default=1): _QTY,
        vol.Optional(ATTR_SOURCE, default=ItemSource.SCAN.value): vol.In(
            [s.value for s in ItemSource]
        ),
    }
)
ADD_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_NAME): cv.string,
        vol.Optional(ATTR_QUANTITY, default=1): _QTY,
        vol.Optional(ATTR_SOURCE, default=ItemSource.MANUAL.value): vol.In(
            [s.value for s in ItemSource]
        ),
    }
)
RESOLVE_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Required(ATTR_PRODUCT_ID): vol.All(vol.Coerce(str), cv.string),
    }
)
SYNC_SCHEMA = vol.Schema(_ENTRY)
READD_SCHEMA = vol.Schema({**_ENTRY, vol.Required(ATTR_ITEM_ID): cv.string})


def _coordinator(call: ServiceCall) -> KrogerRestockCoordinator:
    """Return the coordinator for the targeted (or only) loaded entry."""
    hass = call.hass
    entry_id: str | None = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        entries = [entry]
    else:
        entries = hass.config_entries.async_entries(DOMAIN)
    loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
    if not loaded:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_loaded"
        )
    if len(loaded) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="multiple_entries"
        )
    return loaded[0].runtime_data.coordinator


def _maybe(call: ServiceCall, response: dict[str, Any]) -> ServiceResponse:
    return response if call.return_response else None


async def _scan_upc(call: ServiceCall) -> ServiceResponse:
    response = await _coordinator(call).async_scan(
        call.data[ATTR_UPC],
        call.data[ATTR_QUANTITY],
        ItemSource(call.data[ATTR_SOURCE]),
    )
    return _maybe(call, response)


async def _add_item(call: ServiceCall) -> ServiceResponse:
    response = await _coordinator(call).async_add_text(
        call.data[ATTR_NAME],
        call.data[ATTR_QUANTITY],
        ItemSource(call.data[ATTR_SOURCE]),
    )
    return _maybe(call, response)


async def _resolve_item(call: ServiceCall) -> ServiceResponse:
    response = await _coordinator(call).async_resolve(
        call.data[ATTR_ITEM_ID], call.data[ATTR_PRODUCT_ID]
    )
    return _maybe(call, response)


async def _sync(call: ServiceCall) -> ServiceResponse:
    return _maybe(call, await _coordinator(call).async_sync())


async def _readd_item(call: ServiceCall) -> ServiceResponse:
    response = await _coordinator(call).async_readd(call.data[ATTR_ITEM_ID])
    return _maybe(call, response)


async def _check_stock(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call)
    result = await coordinator.async_check_stock()
    held = await coordinator.async_push_held()
    result["held_pushed"] = held["pushed"]
    return _maybe(call, result)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    for name, handler, schema in (
        (SERVICE_SCAN_UPC, _scan_upc, SCAN_SCHEMA),
        (SERVICE_ADD_ITEM, _add_item, ADD_SCHEMA),
        (SERVICE_RESOLVE_ITEM, _resolve_item, RESOLVE_SCHEMA),
        (SERVICE_SYNC, _sync, SYNC_SCHEMA),
        (SERVICE_READD_ITEM, _readd_item, READD_SCHEMA),
        (SERVICE_CHECK_STOCK, _check_stock, SYNC_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
