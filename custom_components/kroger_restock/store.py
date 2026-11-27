"""Persistent storage for Kroger Restock."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .aisles import locate
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
    # Units sent in a cart call that hasn't been confirmed yet (see PUSHING /
    # CHECK_CART). Saved before the call, so a crash can't lose track of it.
    pending_push: int = 0
    # Recorded as already in the Kroger cart (no cart call) once resolved.
    already_in_cart: bool = False
    # Set when the user chose "keep waiting" on a give-up repair.
    give_up_snoozed_at: datetime | None = None

    @property
    def active(self) -> bool:
        """Return True while the item is still on the active list."""
        return self.status in ACTIVE_STATUSES

    @property
    def aisle_label(self) -> str | None:
        """Return e.g. 'Aisle 12', or the location name ('Checklane 15')."""
        return locate(self.aisle_number, self.aisle_description).label

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
    window_start: datetime | None = None
    window_end: datetime | None = None
    modality: str | None = None
    # None = no email so far contained this information (unknown).
    shorted: list[str] | None = None
    substitutions: list[str] | None = None
    last_subject: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    item_count: int | None = None
    total: float | None = None
    fee: float | None = None
    completed_at: datetime | None = None
    # When the order was placed, its in-cart items were checked for stock
    # (None = no check ran, e.g. the confirmation email was missed).
    stock_checked_at: datetime | None = None
    # Items that were out of stock at that check: [{item_id, name}].
    out_of_stock: list[dict[str, str]] = field(default_factory=list)

    _DATETIMES = (
        "updated_at",
        "stock_checked_at",
        "placed_at",
        "window_start",
        "window_end",
        "completed_at",
    )

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        data = asdict(self)
        for key in self._DATETIMES:
            value = getattr(self, key)
            data[key] = value.isoformat() if value else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KrogerOrder:
        """Deserialize, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        for key in cls._DATETIMES:
            if values.get(key):
                values[key] = dt_util.parse_datetime(values[key])
        return cls(**values)


MAX_ORDERS = 10
MAX_SEEN_EMAILS = 2000


@dataclass(slots=True)
class RestockData:
    """Everything we persist."""

    items: list[ListItem] = field(default_factory=list)
    # Scanned digits -> Kroger product ID that matched.
    barcode_cache: dict[str, str] = field(default_factory=dict)
    # Most recent first.
    orders: list[KrogerOrder] = field(default_factory=list)
    # Keys of order emails already processed (IMAP UID and Message-ID/content).
    seen_emails: list[str] = field(default_factory=list)
    # Store the aisle/price/stock data on items refers to.
    location_id: str | None = None
    # Messages already in the order-email folder when it was linked (never
    # processed): {entry_id, folder, search, keys, count, taken_at}.
    imap_baseline: dict[str, Any] | None = None
    # Recently scanned/added list items, newest first:
    # {item_id, at, result, added, quantity, source}. Only things that landed
    # on the list (no ignored or debounced scans).
    recent: list[dict[str, Any]] = field(default_factory=list)


MAX_RECENT = 25


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
        if old_major_version == 1 and old_minor_version < 6:
            # 1.6 added the recently scanned list.
            old_data.setdefault("recent", [])
        if old_major_version == 1 and old_minor_version < 5:
            # 1.5 added the order-email folder baseline.
            old_data.setdefault("imap_baseline", None)
        if old_major_version == 1 and old_minor_version < 4:
            # 1.4 added pending_push / already_in_cart to items.
            for item in old_data.get("items", []):
                item.setdefault("pending_push", 0)
                item.setdefault("already_in_cart", False)
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
            location_id=raw.get("location_id"),
            imap_baseline=raw.get("imap_baseline"),
            recent=list(raw.get("recent", [])),
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
            "location_id": data.location_id,
            "imap_baseline": data.imap_baseline,
            "recent": list(data.recent),
        }
