"""Serve the Restock scanner card and register it with the dashboards.

In storage mode (the default), the card is added to the dashboard resources,
the way other card-shipping integrations do it, so it shows up in the card
picker. A version query keeps browsers from using a stale copy after an
update. YAML-mode dashboards get the card through the frontend's extra-module
hook instead (the README explains how to add it as a resource).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_DIR = Path(__file__).parent / "frontend"
CARD_FILE = "kroger-restock-card.js"
CARD_URL_BASE = "/kroger_restock_frontend"
CARD_URL = f"{CARD_URL_BASE}/{CARD_FILE}"


def _resources(hass: HomeAssistant) -> Any | None:
    """Return the storage-mode resource collection, if dashboards use storage."""
    try:
        from homeassistant.components.lovelace.const import (  # noqa: PLC0415
            LOVELACE_DATA,
        )
    except ImportError:  # pragma: no cover - lovelace always ships with HA
        return None
    data = hass.data.get(LOVELACE_DATA)
    if data is None or getattr(data, "resource_mode", None) != "storage":
        return None
    return data.resources


def _is_mine(item: dict[str, Any]) -> bool:
    return str(item.get("url", "")).split("?")[0] == CARD_URL


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card's files and make dashboards load it."""
    if hass.http is None:
        _LOGGER.debug("HTTP not loaded; scanner card not registered")
        return
    if not (CARD_DIR / CARD_FILE).is_file():
        _LOGGER.warning(
            "The Restock scanner card files are missing from %s; reinstall the "
            "integration to get the card",
            CARD_DIR,
        )
        return
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    version = (await async_get_integration(hass, DOMAIN)).version
    url = f"{CARD_URL}?v={version}"
    try:
        # A folder: the card, its lazily loaded chunks and the .wasm reader.
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(CARD_DIR), cache_headers=False)]
        )
    except RuntimeError:
        _LOGGER.debug("Scanner card path already registered")

    resources = _resources(hass)
    if resources is not None:
        await resources.async_get_info()  # loads the collection from storage
        mine = [item for item in resources.async_items() if _is_mine(item)]
        if not mine:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Added the Restock scanner card to the dashboard resources")
        else:
            first, *extra = mine
            if first.get("url") != url:
                await resources.async_update_item(
                    first["id"], {"res_type": "module", "url": url}
                )
            for item in extra:  # tidy up duplicates
                await resources.async_delete_item(item["id"])
        return

    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import (  # noqa: PLC0415
            add_extra_js_url,
        )

        add_extra_js_url(hass, url)


async def async_unregister_card(hass: HomeAssistant) -> None:
    """Remove the dashboard resource (when the last entry is removed)."""
    resources = _resources(hass)
    if resources is None:
        return
    await resources.async_get_info()
    for item in list(resources.async_items()):
        if _is_mine(item):
            await resources.async_delete_item(item["id"])
