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
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
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
    KrogerConnectionError,
    KrogerError,
    Product,
)
from .barcode import (
    PRODUCT_ID_LENGTH,
    BarcodeKind,
    NormalizedBarcode,
    normalize_barcode,
    plu_display_name,
    plu_search_term,
)
from .const import (
    CHECK_CART_CONFIRM,
    CHECK_CART_PUSH,
    CHECK_CART_REMOVE,
    CONF_DEBOUNCE_SECONDS,
    CONF_GIVE_UP_DAYS,
    CONF_LEAD_TIME_DAYS,
    CONF_LOCATION_ADDRESS,
    CONF_LOCATION_ID,
    CONF_LOCATION_NAME,
    CONF_MODALITY,
    CONF_NOTIFY_SCANS,
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
    IGNORED_MESSAGE,
    IGNORED_NOTIFY_INTERVAL,
    LINK_IGNORED_MESSAGE,
    MAX_REVIEW_CANDIDATES,
    MISS_CACHE_SECONDS,
    PRODUCT_CACHE_SECONDS,
    SCAN_NOTIFICATION_TAG,
    ItemSource,
    ItemStatus,
    ScanResult,
)
from .links import PRODUCT_ID, product_id_from_text
from .matching import match_item
from .schedule import check_spacing, in_order_window, next_window_start, waited_too_long
from .store import ListItem, RestockData, RestockStore

if TYPE_CHECKING:
    from . import KrogerConfigEntry

_LOGGER = logging.getLogger(__name__)

ISSUE_AUTH_EXPIRED = "auth_expired"
ISSUE_GAVE_UP = "gave_up"
ISSUE_CHECK_CART = "check_cart"
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


