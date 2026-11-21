"""Track Kroger orders from order emails received by HA's IMAP integration.

Kroger's public API can't read orders. Instead, this listens for the IMAP
integration's ``imap_content`` events from the IMAP entry chosen in the
options, keeps only mail from Kroger-family domains, fetches the full text
with ``imap.fetch``, and parses it (see ``order_email``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import logging
import re
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXTRA_SENDER_DOMAINS,
    CONF_IMAP_ENTRY,
    CONF_NOTIFY_ORDERS,
    DEFAULT_NOTIFY_ORDERS,
    EVENT_ORDER_UPDATE,
    ItemStatus,
)
from .coordinator import entry_option
from .order_email import (
    ACTIVE_ORDER_STATUSES,
    UPDATE_ONLY,
    OrderEmail,
    OrderStatus,
    is_order_sender,
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
# Kroger's final receipt has no order number. It completes the most recent
# ready (pickup) or placed (delivery) order from this long ago.
RECEIPT_MATCH_WINDOW = timedelta(hours=24)
MATCH_THRESHOLD = 0.6
UNKNOWN_ORDER = "unknown"
# Re-adding shorted items automatically is disabled until a real Kroger email
# with item-level shortage data has been seen; none exists in the sample
# inbox (12 months of pickup orders). The matching code stays, experimental.
READD_SHORTED_AVAILABLE = False
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
ACTION_MARK_RECEIVED = "KROGER_RESTOCK_MARK_RECEIVED"

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
        self._unsubs: list[CALLBACK_TYPE] = []

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
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_IMAP_CONTENT, self._handle_event, event_filter=self._filter
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_NOTIFICATION_ACTION,
                self._handle_notification_action,
                event_filter=self._action_filter,
            )
        )

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @property
    def _action_id(self) -> str:
        return f"{ACTION_MARK_RECEIVED}_{self.coordinator.config_entry.entry_id}"

    @callback
    def _action_filter(self, event_data: dict[str, Any]) -> bool:
        return str(event_data.get("action", "")).startswith(self._action_id)

    async def _handle_notification_action(self, event: Event) -> None:
        """Handle a tap on "Mark received" in the order-complete notification."""
        number = str(event.data["action"]).removeprefix(self._action_id).lstrip("_")
        order = next(
            (o for o in self.coordinator.data.orders if o.order_number == number), None
        )
        cutoff = (order.placed_at or order.completed_at) if order else None
        count = await self.coordinator.async_mark_cart_received(before=cutoff)
        _LOGGER.debug("Marked %s in-cart items received for order %s", count, number)

    @property
    def extra_domains(self) -> tuple[str, ...]:
        """Additional sender domains from the options (comma separated)."""
        raw = entry_option(self.coordinator.config_entry, CONF_EXTRA_SENDER_DOMAINS, "")
        return tuple(d.strip() for d in str(raw or "").split(",") if d.strip())

    @callback
    def _filter(self, event_data: dict[str, Any]) -> bool:
        return event_data.get("entry_id") == self.imap_entry_id and is_order_sender(
            str(event_data.get("sender", "")), self.extra_domains
        )

    @staticmethod
    def email_keys(data: dict[str, Any]) -> list[str]:
        """Keys identifying one email: IMAP UID, and Message-ID or content.

        UIDs change when a message moves folder, so a second key based on the
        Message-ID header (when the IMAP entry sends headers) or on sender,
        subject and date catches the same email seen again.
        """
        keys = [f"uid:{data.get('entry_id')}:{data.get('uid')}"]
        headers = data.get("headers") or {}
        message_id = None
        if isinstance(headers, dict):
            for name, value in headers.items():
                if str(name).lower() == "message-id":
                    message_id = value[0] if isinstance(value, (list, tuple)) else value
                    break
        if message_id:
            keys.append(f"mid:{str(message_id).strip()}")
        else:
            raw = f"{data.get('sender')}|{data.get('subject')}|{data.get('date')}"
            keys.append("sha:" + hashlib.sha1(raw.encode()).hexdigest()[:20])
        return keys

    async def _handle_event(self, event: Event) -> None:
        data = event.data
        keys = self.email_keys(data)
        if any(key in self.coordinator.data.seen_emails for key in keys):
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
                keys=keys,
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

    def _find_order(self, parsed: OrderEmail, now: datetime) -> KrogerOrder | None:
        orders = self.coordinator.data.orders
        if parsed.order_number:
            return next(
                (o for o in orders if o.order_number == parsed.order_number), None
            )
        if parsed.status == OrderStatus.COMPLETED:
            return self._match_receipt(parsed, now)
        recent = [
            o
            for o in orders
            if o.status in ACTIVE_ORDER_STATUSES
            and now - o.updated_at <= UNNUMBERED_MATCH_WINDOW
        ]
        return max(recent, key=lambda o: o.updated_at) if recent else None

    def _match_receipt(self, parsed: OrderEmail, now: datetime) -> KrogerOrder | None:
        """Find the order a final receipt (no order number) belongs to.

        Pickup: the most recent *ready* order. Delivery (Instacart): the most
        recent *placed* delivery order. Only orders updated in the last
        24 hours count; otherwise the receipt is ignored.
        """
        recent = [
            o
            for o in self.coordinator.data.orders
            if timedelta(0) <= now - o.updated_at <= RECEIPT_MATCH_WINDOW
        ]
        ready = [o for o in recent if o.status == OrderStatus.READY]
        placed_delivery = [
            o
            for o in recent
            if o.status == OrderStatus.PLACED and o.modality == "delivery"
        ]
        if parsed.modality == "delivery":
            candidates = placed_delivery
        elif parsed.modality == "pickup":
            candidates = ready
        else:
            candidates = ready or placed_delivery
        return max(candidates, key=lambda o: o.updated_at) if candidates else None

    @staticmethod
    def _window_datetimes(
        parsed: OrderEmail, received: datetime
    ) -> tuple[datetime | None, datetime | None]:
        """Turn the email's window into local datetimes (HA's time zone).

        The email gives store-local times with no time zone; we assume the
        store is in Home Assistant's configured time zone.
        """
        if parsed.window_start is None or parsed.window_end is None:
            return None, None
        tz = dt_util.get_default_time_zone()
        local_received = dt_util.as_local(received).date()
        day: date | None = parsed.window_date
        if parsed.window_relative == "today":
            day = local_received
        elif parsed.window_relative == "tomorrow":
            day = local_received + timedelta(days=1)
        elif day is not None and day.year == 1900:
            day = day.replace(year=local_received.year)
            if day < local_received - timedelta(days=180):
                day = day.replace(year=day.year + 1)
        if day is None:
            return None, None
        start = datetime.combine(day, parsed.window_start, tz)
        end = datetime.combine(day, parsed.window_end, tz)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    async def async_process_email(
        self,
        *,
        subject: str,
        text: str,
        received: datetime,
        keys: list[str],
    ) -> KrogerOrder | None:
        """Apply one order email. Returns the updated order, if any."""
        coordinator = self.coordinator
        data = coordinator.data
        data.seen_emails = [*data.seen_emails, *keys][-MAX_SEEN_EMAILS:]
        parsed = parse_order_email(subject, text)
        if parsed.status is None:
            _LOGGER.debug("Kroger email not recognised as an order update: %s", subject)
            coordinator.mark_changed()
            return None

        now = dt_util.as_utc(received)
        order = self._find_order(parsed, now)
        previous = str(order.status) if order is not None else str(OrderStatus.NONE)
        if order is None:
            # An email without an order number (e.g. Kroger's "final receipt")
            # can only update an order we already know about, and a "changes"
            # email says nothing about status, so neither creates an order.
            if parsed.status == UPDATE_ONLY or (
                parsed.order_number is None and parsed.status != OrderStatus.PLACED
            ):
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
        if order.status == OrderStatus.COMPLETED and order.completed_at is None:
            order.completed_at = now
        if parsed.order_number and order.order_number == UNKNOWN_ORDER:
            order.order_number = parsed.order_number
        order.updated_at = max(order.updated_at, now)
        if parsed.window:
            order.window = parsed.window
            start, end = self._window_datetimes(parsed, received)
            if start is not None:
                order.window_start, order.window_end = start, end
        # A receipt never changes how the order was fulfilled.
        if order.modality is None or parsed.status != OrderStatus.COMPLETED:
            order.modality = parsed.modality or order.modality
        order.item_count = parsed.item_count or order.item_count
        order.total = parsed.total if parsed.total is not None else order.total
        order.fee = parsed.fee if parsed.fee is not None else order.fee
        order.last_subject = subject[:200]
        new_shorted: list[str] = []
        if parsed.shorted is not None:
            known = order.shorted or []
            new_shorted = [s for s in parsed.shorted if s not in known]
            order.shorted = [*known, *new_shorted]
        if parsed.substitutions is not None:
            known = order.substitutions or []
            order.substitutions = [
                *known,
                *(s for s in parsed.substitutions if s not in known),
            ]
        if order.status != previous or not order.history:
            order.history = [
                *order.history,
                {"status": str(order.status), "at": now.isoformat()},
            ][-20:]

        # Experimental: no real Kroger email with item-level data seen yet.
        matched = self._match_shorted(new_shorted)
        readded: list[str] = []
        if matched and READD_SHORTED_AVAILABLE:  # pragma: no cover - disabled
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
                "window_start": order.window_start.isoformat()
                if order.window_start
                else None,
                "window_end": order.window_end.isoformat()
                if order.window_end
                else None,
                "modality": order.modality,
                "shorted": new_shorted,
                "shorted_item_ids": {n: i.id for n, i in matched.items()},
                "readded_item_ids": readded,
                "substitutions": parsed.substitutions or [],
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
        """Notify on ready / out for delivery / cancelled / completed, and missing items."""
        if not entry_option(
            self.coordinator.config_entry, CONF_NOTIFY_ORDERS, DEFAULT_NOTIFY_ORDERS
        ):
            return
        changed = order.status != previous
        if changed and order.status == OrderStatus.COMPLETED:
            await self._notify_completed(order)
            return
        status_changed = changed and order.status in _NOTIFY_STATUSES
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
            if readded:  # pragma: no cover - auto re-add is disabled
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

    async def _notify_completed(self, order: KrogerOrder) -> None:
        """Ask whether to mark in-cart items received.

        The receipt email has no item list, so items are never checked off
        automatically: the user confirms with the notification's button (or
        the mark_cart_received action).
        """
        cutoff = order.placed_at or order.completed_at
        count = len(self.coordinator.in_cart_items(before=cutoff))
        verb = "delivered" if order.modality == "delivery" else "picked up"
        if count == 0:
            return
        plural = "item" if count == 1 else "items"
        await self.coordinator.async_notify(
            f"Kroger order {verb}",
            f"Mark the {count} in-cart {plural} received?",
            actions=[
                {
                    "action": f"{self._action_id}_{order.order_number}",
                    "title": "Mark received",
                }
            ],
        )
