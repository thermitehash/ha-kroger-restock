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
    "give_up_snoozed_at",
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
    # Set when the user chose "keep waiting" on a give-up repair.
    give_up_snoozed_at: datetime | None = None

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
class KrogerOrder:
    """An order, as reconstructed from Kroger's emails."""

    order_number: str
    status: str
    updated_at: datetime
    placed_at: datetime | None = None
    window: str | None = None
    modality: str | None = None
    shorted: list[str] = field(default_factory=list)
    substitutions: list[str] = field(default_factory=list)
    last_subject: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        data = asdict(self)
        data["updated_at"] = self.updated_at.isoformat()
        data["placed_at"] = self.placed_at.isoformat() if self.placed_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KrogerOrder:
        """Deserialize, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["updated_at"] = dt_util.parse_datetime(values["updated_at"])
        if values.get("placed_at"):
            values["placed_at"] = dt_util.parse_datetime(values["placed_at"])
        return cls(**values)


MAX_ORDERS = 10
MAX_SEEN_EMAILS = 200


@dataclass(slots=True)
class RestockData:
    """Everything we persist."""

    items: list[ListItem] = field(default_factory=list)
    # Scanned digits -> Kroger product ID that matched.
    barcode_cache: dict[str, str] = field(default_factory=dict)
    # Most recent first.
    orders: list[KrogerOrder] = field(default_factory=list)
    # Keys of order emails already processed (IMAP entry + UID).
    seen_emails: list[str] = field(default_factory=list)


class _VersionedStore(Store[dict[str, Any]]):
    """Store with a migration hook for future format changes."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version == 1 and old_minor_version < 2:
            # 1.2 added give_up_snoozed_at to items.
            for item in old_data.get("items", []):
                item.setdefault("give_up_snoozed_at", None)
        if old_major_version == 1 and old_minor_version < 3:
            # 1.3 added order tracking from emails.
            old_data.setdefault("orders", [])
            old_data.setdefault("seen_emails", [])
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
            orders=[KrogerOrder.from_dict(row) for row in raw.get("orders", [])],
            seen_emails=list(raw.get("seen_emails", [])),
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
            "orders": [order.as_dict() for order in data.orders],
            "seen_emails": list(data.seen_emails),
        }
