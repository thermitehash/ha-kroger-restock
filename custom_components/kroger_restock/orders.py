"""Track Kroger orders from order emails received by HA's IMAP integration.

Kroger's public API can't read orders. Instead, this listens for the IMAP
integration's ``imap_content`` events from the IMAP entry chosen in the
options, keeps only mail from Kroger-family domains, fetches the full text
with ``imap.fetch``, and parses it (see ``order_email``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_IMAP_ENTRY,
    CONF_NOTIFY_ORDERS,
    CONF_READD_SHORTED,
    DEFAULT_NOTIFY_ORDERS,
    DEFAULT_READD_SHORTED,
    EVENT_ORDER_UPDATE,
    ItemStatus,
)
from .coordinator import entry_option
from .order_email import (
    ACTIVE_ORDER_STATUSES,
    UPDATE_ONLY,
    OrderStatus,
    is_kroger_sender,
    parse_order_email,
)
from .store import MAX_ORDERS, MAX_SEEN_EMAILS, KrogerOrder, ListItem

if TYPE_CHECKING:
    from .coordinator import KrogerRestockCoordinator

_LOGGER = logging.getLogger(__name__)

EVENT_IMAP_CONTENT = "imap_content"
IMAP_DOMAIN = "imap"
# Show "none" once the latest order has been finished this long.
FINISHED_ORDER_VISIBLE = timedelta(days=2)
# An email without an order number updates the latest active order only if
# that order changed this recently.
UNNUMBERED_MATCH_WINDOW = timedelta(days=4)
MATCH_THRESHOLD = 0.6
UNKNOWN_ORDER = "unknown"

_NOTIFY_STATUSES = frozenset(
    {OrderStatus.READY, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.CANCELLED}
)

_STATUS_TITLES = {
    OrderStatus.PLACED: "Kroger order placed",
    OrderStatus.SHOPPING: "Kroger is shopping your order",
    OrderStatus.READY: "Kroger order ready for pickup",
    OrderStatus.OUT_FOR_DELIVERY: "Kroger order out for delivery",
    OrderStatus.COMPLETED: "Kroger order complete",
    OrderStatus.CANCELLED: "Kroger order cancelled",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {
        w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if len(w) > 1
    }


def match_item(name: str, items: list[ListItem]) -> ListItem | None:
    """Return the one list item that clearly matches a shorted item name."""
    wanted = _tokens(name)
    if not wanted:
        return None
    scored: list[tuple[float, ListItem]] = []
    for item in items:
        have = _tokens(f"{item.brand or ''} {item.name}")
        if not have:
            continue
        score = len(wanted & have) / len(wanted)
        if score >= MATCH_THRESHOLD:
            scored.append((score, item))
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None  # ambiguous
    return scored[0][1]


def current_order(orders: list[KrogerOrder], now: datetime) -> KrogerOrder | None:
    """Return the order the sensor should show, or None."""
    if not orders:
        return None
    active = [o for o in orders if o.status in ACTIVE_ORDER_STATUSES]
    if active:
        return max(active, key=lambda o: o.updated_at)
    latest = max(orders, key=lambda o: o.updated_at)
    if now - latest.updated_at <= FINISHED_ORDER_VISIBLE:
        return latest
    return None


class OrderWatcher:
    """Listens for order emails and keeps ``coordinator.data.orders`` current."""

    def __init__(
        self, hass: HomeAssistant, coordinator: KrogerRestockCoordinator
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.coordinator = coordinator
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def imap_entry_id(self) -> str | None:
        """The IMAP config entry to listen to, if configured."""
        value = entry_option(self.coordinator.config_entry, CONF_IMAP_ENTRY)
        return str(value) if value else None

    @callback
    def async_start(self) -> None:
        """Start listening (only if an IMAP entry is configured)."""
        if self.imap_entry_id is None:
            return
        self._unsub = self.hass.bus.async_listen(
            EVENT_IMAP_CONTENT, self._handle_event, event_filter=self._filter
        )

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _filter(self, event_data: dict[str, Any]) -> bool:
        return event_data.get("entry_id") == self.imap_entry_id and is_kroger_sender(
            str(event_data.get("sender", ""))
        )

    async def _handle_event(self, event: Event) -> None:
        data = event.data
        key = f"{data.get('entry_id')}:{data.get('uid')}"
        if key in self.coordinator.data.seen_emails:
            return
        text = await self._fetch_text(data)
        received = data.get("date")
        if not isinstance(received, datetime):
            received = dt_util.utcnow()
        try:
            await self.async_process_email(
                subject=str(data.get("subject", "")),
                text=text,
                received=received,
                key=key,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not process Kroger order email: %s", err)

    async def _fetch_text(self, data: dict[str, Any]) -> str:
        """Get the full message text; fall back to the event's (truncated) text."""
        entry_id, uid = data.get("entry_id"), data.get("uid")
        entry = self.hass.config_entries.async_get_entry(str(entry_id))
        if (
            entry is not None
            and entry.state is ConfigEntryState.LOADED
            and uid is not None
            and self.hass.services.has_service(IMAP_DOMAIN, "fetch")
        ):
            try:
                response = await self.hass.services.async_call(
                    IMAP_DOMAIN,
                    "fetch",
                    {"entry": entry_id, "uid": str(uid)},
                    blocking=True,
                    return_response=True,
                )
            except HomeAssistantError as err:
                _LOGGER.debug("imap.fetch failed, using event text: %s", err)
            else:
                if isinstance(response, dict) and response.get("text"):
                    return str(response["text"])
        return str(data.get("text") or "")

    def _find_order(self, number: str | None, now: datetime) -> KrogerOrder | None:
        orders = self.coordinator.data.orders
        if number:
            return next((o for o in orders if o.order_number == number), None)
        recent = [
            o
            for o in orders
            if o.status in ACTIVE_ORDER_STATUSES
            and now - o.updated_at <= UNNUMBERED_MATCH_WINDOW
        ]
        return max(recent, key=lambda o: o.updated_at) if recent else None

    async def async_process_email(
        self, *, subject: str, text: str, received: datetime, key: str
    ) -> KrogerOrder | None:
        """Apply one order email. Returns the updated order, if any."""
        coordinator = self.coordinator
        data = coordinator.data
        data.seen_emails = [*data.seen_emails, key][-MAX_SEEN_EMAILS:]
        parsed = parse_order_email(subject, text)
        if parsed.status is None:
            _LOGGER.debug("Kroger email not recognised as an order update: %s", subject)
            coordinator.mark_changed()
            return None

        now = dt_util.as_utc(received)
        order = self._find_order(parsed.order_number, now)
        previous = str(order.status) if order is not None else str(OrderStatus.NONE)
        if order is None:
            if parsed.status == UPDATE_ONLY and parsed.order_number is None:
                coordinator.mark_changed()
                return None
            order = KrogerOrder(
                order_number=parsed.order_number or UNKNOWN_ORDER,
                status=(
                    OrderStatus.PLACED
                    if parsed.status == UPDATE_ONLY
                    else parsed.status
                ),
                updated_at=now,
            )
            data.orders = [order, *data.orders][:MAX_ORDERS]

        if parsed.status != UPDATE_ONLY:
            order.status = parsed.status
        if order.status == OrderStatus.PLACED and order.placed_at is None:
            order.placed_at = now
        if parsed.order_number and order.order_number == UNKNOWN_ORDER:
            order.order_number = parsed.order_number
        order.updated_at = max(order.updated_at, now)
        order.window = parsed.window or order.window
        order.modality = parsed.modality or order.modality
        order.last_subject = subject[:200]
        new_shorted = [s for s in parsed.shorted if s not in order.shorted]
        order.shorted = [*order.shorted, *new_shorted]
        order.substitutions = [
            *order.substitutions,
            *(s for s in parsed.substitutions if s not in order.substitutions),
        ]
        if order.status != previous or not order.history:
            order.history = [
                *order.history,
                {"status": str(order.status), "at": now.isoformat()},
            ][-20:]

        matched = self._match_shorted(new_shorted)
        readded: list[str] = []
        if matched and entry_option(
            coordinator.config_entry, CONF_READD_SHORTED, DEFAULT_READD_SHORTED
        ):
            for item in matched.values():
                await coordinator.async_readd(item.id)
                readded.append(item.id)
        coordinator.mark_changed()

        self.hass.bus.async_fire(
            EVENT_ORDER_UPDATE,
            {
                "order_number": order.order_number,
                "status": str(order.status),
                "previous_status": str(previous),
                "window": order.window,
                "modality": order.modality,
                "shorted": new_shorted,
                "shorted_item_ids": {n: i.id for n, i in matched.items()},
                "readded_item_ids": readded,
                "substitutions": parsed.substitutions,
                "subject": order.last_subject,
                "config_entry_id": coordinator.config_entry.entry_id,
            },
        )
        await self._notify(order, previous, new_shorted, matched, readded)
        return order

    def _match_shorted(self, names: list[str]) -> dict[str, ListItem]:
        candidates = [
            i
            for i in self.coordinator.items
            if i.status in (ItemStatus.IN_CART, ItemStatus.RECEIVED) and i.product_id
        ]
        matched: dict[str, ListItem] = {}
        for name in names:
            if (item := match_item(name, candidates)) is not None:
                matched[name] = item
        return matched

    async def _notify(
        self,
        order: KrogerOrder,
        previous: str,
        shorted: list[str],
        matched: dict[str, ListItem],
        readded: list[str],
    ) -> None:
        """Notify on ready / out for delivery / cancelled, and on missing items."""
        if not entry_option(
            self.coordinator.config_entry, CONF_NOTIFY_ORDERS, DEFAULT_NOTIFY_ORDERS
        ):
            return
        status_changed = order.status != previous and order.status in _NOTIFY_STATUSES
        if not status_changed and not shorted:
            return

        parts: list[str] = []
        if status_changed:
            title = _STATUS_TITLES[OrderStatus(order.status)]
            parts.append(order.window or f"Order {order.order_number}.")
        else:
            title = "Kroger order: items missing"
        if shorted:
            found = list(matched)
            others = [name for name in shorted if name not in matched]
            if readded:
                parts.append("Added back to your list: " + ", ".join(found) + ".")
            elif found:
                parts.append(
                    "Missing: " + ", ".join(found) + ". Uncheck them on the list "
                    "to order them again."
                )
            if others:
                label = "Also missing: " if found else "Missing: "
                parts.append(label + ", ".join(others) + ".")
        await self.coordinator.async_notify(title, " ".join(parts))