def scan_notification_text(response: dict[str, Any]) -> str | None:
    """Short text for the per-scan push."""
    result = response.get("result")
    name = response.get("name") or ""
    if result == "ignored":
        if response.get("reason") == "not_a_kroger_product_link":
            return "⊘ Ignored: not a Kroger product link"
        return "⊘ Ignored: aim at the barcode"
    if result == "in_cart":
        details = " ".join(p for p in (name, response.get("size")) if p)
        if response.get("aisle"):
            details += f" · {response['aisle']}"
        label = "In cart (recorded)" if response.get("already_in_cart") else "In cart"
        if response.get("pushed") is False and not response.get("already_in_cart"):
            label = "Cart push pending"
        return f"✓ {label}: {details}"
    if result == "waiting":
        return f"⏳ Waiting on stock: {name}"
    if result == "unmatched":
        return f"? Unknown code {response.get('upc') or name}"
    if result == "duplicate":
        return f"↺ Already on list (qty {response.get('quantity')}): {name}"
    if result == "needs_review":
        return f"• Needs review: {name}"
    return None


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
    added: int = 0  # units a duplicate scan added to an existing item


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
        self._needs_revalidation = False
        self._last_ignored_notice = float("-inf")
        self._record_only = False
        self._check_task: asyncio.Task[Any] | None = None
        self._last_cycle: datetime | None = None
        self.data = RestockData()

    # ------------------------------------------------------------------
    # Setup and persistence

    async def async_load(self) -> None:
        """Load persisted state, and handle a store change made in the options."""
        self.data = await self._store.async_load()
        previous = self.data.location_id
        if previous is not None and previous != self.location_id:
            _LOGGER.info(
                "Store changed (%s -> %s); clearing per-store aisle, price and "
                "stock data",
                previous,
                self.location_id,
            )
            for item in self.data.items:
                item.aisle_number = None
                item.aisle_description = None
                item.stock_level = None
                item.price = None
            self._needs_revalidation = True
        self.data.location_id = self.location_id
        # A push that was in flight when HA stopped: it may be in the cart.
        interrupted = [i for i in self.data.items if i.status == ItemStatus.PUSHING]
        for item in interrupted:
            _LOGGER.warning(
                "Cart push for %s was interrupted; it may already be in the cart",
                item.name,
            )
            self._flag_check_cart(item)
        if interrupted:
            await self._store.async_save(self.data)

    async def async_revalidate_store_data(self) -> int:
        """Re-read aisle, price and stock for active items at the current store.

        Runs after a store change. Nothing is pushed; waiting/held items keep
        their status until the next stock check. Returns items refreshed.
        """
        refreshed = 0
        for item in list(self.active_items):
            if not item.product_id:
                continue
            try:
                product = await self._get_product(item.product_id)
            except HomeAssistantError as err:
                _LOGGER.debug("Revalidation failed for %s: %s", item.product_id, err)
                continue
            if product is None:
                continue
            async with self._lock:
                item.aisle_number = product.aisle.number if product.aisle else None
                item.aisle_description = (
                    product.aisle.description if product.aisle else None
                )
                item.price = product.price
                item.stock_level = product.stock_level
            refreshed += 1
        self._needs_revalidation = False
        self._changed()
        return refreshed

    async def _async_update_data(self) -> RestockData:
        """No polling in this phase; return current state."""
        return self.data

    def _changed(self) -> None:
        self._store.async_delay_save(self.data)
        self._clear_stale_give_up_issues()
        self.async_set_updated_data(self.data)

    @callback
    def mark_changed(self) -> None:
        """Save and notify listeners after an outside change to ``data``."""
        self._changed()

    async def async_notify(
        self,
        title: str | None,
        message: str,
        actions: list[dict[str, str]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification to the configured targets."""
        await self._async_notify(title, message, actions, data)

    def in_cart_items(self, before: datetime | None = None) -> list[ListItem]:
        """In-cart items fully pushed (optionally pushed before ``before``)."""
        return [
            i
            for i in self.data.items
            if i.status == ItemStatus.IN_CART
            and i.pushed_quantity >= i.quantity
            and (before is None or (i.cart_pushed_at and i.cart_pushed_at <= before))
        ]

    async def async_mark_cart_received(
        self,
        before: datetime | None = None,
        missing: list[str] | None = None,
    ) -> dict[str, Any]:
        """Mark in-cart items received after an order arrived.

        ``missing`` lists items that were expected but didn't arrive (item IDs
        or names, e.g. from the notification's text reply). Those go back on
        the list through the re-add path (stock check, then pushed again for
        the next order); everything else is marked received.
        """
        async with self._lock:
            items = self.in_cart_items(before)
            by_id = {item.id: item for item in items}
            missing_items: list[ListItem] = []
            unmatched: list[str] = []
            for entry in missing or []:
                item = by_id.get(entry) or match_item(
                    entry, [i for i in items if i not in missing_items]
                )
                if item is None:
                    unmatched.append(entry)
                elif item not in missing_items:
                    missing_items.append(item)
            now = dt_util.utcnow()
            for item in items:
                item.status = ItemStatus.RECEIVED
                item.received_at = now
            if items:
                self._changed()
        returned = []
        for item in missing_items:
            result = await self.async_readd(item.id)
            returned.append(
                {"item_id": item.id, "name": item.name, "status": result["status"]}
            )
        return {
            "received": len(items) - len(missing_items),
            "missing": returned,
            "unmatched": unmatched,
        }

    @callback
    def async_start(self) -> None:
        """Start the periodic stock check and the order-window tick."""
        if self._needs_revalidation:
            self.config_entry.async_create_background_task(
                self.hass,
                self.async_revalidate_store_data(),
                "kroger_restock store revalidation",
            )
        self._unsubs.append(
            self.hass.bus.async_listen(
                "mobile_app_notification_action",
                self._handle_undo,
                event_filter=self._undo_filter,
            )
        )
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
        """Store name as Kroger calls it (e.g. a neighborhood, not the city)."""
        name = str(entry_option(self.config_entry, CONF_LOCATION_NAME, ""))
        # Entries made before 0.7 stored "Name — address" here.
        return name.split(" — ", 1)[0]

    @property
    def location_address(self) -> str | None:
        """Street address of the store."""
        address = entry_option(self.config_entry, CONF_LOCATION_ADDRESS)
        if address:
            return str(address)
        name = str(entry_option(self.config_entry, CONF_LOCATION_NAME, ""))
        return name.split(" — ", 1)[1] if " — " in name else None

    @property
    def location_label(self) -> str:
        """Name plus address, for printouts and pickers."""
        if self.location_address:
            return f"{self.location_name} — {self.location_address}"
        return self.location_name

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
    def notify_scans(self) -> bool:
        """Send a short push for every scan (off by default)."""
        return bool(entry_option(self.config_entry, CONF_NOTIFY_SCANS, False))

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
        candidates = list(candidates)
        cached_id = self.data.barcode_cache.get(digits)
        _LOGGER.debug(
            "Barcode %s: cached product %s, candidates in order %s",
            digits,
            cached_id or "none",
            candidates,
        )
        if cached_id:
            product = await self._get_product(cached_id)
            _LOGGER.debug(
                "Barcode %s: cached %s -> %s",
                digits,
                cached_id,
                "hit" if product else "miss",
            )
            if product is not None:
                return product
        for position, candidate in enumerate(candidates, start=1):
            product = await self._get_product(candidate)
            _LOGGER.debug(
                "Barcode %s: candidate %d/%d %s -> %s",
                digits,
                position,
                len(candidates),
                candidate,
                "hit" if product else "miss",
            )
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
        if self._record_only:
            # Already physically in the Kroger cart: record it, whatever the
            # stock level says, and make no cart call.
            item.out_of_stock_since = None
            item.status = ItemStatus.IN_CART
            item.already_in_cart = False
            await self._push([item])
            return ProcessOutcome(ScanResult.IN_CART, item, pushed=False)
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
        now = dt_util.utcnow()
        if self._record_only:
            for item, delta in lines:
                item.pushed_quantity += delta
                item.cart_pushed_at = now
            return None
        # Save before calling Kroger: if HA stops between the cart call and
        # the next save, these items come back as CHECK_CART, not lost.
        for item, delta in lines:
            item.status = ItemStatus.PUSHING
            item.pending_push = delta
        await self._store.async_save(self.data)
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
            if isinstance(err.__cause__, KrogerConnectionError):
                # No answer from Kroger: the request may have gone through.
                _LOGGER.warning("Cart push got no response; asking the user: %s", err)
                for item, _delta in lines:
                    self._flag_check_cart(item)
            else:
                # Kroger answered with an error: nothing was added.
                _LOGGER.warning("Cart push failed; will retry on next sync: %s", err)
                for item, _delta in lines:
                    item.status = ItemStatus.IN_CART
                    item.pending_push = 0
            await self._store.async_save(self.data)
            return str(err)
        for item, delta in lines:
            item.pushed_quantity += delta
            item.pending_push = 0
            item.status = ItemStatus.IN_CART
            item.cart_pushed_at = now
        await self._store.async_save(self.data)
        return None

    # ------------------------------------------------------------------
    # Interrupted pushes (CHECK_CART)

    def _check_cart_issue_id(self, item_id: str) -> str:
        return f"{ISSUE_CHECK_CART}_{self.config_entry.entry_id}_{item_id}"

    def _flag_check_cart(self, item: ListItem) -> None:
        """Mark an item whose cart call may or may not have gone through."""
        item.status = ItemStatus.CHECK_CART
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._check_cart_issue_id(item.id),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_CHECK_CART,
            translation_placeholders={
                "name": item.name,
                "quantity": str(item.pending_push or item.quantity),
            },
            data={"entry_id": self.config_entry.entry_id, "item_id": item.id},
        )

    async def async_resolve_check_cart(
        self, item_id: str, action: str
    ) -> dict[str, Any]:
        """Settle an interrupted push: confirm, push again, or remove."""
        async with self._lock:
            item = self.get_item(item_id)
            if item.status not in (ItemStatus.CHECK_CART, ItemStatus.PUSHING):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_check_cart",
                    translation_placeholders={"status": str(item.status)},
                )
            ir.async_delete_issue(self.hass, DOMAIN, self._check_cart_issue_id(item_id))
            result: dict[str, Any] = {
                "item_id": item.id,
                "name": item.name,
                "action": action,
            }
            if action == CHECK_CART_REMOVE:
                self.data.items.remove(item)
                self._changed()
                result["status"] = "removed"
                return result
            if action == CHECK_CART_CONFIRM:
                item.pushed_quantity += item.pending_push
                item.cart_pushed_at = item.cart_pushed_at or dt_util.utcnow()
            item.pending_push = 0
            item.status = ItemStatus.IN_CART
            error = None
            if action == CHECK_CART_PUSH:
                error = await self._push([item])
            self._changed()
        result["status"] = str(item.status)
        result["pushed"] = action == CHECK_CART_PUSH and error is None
        if error:
            result["error"] = error
        return result

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

    def _response(
        self, outcome: ProcessOutcome, already_in_cart: bool = False
    ) -> dict[str, Any]:
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
        if already_in_cart:
            # Recorded as already in the Kroger cart; no cart call was made.
            response["already_in_cart"] = True
        if item.candidates:
            response["candidates"] = item.candidates
        if outcome.error:
            response["error"] = outcome.error
        if outcome.added:
            response["added"] = outcome.added
        return response

    async def _bump_duplicate(self, item: ListItem, quantity: int) -> ProcessOutcome:
        item.quantity += quantity
        if self._record_only and item.status in (ItemStatus.WAITING, ItemStatus.HELD):
            # The user says it's in the cart after all.
            item.status = ItemStatus.IN_CART
            item.out_of_stock_since = None
        error = None
        if item.status == ItemStatus.IN_CART:
            # Push only the extra units; already-pushed units are never resent.
            error = await self._push([item])
        return ProcessOutcome(
            ScanResult.DUPLICATE, item, pushed=False, error=error, added=quantity
        )

    # ------------------------------------------------------------------
    # Public operations

    async def async_scan(
        self,
        code: str | None = None,
        quantity: int = 1,
        source: ItemSource = ItemSource.SCAN,
        *,
        already_in_cart: bool = False,
        product_id: str | None = None,
        url: str | None = None,
    ) -> dict[str, Any]:
        """Handle a scanned barcode, a Kroger product ID, or a product link.

        A product ID (given directly or taken from a kroger.com link) is
        looked up as-is, with no barcode-candidate guessing.
        """
        if url is None and code and "://" in code:
            # A URL in the barcode field: usually a scanned QR code, but it
            # may be a shared Kroger product link.
            link = product_id_from_text(code)
            if link.product_id is None:
                return await self._async_ignored(code, source)
            product_id = link.product_id
        elif url is not None:
            link = product_id_from_text(url)
            if link.product_id is None:
                return await self._async_ignored(
                    url, source, LINK_IGNORED_MESSAGE, "not_a_kroger_product_link"
                )
            product_id = link.product_id
        if product_id is not None:
            product_id = product_id.strip()
            if not PRODUCT_ID.match(product_id):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_product_id",
                    translation_placeholders={"product_id": product_id},
                )
            normalized = NormalizedBarcode(
                raw=product_id,
                digits=product_id,
                kind=BarcodeKind.OTHER,
                candidates=(product_id,),
            )
        else:
            normalized = normalize_barcode(code or "")
        if normalized.kind is BarcodeKind.INVALID:
            # QR code, Data Matrix, URL or other non-product code: no item is
            # added, but tell the user (response, event, notification) so a
            # scan of the bag's QR code isn't silently lost.
            return await self._async_ignored(code or "", source)
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
            outcome = await self._recording(
                already_in_cart,
                self._process_scan(normalized, digits, quantity, source),
            )
            self._changed()
        self._fire(outcome, source)
        response = self._response(outcome, already_in_cart)
        self._notify_scan(response)
        return response

    async def _recording(self, already_in_cart: bool, coro: Any) -> ProcessOutcome:
        """Run an add/scan/resolve, optionally as "already in the Kroger cart".

        In that mode no cart call is made: matched items are recorded as in the
        cart (pushed_quantity = quantity), and items still needing review or a
        match remember it so resolving them later records instead of pushing.
        """
        self._record_only = already_in_cart
        try:
            outcome = await coro
        finally:
            self._record_only = False
        if already_in_cart and outcome.item.status in (
            ItemStatus.NEEDS_REVIEW,
            ItemStatus.UNMATCHED,
        ):
            outcome.item.already_in_cart = True
        return outcome

    async def _async_ignored(
        self,
        code: str,
        source: ItemSource,
        message: str = IGNORED_MESSAGE,
        reason: str = "not_a_product_barcode",
    ) -> dict[str, Any]:
        _LOGGER.debug("Ignoring non-product code %r", code)
        self.hass.bus.async_fire(
            EVENT_SCANNED,
            {
                "result": str(ScanResult.IGNORED),
                "item_id": None,
                "name": None,
                "brand": None,
                "size": None,
                "price": None,
                "aisle": None,
                "quantity": 0,
                "upc": None,
                "source": str(source),
                "message": message,
                "config_entry_id": self.config_entry.entry_id,
            },
        )
        response = {
            "result": str(ScanResult.IGNORED),
            "reason": reason,
            "message": message,
        }
        if self.notify_scans:
            self._notify_scan(response)
            return response
        now = monotonic()
        if (
            self.notify_targets
            and now - self._last_ignored_notice >= IGNORED_NOTIFY_INTERVAL
        ):
            self._last_ignored_notice = now
            self.config_entry.async_create_task(
                self.hass,
                self._async_notify("Scan ignored", message),
                "kroger_restock ignored notice",
            )
        return response

    def _notify_scan(self, response: dict[str, Any]) -> None:
        """One short, replaceable push per scan ("Notify on every scan")."""
        if not self.notify_scans or not self.notify_targets:
            return
        if (text := scan_notification_text(response)) is None:
            return
        actions = None
        if response.get("result") == "duplicate" and response.get("added"):
            added = response["added"]
            actions = [
                {
                    "action": (
                        f"{self._undo_prefix}{response['item_id']}"
                        f"_{response['quantity']}_{added}"
                    ),
                    "title": f"Undo +{added}",
                }
            ]
        self.config_entry.async_create_task(
            self.hass,
            self._async_notify(
                None, text, actions, data={"tag": SCAN_NOTIFICATION_TAG}
            ),
            "kroger_restock scan notice",
        )

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
        already_in_cart: bool = False,
    ) -> dict[str, Any]:
        """Add a free-text item: search, then match or flag for review."""
        name = " ".join(name.split())
        if not name:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="empty_name"
            )
        async with self._lock:
            outcome = await self._recording(
                already_in_cart, self._process_text(name, quantity, source, note)
            )
            self._changed()
        self._fire(outcome, source)
        response = self._response(outcome, already_in_cart)
        self._notify_scan(response)
        return response

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

    async def async_resolve(
        self, item_id: str, product_id: str, already_in_cart: bool = False
    ) -> dict[str, Any]:
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
            record = already_in_cart or item.already_in_cart
            existing = self._find_active(product_id=product.product_id)
            if existing is not None and existing is not item:
                self.data.items.remove(item)
                outcome = await self._recording(
                    record, self._bump_duplicate(existing, item.quantity)
                )
            else:
                self._apply_product(item, product)
                outcome = await self._recording(record, self._settle(item, product))
            self._changed()
        return self._response(outcome, record)

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
        """Apply a rename/quantity/note edit from the to-do UI.

        A trailing ``×N`` in the summary sets the quantity (same rules as
        ``set_quantity``; ``×0`` removes the item). No ``×N`` leaves it as is.
        """
        async with self._lock:
            item = self.get_item(item_id)
            quantity: int | None = None
            if summary is not None:
                text = summary.strip()
                if match := _QTY_SUFFIX.search(text):
                    quantity = int(match.group(1))
                    text = text[: match.start()].strip()
                if item.size and text.endswith(f"({item.size})"):
                    text = text[: -len(f"({item.size})")].strip()
                if text and text != item.name:
                    item.name = text
            item.note = note or None
            if quantity is not None and quantity != item.quantity:
                await self._set_quantity(item, quantity)
            elif (
                item.status == ItemStatus.IN_CART
                and item.quantity > item.pushed_quantity
            ):
                await self._push([item])
            self._changed()

    def find_item(self, name: str) -> ListItem:
        """Return the one active item called ``name`` (exact, else a clear match)."""
        active = self.active_items
        wanted = name.strip().casefold()
        exact = [i for i in active if i.name.casefold() == wanted]
        if len(exact) == 1:
            return exact[0]
        if not exact and (item := match_item(name, active)) is not None:
            return item
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="item_name_not_found",
            translation_placeholders={"name": name},
        )

    async def async_set_quantity(self, item_id: str, quantity: int) -> dict[str, Any]:
        """Set an item's quantity; 0 removes it. See ``_set_quantity``."""
        async with self._lock:
            response = await self._set_quantity(self.get_item(item_id), quantity)
            self._changed()
        return response

    async def _set_quantity(self, item: ListItem, quantity: int) -> dict[str, Any]:
        """Change the quantity (lock held).

        Not pushed yet: just the number. Already pushed: raising pushes only
        the extra units; lowering can't take units out of the Kroger cart (the
        API is write-only), so the record is lowered and the user is told how
        many to remove in the Kroger app.
        """
        if item.status in (ItemStatus.PUSHING, ItemStatus.CHECK_CART):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="quantity_check_cart_first",
                translation_placeholders={"name": item.name},
            )
        previous = item.quantity
        in_cart = item.pushed_quantity if item.status == ItemStatus.IN_CART else 0
        to_remove = max(0, in_cart - quantity)
        pushed_units = 0
        error = None
        if quantity <= 0:
            self.data.items = [i for i in self.data.items if i.id != item.id]
            result = "removed"
        else:
            item.quantity = quantity
            if to_remove:
                # Assume the user takes them out in the Kroger app.
                item.pushed_quantity = quantity
            if item.status == ItemStatus.IN_CART and quantity > item.pushed_quantity:
                before = item.pushed_quantity
                error = await self._push([item])
                pushed_units = item.pushed_quantity - before
            result = "updated"
        response: dict[str, Any] = {
            "result": result,
            "item_id": item.id,
            "name": item.name,
            "status": "removed" if result == "removed" else str(item.status),
            "previous_quantity": previous,
            "quantity": max(0, quantity),
            "pushed": pushed_units,
            "kroger_cart_remove": to_remove,
        }
        if error:
            response["error"] = error
        if to_remove:
            warning = (
                f"Remove {to_remove} from the Kroger app cart: {item.name}. "
                "Kroger's API can add to the cart but can't remove from it."
            )
            response["warning"] = warning
            self.config_entry.async_create_task(
                self.hass,
                self._async_notify("Kroger cart", warning),
                "kroger_restock quantity warning",
            )
        return response

    @property
    def _undo_prefix(self) -> str:
        return f"KROGER_RESTOCK_UNDO_{self.config_entry.entry_id}_"

    @callback
    def _undo_filter(self, event_data: dict[str, Any]) -> bool:
        return str(event_data.get("action", "")).startswith(self._undo_prefix)

    async def _handle_undo(self, event: Event) -> None:
        """Handle "Undo +N" on a duplicate-scan notification."""
        rest = str(event.data["action"])[len(self._undo_prefix) :]
        try:
            item_id, quantity, added = rest.rsplit("_", 2)
            expected, added_units = int(quantity), int(added)
        except ValueError:
            return
        item = self._item_or_none(item_id)
        if item is None or item.quantity != expected:
            # Already undone, edited since, or removed: don't guess.
            _LOGGER.debug("Undo for %s skipped: quantity changed", item_id)
            return
        try:
            await self.async_set_quantity(item_id, expected - added_units)
        except ServiceValidationError as err:
            _LOGGER.warning("Could not undo: %s", err)

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

    async def _async_notify(
        self,
        title: str | None,
        message: str,
        actions: list[dict[str, str]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Send to each configured notify target, or a persistent notification.

        ``actions`` become actionable-notification buttons on mobile app
        targets; the persistent notification explains the equivalent action.
        """
        targets = self.notify_targets
        if not targets:
            if actions:
                message += (
                    " (Use the kroger_restock.mark_cart_received action to do it.)"
                )
            if data and data.get("tag") == SCAN_NOTIFICATION_TAG:
                return  # per-scan pushes only go to phones
            persistent_notification.async_create(
                self.hass,
                message,
                title=title or "Kroger Restock",
                notification_id=f"{DOMAIN}_{self.config_entry.entry_id}",
            )
            return
        for target in targets:
            domain, _, service = target.partition(".")
            if not service:
                domain, service = "notify", domain
            payload: dict[str, Any] = {"message": message}
            if title:
                payload["title"] = title
            extra: dict[str, Any] = dict(data or {})
            if actions:
                extra["actions"] = actions
            if extra:
                payload["data"] = extra
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    payload,
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
        entry_id = self.config_entry.entry_id
        keep = {
            f"{ISSUE_GAVE_UP}_{entry_id}_": {
                i.id for i in self.data.items if i.status == ItemStatus.WAITING
            },
            f"{ISSUE_CHECK_CART}_{entry_id}_": {
                i.id for i in self.data.items if i.status == ItemStatus.CHECK_CART
            },
        }
        for domain, issue_id in list(registry.issues):
            if domain != DOMAIN:
                continue
            for prefix, ids in keep.items():
                if (
                    issue_id.startswith(prefix)
                    and issue_id.removeprefix(prefix) not in ids
                ):
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
