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
    ATTR_ACTION,
    ATTR_ALREADY_IN_CART,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_ITEM_ID,
    ATTR_MISSING,
    ATTR_NAME,
    ATTR_PRODUCT_ID,
    ATTR_QUANTITY,
    ATTR_SOURCE,
    ATTR_TARGET,
    ATTR_UPC,
    ATTR_URL,
    CHECK_CART_ACTIONS,
    DOMAIN,
    PRINT_BOTH,
    PRINT_TARGETS,
    SERVICE_ADD_ITEM,
    SERVICE_CART_CHECK,
    SERVICE_CHECK_CART_ITEM,
    SERVICE_CHECK_STOCK,
    SERVICE_MARK_CART_RECEIVED,
    SERVICE_PRINT_LIST,
    SERVICE_READD_ITEM,
    SERVICE_RESOLVE_ITEM,
    SERVICE_SCAN_UPC,
    SERVICE_SYNC,
    ItemSource,
)
from .matching import split_names
from .printer import async_print

if TYPE_CHECKING:
    from .coordinator import KrogerRestockCoordinator

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
_QTY = vol.All(vol.Coerce(int), vol.Range(min=1, max=99))

_ALREADY = {vol.Optional(ATTR_ALREADY_IN_CART, default=False): cv.boolean}

SCAN_SCHEMA = vol.All(
    vol.Schema(
        {
            **_ENTRY,
            **_ALREADY,
            vol.Optional(ATTR_UPC): vol.All(vol.Coerce(str), cv.string),
            vol.Optional(ATTR_PRODUCT_ID): vol.All(vol.Coerce(str), cv.string),
            vol.Optional(ATTR_URL): cv.string,
            vol.Optional(ATTR_QUANTITY, default=1): _QTY,
            vol.Optional(ATTR_SOURCE, default=ItemSource.SCAN.value): vol.In(
                [s.value for s in ItemSource]
            ),
        }
    ),
    cv.has_at_least_one_key(ATTR_UPC, ATTR_PRODUCT_ID, ATTR_URL),
)
ADD_SCHEMA = vol.All(
    vol.Schema(
        {
            **_ENTRY,
            **_ALREADY,
            vol.Optional(ATTR_NAME): cv.string,
            vol.Optional(ATTR_URL): cv.string,
            vol.Optional(ATTR_QUANTITY, default=1): _QTY,
            vol.Optional(ATTR_SOURCE, default=ItemSource.MANUAL.value): vol.In(
                [s.value for s in ItemSource]
            ),
        }
    ),
    cv.has_at_least_one_key(ATTR_NAME, ATTR_URL),
)
RESOLVE_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        **_ALREADY,
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Required(ATTR_PRODUCT_ID): vol.All(vol.Coerce(str), cv.string),
    }
)
SYNC_SCHEMA = vol.Schema(_ENTRY)
PRINT_SCHEMA = vol.Schema(
    {**_ENTRY, vol.Optional(ATTR_TARGET, default=PRINT_BOTH): vol.In(PRINT_TARGETS)}
)
MARK_RECEIVED_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Optional(ATTR_MISSING): vol.Any(
            cv.string, vol.All(cv.ensure_list, [cv.string])
        ),
    }
)
CHECK_CART_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Required(ATTR_ACTION): vol.In(CHECK_CART_ACTIONS),
    }
)
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
        call.data.get(ATTR_UPC),
        call.data[ATTR_QUANTITY],
        ItemSource(call.data[ATTR_SOURCE]),
        already_in_cart=call.data[ATTR_ALREADY_IN_CART],
        product_id=call.data.get(ATTR_PRODUCT_ID),
        url=call.data.get(ATTR_URL),
    )
    return _maybe(call, response)


async def _add_item(call: ServiceCall) -> ServiceResponse:
    if ATTR_URL in call.data:
        # A shared kroger.com product link: look the product up directly.
        response = await _coordinator(call).async_scan(
            None,
            call.data[ATTR_QUANTITY],
            ItemSource(call.data[ATTR_SOURCE]),
            already_in_cart=call.data[ATTR_ALREADY_IN_CART],
            url=call.data[ATTR_URL],
        )
        return _maybe(call, response)
    response = await _coordinator(call).async_add_text(
        call.data[ATTR_NAME],
        call.data[ATTR_QUANTITY],
        ItemSource(call.data[ATTR_SOURCE]),
        already_in_cart=call.data[ATTR_ALREADY_IN_CART],
    )
    return _maybe(call, response)


async def _resolve_item(call: ServiceCall) -> ServiceResponse:
    response = await _coordinator(call).async_resolve(
        call.data[ATTR_ITEM_ID],
        call.data[ATTR_PRODUCT_ID],
        already_in_cart=call.data[ATTR_ALREADY_IN_CART],
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


async def _print_list(call: ServiceCall) -> ServiceResponse:
    result = await async_print(_coordinator(call), call.data[ATTR_TARGET])
    return _maybe(call, result)


async def _mark_cart_received(call: ServiceCall) -> ServiceResponse:
    missing = call.data.get(ATTR_MISSING) or []
    if isinstance(missing, str):
        missing = split_names(missing)
    result = await _coordinator(call).async_mark_cart_received(missing=list(missing))
    return _maybe(call, result)


async def _check_cart_item(call: ServiceCall) -> ServiceResponse:
    result = await _coordinator(call).async_resolve_check_cart(
        call.data[ATTR_ITEM_ID], call.data[ATTR_ACTION]
    )
    return _maybe(call, result)


async def _cart_check(call: ServiceCall) -> ServiceResponse:
    entry = _coordinator(call).config_entry
    summary = await entry.runtime_data.cart_check.async_send()
    return _maybe(call, summary)


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
        (SERVICE_PRINT_LIST, _print_list, PRINT_SCHEMA),
        (SERVICE_CHECK_CART_ITEM, _check_cart_item, CHECK_CART_SCHEMA),
        (SERVICE_CART_CHECK, _cart_check, SYNC_SCHEMA),
        (SERVICE_MARK_CART_RECEIVED, _mark_cart_received, MARK_RECEIVED_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
