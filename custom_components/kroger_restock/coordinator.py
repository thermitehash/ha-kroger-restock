"""Coordinator: owns the list, talks to Kroger and enforces the lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    CartItem,
    KrogerApiClient,
    KrogerAuthError,
    KrogerError,
    Product,
)
from .barcode import (
    PRODUCT_ID_LENGTH,
    BarcodeKind,
    normalize_barcode,
    plu_display_name,
    plu_search_term,
)
from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_GIVE_UP_DAYS,
    CONF_LEAD_TIME_DAYS,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_MODALITY,
    CONF_NOTIFY_TARGETS,
    CONF_ORDER_DAYS,
    CONF_STOCK_CHECK_HOURS,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_GIVE_UP_DAYS,
    DEFAULT_LEAD_TIME_DAYS,
    DEFAULT_MODALITY,
    DEFAULT_STOCK_CHECK_HOURS,
    DOMAIN,
    EVENT_BACK_IN_STOCK,
    EVENT_SCANNED,
    MAX_REVIEW_CANDIDATES,
    MISS_CACHE_SECONDS,
    PRODUCT_CACHE_SECONDS,
    ItemSource,
    ItemStatus,
    ScanResult,
)
from .schedule import check_spacing, in_order_window, next_window_start, waited_too_long
from .store import ListItem, RestockData, RestockStore

if TYPE_CHECKING:
    from . import KrogerConfigEntry

_LOGGER = logging.getLogger(__name__)

ISSUE_AUTH_EXPIRED = "auth_expired"
ISSUE_GAVE_UP = "gave_up"
HELD_TICK = timedelta(hours=1)

_QTY_SUFFIX = re.compile(r"\s*[×x]\s*(\d+)\s*$", re.IGNORECASE)
_SIZE_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def async_create_auth_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Raise a Repairs issue telling the user to sign in to Kroger again."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_AUTH_EXPIRED}_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_AUTH_EXPIRED,
        translation_placeholders={"title": entry.title},
    )


def monotonic() -> float:
    """Monotonic clock (wrapped so tests can patch it)."""
    return time.monotonic()


def entry_option(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Read a setting from options first, then data."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


@dataclass(slots=True)
class ProcessOutcome:
    """What happened when we processed an item."""

    result: ScanResult
    item: ListItem
    pushed: bool = False
    error: str | None = None


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {
        w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if len(w) > 1
    }


def plausible_matches(term: str, products: list[Product]) -> list[Product]:
    """Return products whose name contains every word of ``term``."""
    wanted = _tokens(term)
    if not wanted:
        return []
    matches = []
    for product in products:
        have = _tokens(f"{product.brand or ''} {product.description}")
        if wanted <= have:
            matches.append(product)
    return matches


class KrogerRestockCoordinator(DataUpdateCoordinator[RestockData]):
    """Holds list state and applies the item lifecycle."""

    config_entry: KrogerConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: KrogerConfigEntry,
        api: KrogerApiClient,
        store: RestockStore,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
        )
        self.api = api
        self._store = store
        self._lock = asyncio.Lock()
        self._recent_scans: dict[str, float] = {}
        self._product_cache: dict[str, tuple[float, Product | None]] = {}
        self._miss_cache: dict[str, float] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._check_task: asyncio.Task[Any] | None = None
        self._last_cycle: datetime | None = None
        self.data = RestockData()

    # ------------------------------------------------------------------
    # Setup and persistence

    async def async_load(self) -> None:
        """Load persisted state."""
        self.data = await self._store.async_load()

    async def _async_update_data(self) -> RestockData:
        """No polling in this phase; return current state."""
        return self.data

    def _changed(self) -> None:
        self._store.async_delay_save(self.data)
        self._clear_stale_give_up_issues()
        self.async_set_updated_data(self.data)

    @callback
    def async_start(self) -> None:
        """Start the periodic stock check and the order-window tick."""
        interval = timedelta(hours=self.stock_check_hours)
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._scheduled_check, interval, name="kroger_restock stock"
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._held_tick, HELD_TICK, name="kroger_restock held"
            )
        )

    @callback
    def async_stop(self) -> None:
        """Cancel timers and any running check."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._check_task is not None and not self._check_task.done():
            self._check_task.cancel()

    @callback
    def _scheduled_check(self, _now: datetime) -> None:
        if self._check_task is not None and not self._check_task.done():
            return
        self._check_task = self.config_entry.async_create_background_task(
            self.hass, self._safe_check(), "kroger_restock stock check"
        )

    async def _safe_check(self) -> None:
        try:
            await self.async_check_stock(spread=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Scheduled stock check failed: %s", err)

    async def _held_tick(self, _now: datetime) -> None:
        try:
            await self.async_push_held()
        except HomeAssistantError as err:
            _LOGGER.warning("Pushing held items failed: %s", err)

    async def async_flush(self) -> None:
        """Write state to disk now."""
        await self._store.async_save(self.data)

    # ------------------------------------------------------------------
    # Settings

    @property
    def location_id(self) -> str:
        """Store the cart and stock levels refer to."""
        return str(entry_option(self.config_entry, CONF_LOCATION_ID))

    @property
    def location_name(self) -> str:
        """Human-readable store name."""
        return str(entry_option(self.config_entry, CONF_LOCATION_NAME, ""))

    @property
    def modality(self) -> str:
        """PICKUP or DELIVERY, as the cart API expects."""
        return str(
            entry_option(self.config_entry, CONF_MODALITY, DEFAULT_MODALITY)
        ).upper()

    @property
    def stock_check_hours(self) -> float:
        """Hours between stock checks of waiting items."""
        return float(
            entry_option(
                self.config_entry, CONF_STOCK_CHECK_HOURS, DEFAULT_STOCK_CHECK_HOURS
            )
        )

    @property
    def give_up_days(self) -> int:
        """Flag items that have waited longer than this."""
        return int(
            entry_option(self.config_entry, CONF_GIVE_UP_DAYS, DEFAULT_GIVE_UP_DAYS)
        )

    @property
    def order_days(self) -> list[str]:
        """Weekday keys the user orders on (empty = push right away)."""
        return list(entry_option(self.config_entry, CONF_ORDER_DAYS, []) or [])

    @property
    def lead_time_days(self) -> int:
        """Days before an order day that held items get pushed."""
        return int(
            entry_option(self.config_entry, CONF_LEAD_TIME_DAYS, DEFAULT_LEAD_TIME_DAYS)
        )

    @property
    def notify_targets(self) -> list[str]:
        """notify.* actions to call."""
        return list(entry_option(self.config_entry, CONF_NOTIFY_TARGETS, []) or [])

    def in_order_window(self) -> bool:
        """Return True if held items should be pushed now."""
        return in_order_window(
            dt_util.now().date(), self.order_days, self.lead_time_days
        )

    def next_push_date(self) -> Any:
        """Return the date held items will next be pushed, or None."""
        return next_window_start(
            dt_util.now().date(), self.order_days, self.lead_time_days
        )

    @property
    def debounce_seconds(self) -> float:
        """Ignore repeat scans of a code within this many seconds."""
        return float(
            entry_option(
                self.config_entry, CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS
            )
        )

    # ------------------------------------------------------------------
    # Queries

    @property
    def items(self) -> list[ListItem]:
        """All items, in list order."""
        return self.data.items

    @property
    def active_items(self) -> list[ListItem]:
        """Items still on the active list."""
        return [item for item in self.data.items if item.active]

    def get_item(self, item_id: str) -> ListItem:
        """Return an item or raise a validation error."""
        for item in self.data.items:
            if item.id == item_id:
                return item
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="item_not_found",
            translation_placeholders={"item_id": item_id},
        )

    def count(self, status: ItemStatus) -> int:
        """Return the number of items with ``status``."""
        return sum(1 for item in self.data.items if item.status == status)

    def _find_active(
        self, *, product_id: str | None = None, raw_code: str | None = None
    ) -> ListItem | None:
        for item in self.data.items:
            if not item.active:
                continue
            if product_id and item.product_id == product_id:
                return item
            if raw_code and item.raw_code == raw_code:
                return item
        return None

    # ------------------------------------------------------------------
    # Kroger lookups with caching

    async def _get_product(self, product_id: str) -> Product | None:
        now = monotonic()
        cached = self._product_cache.get(product_id)
        if cached and now - cached[0] < PRODUCT_CACHE_SECONDS:
            return cached[1]
        if (
            miss := self._miss_cache.get(product_id)
        ) and now - miss < MISS_CACHE_SECONDS:
            return None
        product = await self._call(
            self.api.async_get_product(product_id, self.location_id)
        )
        if product is None:
            self._miss_cache[product_id] = now
        else:
            self._product_cache[product_id] = (now, product)
        return product

    async def _lookup_barcode(
        self, digits: str, candidates: Iterable[str]
    ) -> Product | None:
        """Try the cached mapping, then each candidate ID in order."""
        cached_id = self.data.barcode_cache.get(digits)
        if cached_id:
            product = await self._get_product(cached_id)
            if product is not None:
                return product
        for candidate in candidates:
            product = await self._get_product(candidate)
            if product is not None:
                if self.data.barcode_cache.get(digits) != product.product_id:
                    self.data.barcode_cache[digits] = product.product_id
                return product
        return None

    async def _search(self, term: str) -> list[Product]:
        return await self._call(self.api.async_search_products(term, self.location_id))

    async def _call[T](self, coro: Any) -> T:
        """Await an API call, mapping errors to HA exceptions."""
        try:
            return await coro
        except (KrogerAuthError, ConfigEntryAuthFailed) as err:
            async_create_auth_issue(self.hass, self.config_entry)
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except KrogerError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(err)},
            ) from err

    # ------------------------------------------------------------------
    # Applying products and pushing to the cart

    @staticmethod
    def _apply_product(item: ListItem, product: Product) -> None:
        item.product_id = product.product_id
        item.upc = product.upc
        item.name = product.description
        item.brand = product.brand
        item.size = product.size
        item.image_url = product.image_url
        item.price = product.price
        item.stock_level = product.stock_level
        item.aisle_number = product.aisle.number if product.aisle else None
        item.aisle_description = product.aisle.description if product.aisle else None
        item.candidates = []

    async def _settle(self, item: ListItem, product: Product) -> ProcessOutcome:
        """Apply stock state to a matched item and push it if in stock."""
        now = dt_util.utcnow()
        item.last_stock_check = now
        item.stock_level = product.stock_level
        if not product.in_stock:
            if item.status != ItemStatus.WAITING or item.out_of_stock_since is None:
                item.out_of_stock_since = now
            item.status = ItemStatus.WAITING
            return ProcessOutcome(ScanResult.WAITING, item)
        item.out_of_stock_since = None
        item.status = ItemStatus.IN_CART
        error = await self._push([item])
        return ProcessOutcome(
            ScanResult.IN_CART, item, pushed=error is None, error=error
        )

    async def _push(self, items: list[ListItem]) -> str | None:
        """Push each item's unpushed quantity in one batch.

        Returns an error message on failure (items stay pending), else None.
        """
        lines: list[tuple[ListItem, int]] = []
        for item in items:
            delta = item.quantity - item.pushed_quantity
            if item.status == ItemStatus.IN_CART and item.upc and delta > 0:
                lines.append((item, delta))
        if not lines:
            return None
        cart = [
            CartItem(
                upc=item.upc.zfill(PRODUCT_ID_LENGTH),  # type: ignore[union-attr]
                quantity=delta,
                modality=self.modality,
            )
            for item, delta in lines
        ]
        try:
            await self._call(self.api.async_add_to_cart(cart))
        except HomeAssistantError as err:
            _LOGGER.warning("Cart push failed; will retry on next sync: %s", err)
            return str(err)
        now = dt_util.utcnow()
        for item, delta in lines:
            item.pushed_quantity += delta
            item.cart_pushed_at = now
        return None

    def _fire(self, outcome: ProcessOutcome, source: ItemSource) -> None:
        item = outcome.item
        self.hass.bus.async_fire(
            EVENT_SCANNED,
            {
                "result": str(outcome.result),
                "item_id": item.id,
                "name": item.name,
                "brand": item.brand,
                "size": item.size,
                "price": item.price,
                "aisle": item.aisle_label,
                "quantity": item.quantity,
                "upc": item.upc or item.raw_code,
                "source": str(source),
                "config_entry_id": self.config_entry.entry_id,
            },
        )

    def _response(self, outcome: ProcessOutcome) -> dict[str, Any]:
        item = outcome.item
        response: dict[str, Any] = {
            "result": str(outcome.result),
            "item_id": item.id,
            "status": str(item.status),
            "name": item.name,
            "brand": item.brand,
            "size": item.size,
            "price": item.price,
            "aisle": item.aisle_label,
            "quantity": item.quantity,
            "upc": item.upc,
            "product_id": item.product_id,
            "stock_level": item.stock_level,
            "image_url": item.image_url,
            "pushed": outcome.pushed,
        }
        if item.candidates:
            response["candidates"] = item.candidates
        if outcome.error:
            response["error"] = outcome.error
        return response

    async def _bump_duplicate(self, item: ListItem, quantity: int) -> ProcessOutcome:
        item.quantity += quantity
        error = None
        if item.status == ItemStatus.IN_CART:
            # Push only the extra units; already-pushed units are never resent.
            error = await self._push([item])
        return ProcessOutcome(ScanResult.DUPLICATE, item, pushed=False, error=error)

    # ------------------------------------------------------------------
    # Public operations

    async def async_scan(
        self, code: str, quantity: int = 1, source: ItemSource = ItemSource.SCAN
    ) -> dict[str, Any]:
        """Handle a scanned barcode."""
        normalized = normalize_barcode(code)
        if normalized.kind is BarcodeKind.INVALID:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_barcode",
                translation_placeholders={"code": str(code)},
            )
        digits = normalized.digits
        now = monotonic()
        last = self._recent_scans.get(digits)
        self._recent_scans = {
            k: v for k, v in self._recent_scans.items() if now - v < 60
        }
        if last is not None and now - last < self.debounce_seconds:
            _LOGGER.debug("Ignoring repeat scan of %s within debounce window", digits)
            return {
                "result": str(ScanResult.DUPLICATE),
                "debounced": True,
                "upc": digits,
            }
        self._recent_scans[digits] = now

        async with self._lock:
            outcome = await self._process_scan(normalized, digits, quantity, source)
            self._changed()
        self._fire(outcome, source)
        return self._response(outcome)

    async def _process_scan(
        self, normalized: Any, digits: str, quantity: int, source: ItemSource
    ) -> ProcessOutcome:
        # Duplicate check before any API call.
        existing = self._find_active(
            product_id=self.data.barcode_cache.get(digits), raw_code=digits
        )
        if existing is not None:
            return await self._bump_duplicate(existing, quantity)

        if normalized.is_plu:
            item = ListItem(
                name=plu_display_name(normalized),
                status=ItemStatus.NEEDS_REVIEW,
                source=source,
                quantity=quantity,
                raw_code=digits,
            )
            if term := plu_search_term(normalized):
                item.candidates = _candidates(await self._search(term))
            self.data.items.append(item)
            return ProcessOutcome(ScanResult.NEEDS_REVIEW, item)

        product = await self._lookup_barcode(digits, normalized.candidates)
        if product is None:
            item = ListItem(
                name=digits,
                status=ItemStatus.UNMATCHED,
                source=source,
                quantity=quantity,
                raw_code=digits,
            )
            self.data.items.append(item)
            return ProcessOutcome(ScanResult.UNMATCHED, item)

        existing = self._find_active(product_id=product.product_id)
        if existing is not None:
            return await self._bump_duplicate(existing, quantity)

        item = ListItem(
            name=product.description,
            status=ItemStatus.WAITING,
            source=source,
            quantity=quantity,
            raw_code=digits,
        )
        self._apply_product(item, product)
        self.data.items.append(item)
        return await self._settle(item, product)

    async def async_add_text(
        self,
        name: str,
        quantity: int = 1,
        source: ItemSource = ItemSource.MANUAL,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Add a free-text item: search, then match or flag for review."""
        name = " ".join(name.split())
        if not name:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="empty_name"
            )
        async with self._lock:
            outcome = await self._process_text(name, quantity, source, note)
            self._changed()
        self._fire(outcome, source)
        return self._response(outcome)

    async def _process_text(
        self, name: str, quantity: int, source: ItemSource, note: str | None
    ) -> ProcessOutcome:
        for item in self.active_items:
            if item.product_id is None and item.name.casefold() == name.casefold():
                return await self._bump_duplicate(item, quantity)

        results = await self._search(name)
        matches = plausible_matches(name, results)
        item = ListItem(
            name=name,
            status=ItemStatus.UNMATCHED,
            source=source,
            quantity=quantity,
            note=note,
        )
        if not results:
            self.data.items.append(item)
            return ProcessOutcome(ScanResult.UNMATCHED, item)
        if len(matches) == 1 or len(results) == 1:
            product = matches[0] if matches else results[0]
            if (
                existing := self._find_active(product_id=product.product_id)
            ) is not None:
                return await self._bump_duplicate(existing, quantity)
            self._apply_product(item, product)
            self.data.items.append(item)
            return await self._settle(item, product)
        item.status = ItemStatus.NEEDS_REVIEW
        item.candidates = _candidates(matches or results)
        self.data.items.append(item)
        return ProcessOutcome(ScanResult.NEEDS_REVIEW, item)

    async def async_resolve(self, item_id: str, product_id: str) -> dict[str, Any]:
        """Attach a product to an unmatched or needs-review item."""
        async with self._lock:
            item = self.get_item(item_id)
            if item.status not in (ItemStatus.UNMATCHED, ItemStatus.NEEDS_REVIEW):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_resolvable",
                    translation_placeholders={"status": str(item.status)},
                )
            normalized = normalize_barcode(product_id)
            if normalized.kind in (BarcodeKind.INVALID, BarcodeKind.PLU):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_product_id",
                    translation_placeholders={"product_id": product_id},
                )
            ids = (
                [normalized.digits]
                if len(normalized.digits) == PRODUCT_ID_LENGTH
                else []
            )
            ids += [c for c in normalized.candidates if c not in ids]
            product = None
            for candidate in ids:
                if (product := await self._get_product(candidate)) is not None:
                    break
            if product is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="product_not_found",
                    translation_placeholders={"product_id": product_id},
                )
            if item.raw_code and not normalize_barcode(item.raw_code).is_plu:
                # Remember the fix so the next scan of this code just works.
                self.data.barcode_cache[item.raw_code] = product.product_id
            existing = self._find_active(product_id=product.product_id)
            if existing is not None and existing is not item:
                self.data.items.remove(item)
                outcome = await self._bump_duplicate(existing, item.quantity)
            else:
                self._apply_product(item, product)
                outcome = await self._settle(item, product)
            self._changed()
        return self._response(outcome)

    async def async_sync(self) -> dict[str, Any]:
        """Push any in-cart items whose quantity hasn't been fully pushed.

        Never re-sends units that were already pushed.
        """
        async with self._lock:
            pending = [
                item
                for item in self.data.items
                if item.status == ItemStatus.IN_CART
                and item.quantity > item.pushed_quantity
            ]
            error = await self._push(pending)
            self._changed()
        pushed = [i for i in pending if i.quantity == i.pushed_quantity]
        result: dict[str, Any] = {
            "pushed": len(pushed),
            "pending": len(pending) - len(pushed),
            "items": [{"item_id": i.id, "name": i.name} for i in pushed],
        }
        if error:
            result["error"] = error
        return result

    async def async_set_received(self, item_id: str) -> None:
        """User checked an item off: it leaves the active list."""
        async with self._lock:
            item = self.get_item(item_id)
            if item.status != ItemStatus.RECEIVED:
                item.status = ItemStatus.RECEIVED
                item.received_at = dt_util.utcnow()
                self._changed()

    async def async_readd(self, item_id: str) -> dict[str, Any]:
        """Bring a received item back: stock check, then push again.

        This is the "shorted at pickup" path and the only way an item that
        was already pushed is pushed again.
        """
        async with self._lock:
            item = self.get_item(item_id)
            item.received_at = None
            item.give_up_snoozed_at = None
            item.pushed_quantity = 0
            item.cart_pushed_at = None
            if item.product_id is None:
                item.status = (
                    ItemStatus.NEEDS_REVIEW if item.candidates else ItemStatus.UNMATCHED
                )
                outcome = ProcessOutcome(ScanResult(str(item.status)), item)
            else:
                self._product_cache.pop(item.product_id, None)
                product = await self._get_product(item.product_id)
                if product is None:
                    item.status = ItemStatus.UNMATCHED
                    outcome = ProcessOutcome(ScanResult.UNMATCHED, item)
                else:
                    self._apply_product(item, product)
                    outcome = await self._settle(item, product)
            self._changed()
        return self._response(outcome)

    async def async_edit(
        self, item_id: str, summary: str | None, note: str | None
    ) -> None:
        """Apply a rename/quantity/note edit from the to-do UI."""
        async with self._lock:
            item = self.get_item(item_id)
            if summary is not None:
                text = summary.strip()
                if match := _QTY_SUFFIX.search(text):
                    item.quantity = max(1, int(match.group(1)))
                    text = text[: match.start()].strip()
                if item.size and text.endswith(f"({item.size})"):
                    text = text[: -len(f"({item.size})")].strip()
                if text and text != item.name:
                    item.name = text
            item.note = note or None
            if (
                item.status == ItemStatus.IN_CART
                and item.quantity > item.pushed_quantity
            ):
                await self._push([item])
            self._changed()

    async def async_delete(self, item_ids: list[str]) -> None:
        """Remove items from the list (and our records) for good."""
        async with self._lock:
            ids = set(item_ids)
            self.data.items = [i for i in self.data.items if i.id not in ids]
            self._changed()

    # ------------------------------------------------------------------
    # Phase 2: stock checks, held items, give-up, notifications

    async def async_check_stock(self, *, spread: bool = False) -> dict[str, Any]:
        """Re-check every waiting item and act on the ones back in stock.

        With ``spread`` the calls are spaced out over part of the interval
        to stay gentle on Kroger's rate limits. The lock is only held while
        applying each result, so scans keep working during a long cycle.
        """
        waiting_ids = [i.id for i in self.data.items if i.status == ItemStatus.WAITING]
        spacing = (
            check_spacing(self.stock_check_hours * 3600, len(waiting_ids))
            if spread
            else 0.0
        )
        back: list[ListItem] = []
        pushed: list[ListItem] = []
        held: list[ListItem] = []
        errors: list[str] = []
        for index, item_id in enumerate(waiting_ids):
            if index and spacing:
                await asyncio.sleep(spacing)
            item = self._item_or_none(item_id)
            if item is None or item.status != ItemStatus.WAITING or not item.product_id:
                continue
            self._product_cache.pop(item.product_id, None)
            try:
                product = await self._get_product(item.product_id)
            except HomeAssistantError as err:
                errors.append(str(err))
                continue
            async with self._lock:
                if item.status != ItemStatus.WAITING:
                    continue
                item.last_stock_check = dt_util.utcnow()
                if product is None or not product.in_stock:
                    if product is not None:
                        item.stock_level = product.stock_level
                    continue
                self._apply_product(item, product)
                back.append(item)
                if self.order_days and not self.in_order_window():
                    item.status = ItemStatus.HELD
                    item.out_of_stock_since = None
                    held.append(item)
                else:
                    item.status = ItemStatus.IN_CART
                    item.out_of_stock_since = None
                    pushed.append(item)
        async with self._lock:
            push_error = await self._push(pushed)
            for item in pushed:
                if item.status == ItemStatus.IN_CART:
                    item.out_of_stock_since = None
            self._last_cycle = dt_util.utcnow()
            self._flag_give_ups()
            self._changed()
        if back:
            self._announce_back_in_stock(pushed, held)
        result: dict[str, Any] = {
            "checked": len(waiting_ids),
            "back_in_stock": len(back),
            "pushed": [{"item_id": i.id, "name": i.name} for i in pushed],
            "held": [{"item_id": i.id, "name": i.name} for i in held],
            "still_waiting": self.count(ItemStatus.WAITING),
        }
        if push_error:
            errors.append(push_error)
        if errors:
            result["errors"] = errors
        return result

    async def async_push_held(self) -> dict[str, Any]:
        """Push held items if we're inside the order window.

        Stock is checked again first; anything out of stock again goes back
        to waiting.
        """
        held_ids = [i.id for i in self.data.items if i.status == ItemStatus.HELD]
        if not held_ids or (self.order_days and not self.in_order_window()):
            return {"pushed": 0}
        to_push: list[ListItem] = []
        async with self._lock:
            for item_id in held_ids:
                item = self._item_or_none(item_id)
                if (
                    item is None
                    or item.status != ItemStatus.HELD
                    or not item.product_id
                ):
                    continue
                self._product_cache.pop(item.product_id, None)
                product = await self._get_product(item.product_id)
                item.last_stock_check = dt_util.utcnow()
                if product is None or not product.in_stock:
                    item.status = ItemStatus.WAITING
                    item.out_of_stock_since = dt_util.utcnow()
                    continue
                self._apply_product(item, product)
                item.status = ItemStatus.IN_CART
                item.out_of_stock_since = None
                to_push.append(item)
            error = await self._push(to_push)
            self._changed()
        if to_push:
            names = ", ".join(i.name for i in to_push)
            await self._async_notify(
                "Held items added to your cart",
                f"Added for your order: {names}.",
            )
        result: dict[str, Any] = {"pushed": len(to_push)}
        if error:
            result["error"] = error
        return result

    def _item_or_none(self, item_id: str) -> ListItem | None:
        return next((i for i in self.data.items if i.id == item_id), None)

    def _announce_back_in_stock(
        self, pushed: list[ListItem], held: list[ListItem]
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_BACK_IN_STOCK,
            {
                "pushed": [{"item_id": i.id, "name": i.name} for i in pushed],
                "held": [{"item_id": i.id, "name": i.name} for i in held],
                "config_entry_id": self.config_entry.entry_id,
            },
        )
        lines = []
        if pushed:
            lines.append(
                "Added to your cart: " + ", ".join(i.name for i in pushed) + "."
            )
        if held:
            when = self.next_push_date()
            day = f"{when:%A}" if when else "your order day"
            lines.append(
                "Held until " + day + ": " + ", ".join(i.name for i in held) + "."
            )
        self.config_entry.async_create_task(
            self.hass,
            self._async_notify("Back in stock", " ".join(lines)),
            "kroger_restock notify",
        )

    async def _async_notify(self, title: str, message: str) -> None:
        """Send to each configured notify target, or a persistent notification."""
        targets = self.notify_targets
        if not targets:
            persistent_notification.async_create(
                self.hass,
                message,
                title=title,
                notification_id=f"{DOMAIN}_{self.config_entry.entry_id}",
            )
            return
        for target in targets:
            domain, _, service = target.partition(".")
            if not service:
                domain, service = "notify", domain
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"title": title, "message": message},
                    blocking=True,
                )
            except HomeAssistantError as err:
                _LOGGER.warning("Could not notify %s: %s", target, err)

    def _give_up_issue_id(self, item_id: str) -> str:
        return f"{ISSUE_GAVE_UP}_{self.config_entry.entry_id}_{item_id}"

    def _flag_give_ups(self) -> None:
        """Raise a Repairs issue per item waiting longer than allowed.

        Items are never removed automatically; the user decides.
        """
        now = dt_util.utcnow()
        for item in self.data.items:
            if item.status != ItemStatus.WAITING:
                continue
            if not waited_too_long(
                now, item.out_of_stock_since, item.give_up_snoozed_at, self.give_up_days
            ):
                continue
            since = item.out_of_stock_since or now
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._give_up_issue_id(item.id),
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_GAVE_UP,
                translation_placeholders={
                    "name": item.name,
                    "days": str((now - since).days),
                },
                data={"entry_id": self.config_entry.entry_id, "item_id": item.id},
            )

    def _clear_stale_give_up_issues(self) -> None:
        registry = ir.async_get(self.hass)
        prefix = f"{ISSUE_GAVE_UP}_{self.config_entry.entry_id}_"
        waiting = {i.id for i in self.data.items if i.status == ItemStatus.WAITING}
        for domain, issue_id in list(registry.issues):
            if domain != DOMAIN or not issue_id.startswith(prefix):
                continue
            if issue_id.removeprefix(prefix) not in waiting:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def async_keep_waiting(self, item_id: str) -> None:
        """User chose to keep waiting: restart the give-up clock."""
        async with self._lock:
            item = self.get_item(item_id)
            item.give_up_snoozed_at = dt_util.utcnow()
            ir.async_delete_issue(self.hass, DOMAIN, self._give_up_issue_id(item_id))
            self._changed()

    async def async_move(self, item_id: str, previous_id: str | None) -> None:
        """Reorder an item after ``previous_id`` (or to the top)."""
        async with self._lock:
            item = self.get_item(item_id)
            self.data.items.remove(item)
            index = 0
            if previous_id is not None:
                prev = self.get_item(previous_id)
                index = self.data.items.index(prev) + 1
            self.data.items.insert(index, item)
            self._changed()

    def last_stock_check(self) -> datetime | None:
        """Most recent stock check across all items."""
        checks = [i.last_stock_check for i in self.data.items if i.last_stock_check]
        if self._last_cycle is not None:
            checks.append(self._last_cycle)
        return max(checks) if checks else None


def _candidates(products: list[Product]) -> list[dict[str, Any]]:
    return [
        {
            "product_id": p.product_id,
            "name": p.description,
            "brand": p.brand,
            "size": p.size,
            "in_stock": p.in_stock,
        }
        for p in products[:MAX_REVIEW_CANDIDATES]
    ]
