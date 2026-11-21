"""Persistent storage for Kroger Restock."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_STATUSES,
    DOMAIN,
    STORAGE_MINOR_VERSION,
    STORAGE_VERSION,
    ItemSource,
    ItemStatus,
)

_DATETIME_FIELDS = (
    "added_at",
    "last_stock_check",
    "out_of_stock_since",
    "cart_pushed_at",
    "received_at",
)


@dataclass(slots=True)
class ListItem:
    """One entry on the grocery list."""

    name: str
    status: ItemStatus
    source: ItemSource
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    upc: str | None = None
    product_id: str | None = None
    brand: str | None = None
    size: str | None = None
    image_url: str | None = None
    price: float | None = None
    quantity: int = 1
    # How many units of this item we have already sent to the cart. The cart
    # can't be read back, so this is our only record. Pushes only ever send
    # ``quantity - pushed_quantity``.
    pushed_quantity: int = 0
    aisle_number: str | None = None
    aisle_description: str | None = None
    stock_level: str | None = None
    note: str | None = None
    raw_code: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    added_at: datetime = field(default_factory=dt_util.utcnow)
    last_stock_check: datetime | None = None
    out_of_stock_since: datetime | None = None
    cart_pushed_at: datetime | None = None
    received_at: datetime | None = None

    @property
    def active(self) -> bool:
        """Return True while the item is still on the active list."""
        return self.status in ACTIVE_STATUSES

    @property
    def aisle_label(self) -> str | None:
        """Return e.g. 'Aisle 12' or the aisle description."""
        if self.aisle_number and self.aisle_number != "0":
            return f"Aisle {self.aisle_number}"
        return self.aisle_description

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        data = asdict(self)
        for key in _DATETIME_FIELDS:
            value = data[key]
            data[key] = value.isoformat() if value else None
        data["status"] = str(self.status)
        data["source"] = str(self.source)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ListItem:
        """Deserialize from storage, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        for key in _DATETIME_FIELDS:
            if values.get(key):
                values[key] = dt_util.parse_datetime(values[key])
        values["status"] = ItemStatus(values["status"])
        values["source"] = ItemSource(values.get("source", ItemSource.MANUAL))
        return cls(**values)


@dataclass(slots=True)
class RestockData:
    """Everything we persist."""

    items: list[ListItem] = field(default_factory=list)
    # Scanned digits -> Kroger product ID that matched.
    barcode_cache: dict[str, str] = field(default_factory=dict)


class _VersionedStore(Store[dict[str, Any]]):
    """Store with a migration hook for future format changes."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        # Version 1.1 is the first format. Future migrations go here.
        return old_data


class RestockStore:
    """Load and save :class:`RestockData` for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        self._store = _VersionedStore(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            minor_version=STORAGE_MINOR_VERSION,
            private=True,
        )

    async def async_load(self) -> RestockData:
        """Load from disk."""
        raw = await self._store.async_load()
        if not raw:
            return RestockData()
        return RestockData(
            items=[ListItem.from_dict(row) for row in raw.get("items", [])],
            barcode_cache=dict(raw.get("barcode_cache", {})),
        )

    async def async_save(self, data: RestockData) -> None:
        """Save to disk now."""
        await self._store.async_save(self._serialize(data))

    def async_delay_save(self, data: RestockData, delay: float = 1.0) -> None:
        """Schedule a save shortly."""
        self._store.async_delay_save(lambda: self._serialize(data), delay)

    async def async_remove(self) -> None:
        """Delete the file."""
        await self._store.async_remove()

    @staticmethod
    def _serialize(data: RestockData) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in data.items],
            "barcode_cache": dict(data.barcode_cache),
        }
