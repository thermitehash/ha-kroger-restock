"""Diagnostics with tokens and personal data redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import KrogerConfigEntry

TO_REDACT_ENTRY = {
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "unique_id",
    "location_name",
    "location_address",
    "zip_code",
    "notify_targets",
}
TO_REDACT_ITEM = {"note", "image_url"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KrogerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    api = entry.runtime_data.api
    return {
        "entry": {
            "title": "**REDACTED**",
            "unique_id": "**REDACTED**",
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
            "options": async_redact_data(dict(entry.options), TO_REDACT_ENTRY),
        },
        "api": {
            "calls_today": dict(api.call_counts),
            "products_use_app_token": api.products_use_app_token,
        },
        "counts": {
            status: coordinator.count(status)
            for status in (
                "unmatched",
                "needs_review",
                "waiting",
                "held",
                "in_cart",
                "received",
            )
        },
        "barcode_cache_size": len(coordinator.data.barcode_cache),
        "orders": [
            {
                "status": o.status,
                "updated": o.updated_at.isoformat(),
                "shorted": len(o.shorted),
                "substitutions": len(o.substitutions),
            }
            for o in coordinator.data.orders
        ],
        "seen_emails": len(coordinator.data.seen_emails),
        "items": [
            async_redact_data(item.as_dict(), TO_REDACT_ITEM)
            for item in coordinator.items
        ],
    }
