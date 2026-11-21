"""Track Kroger orders from order emails received by HA's IMAP integration.

Kroger's public API can't read orders. Instead, this listens for the IMAP
integration's ``imap_content`` events from the IMAP entry chosen in the
options, keeps only mail from Kroger-family domains, fetches the full text
with ``imap.fetch``, and parses it (see ``order_email``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXTRA_SENDER_DOMAINS,
    CONF_IMAP_ENTRY,
    CONF_NOTIFY_ORDERS,
    DEFAULT_NOTIFY_ORDERS,
    DOMAIN,
    EVENT_ORDER_UPDATE,
    ItemStatus,
)
from .coordinator import entry_option
from .imap_baseline import BaselineError, async_take_baseline, content_keys
from .matching import match_item, split_names
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
ISSUE_IMAP_BASELINE = "imap_baseline"
BASELINE_RETRY = timedelta(minutes=5)
IMAP_DOMAIN = "imap"
# Show "none" once the latest order has been finished this long.
FINISHED_ORDER_VISIBLE = timedelta(days=2)
# An email without an order number updates the latest active order only if
# that order changed this recently.
UNNUMBERED_MATCH_WINDOW = timedelta(days=4)
# Kroger's final receipt has no order number. It completes the most recent
# ready (pickup) or placed (delivery) order from this long ago.
RECEIPT_MATCH_WINDOW = timedelta(hours=24)
UNKNOWN_ORDER = "unknown"
# Re-adding shorted items automatically is disabled until a real Kroger email
# with item-level shortage data has been seen; none exists in the sample
# inbox (12 months of pickup orders). The matching code stays, experimental.
READD_SHORTED_AVAILABLE = False
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
ACTION_MARK_RECEIVED = "KROGER_RESTOCK_MARK_RECEIVED"
CHOICE_ALL = "ALL"
CHOICE_MISSING = "MISSING"


def missing_summary(result: dict[str, Any]) -> str:
    """Describe a mark_cart_received result in one notification."""
    parts = [f"{result['received']} marked received."]
    status_text = {
        "in_cart": "back in the cart",
        "waiting": "waiting on stock",
        "needs_review": "needs review",
        "unmatched": "needs review",
    }
    if result["missing"]:
        parts.append(
            "Added back: "
            + ", ".join(
                f"{m['name']} ({status_text.get(m['status'], m['status'])})"
                for m in result["missing"]
            )
            + "."
        )
    if result["unmatched"]:
        parts.append(
            "Couldn't match: "
            + ", ".join(f'"{name}"' for name in result["unmatched"])
            + ". Uncheck them on the list instead."
        )
    return " ".join(parts)


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
        self._retry_unsub: CALLBACK_TYPE | None = None
        self._baseline_keys: frozenset[str] = frozenset()

    @property
    def imap_entry_id(self) -> str | None:
        """The IMAP config entry to listen to, if configured."""
        value = entry_option(self.coordinator.config_entry, CONF_IMAP_ENTRY)
        return str(value) if value else None

    @callback
    def async_start(self) -> None:
        """Start listening (only if an IMAP entry is configured).

        A folder may hold years of order history, so before acting on any
        email the messages already there are recorded as seen (the baseline).
        """
        data = self.coordinator.data
        if self.imap_entry_id is None:
            if data.imap_baseline is not None:
                # Unlinked: a later re-link takes a fresh baseline.
                data.imap_baseline = None
                self.coordinator.mark_changed()
            return
        if self._baseline_ready():
            self._baseline_keys = frozenset(data.imap_baseline["keys"])  # type: ignore[index]
        else:
            self.coordinator.config_entry.async_create_background_task(
                self.hass, self.async_ensure_baseline(), "kroger_restock imap baseline"
            )
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
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    # ------------------------------------------------------------------
    # Folder baseline

    def _imap_settings(self) -> tuple[str, str] | None:
        entry = self.hass.config_entries.async_get_entry(self.imap_entry_id or "")
        if entry is None:
            return None
        return (
            str(entry.data.get("folder", "INBOX")),
            str(entry.data.get("search", "UnSeen UnDeleted")),
        )

    def _baseline_ready(self) -> bool:
        """Return True if a baseline exists for this entry, folder and search."""
        baseline = self.coordinator.data.imap_baseline
        settings = self._imap_settings()
        return (
            baseline is not None
            and settings is not None
            and baseline.get("entry_id") == self.imap_entry_id
            and (baseline.get("folder"), baseline.get("search")) == settings
        )

    def _baseline_issue_id(self) -> str:
        return f"{ISSUE_IMAP_BASELINE}_{self.coordinator.config_entry.entry_id}"

    async def async_ensure_baseline(self, _now: Any = None) -> bool:
        """Take the baseline if needed. Returns True once one is in place."""
        if self._baseline_ready():
            return True
        entry = self.hass.config_entries.async_get_entry(self.imap_entry_id or "")
        try:
            if entry is None:
                raise BaselineError("The selected IMAP connection no longer exists")
            baseline = await async_take_baseline(entry.entry_id, entry.data)
        except BaselineError as err:
            _LOGGER.warning("Couldn't baseline the order-email folder: %s", err)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._baseline_issue_id(),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_IMAP_BASELINE,
                translation_placeholders={
                    "imap": entry.title if entry else str(self.imap_entry_id),
                    "error": str(err),
                },
            )
            if self._retry_unsub is None:
                self._retry_unsub = async_track_time_interval(
                    self.hass,
                    self.async_ensure_baseline,
                    BASELINE_RETRY,
                    name="kroger_restock imap baseline retry",
                )
            return False
        self.coordinator.data.imap_baseline = {
            "entry_id": baseline.entry_id,
            "folder": baseline.folder,
            "search": baseline.search,
            "keys": sorted(baseline.keys),
            "count": baseline.count,
            "taken_at": dt_util.utcnow().isoformat(),
        }
        self._baseline_keys = baseline.keys
        self.coordinator.mark_changed()
        await self.coordinator.async_flush()
        ir.async_delete_issue(self.hass, DOMAIN, self._baseline_issue_id())
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None
        _LOGGER.info(
            "Baselined %d existing messages in folder %s",
            baseline.count,
            baseline.folder,
        )
        return True

    @property
    def _action_id(self) -> str:
        return f"{ACTION_MARK_RECEIVED}_{self.coordinator.config_entry.entry_id}"

    @callback
    def _action_filter(self, event_data: dict[str, Any]) -> bool:
        return str(event_data.get("action", "")).startswith(self._action_id)

    async def _handle_notification_action(self, event: Event) -> None:
        """Handle "All received" / "Some missing…" on the order-complete prompt.

        Kroger reports last-minute out-of-stock items and replacements by text
        message, which the integration can't see, so the user says what
        didn't arrive. Those items go back on the list (stock check, then back
        into the cart for the next order); everything else is marked received.
        """
        rest = str(event.data["action"]).removeprefix(self._action_id).lstrip("_")
        number, _, choice = rest.rpartition("_")
        if choice not in (CHOICE_ALL, CHOICE_MISSING):
            number, choice = rest, CHOICE_ALL  # v0.7.0-dev action IDs
        order = next(
            (o for o in self.coordinator.data.orders if o.order_number == number), None
        )
        cutoff = (order.placed_at or order.completed_at) if order else None
        if choice == CHOICE_ALL:
            await self.coordinator.async_mark_cart_received(before=cutoff)
            return
        reply = str(event.data.get("reply_text") or "").strip()
        if not reply:
            await self.coordinator.async_notify(
                "Nothing marked",
                "No missing items were entered. Open the grocery list and uncheck "
                "what didn't arrive, or answer the prompt again.",
            )
            return
        result = await self.coordinator.async_mark_cart_received(
            before=cutoff, missing=split_names(reply)
        )
        await self.coordinator.async_notify(
            "Kroger order: missing items", missing_summary(result)
        )

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
        """Content keys for one email: Message-ID (if sent) and a content hash.

        HA's IMAP integration reports SEARCH sequence numbers as ``uid``; they
        shift when mail leaves the folder, so they're never used for "seen".
        The same keys are recorded by the folder baseline.
        """
        headers = data.get("headers") or {}
        message_id = None
        if isinstance(headers, dict):
            for name, value in headers.items():
                if str(name).lower() == "message-id":
                    message_id = value[0] if isinstance(value, (list, tuple)) else value
                    break
        return content_keys(
            data.get("sender"),
            data.get("subject"),
            data.get("date"),
            str(message_id) if message_id else None,
        )

    def _is_seen(self, keys: list[str]) -> bool:
        seen = self.coordinator.data.seen_emails
        return any(key in seen or key in self._baseline_keys for key in keys)

    async def _handle_event(self, event: Event) -> None:
        data = event.data
        if not self._baseline_ready():
            _LOGGER.debug(
                "Ignoring Kroger email until the folder baseline is taken: %s",
                data.get("subject"),
            )
            return
        keys = self.email_keys(data)
        if self._is_seen(keys):
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
        action = f"{self._action_id}_{order.order_number}"
        actions: list[dict[str, str]] = [
            {"action": f"{action}_{CHOICE_ALL}", "title": "All received"},
            {
                "action": f"{action}_{CHOICE_MISSING}",
                "title": "Some missing…",
                "behavior": "textInput",
                "textInputButtonTitle": "Add back",
                "textInputPlaceholder": "What didn't come? e.g. eggs, milk",
            },
        ]
        if todo := self._todo_entity_id():
            actions.append(
                {
                    "action": "URI",
                    "title": "Open list",
                    "uri": f"/todo?entity_id={todo}",
                }
            )
        await self.coordinator.async_notify(
            f"Kroger order {verb}",
            f"Mark the {count} in-cart {plural} received? If anything was out of "
            "stock or replaced, tap Some missing… and type what didn't come.",
            actions=actions,
        )

    def _todo_entity_id(self) -> str | None:
        registry = er.async_get(self.hass)
        return registry.async_get_entity_id(
            "todo", DOMAIN, f"{self.coordinator.config_entry.entry_id}_todo"
        )
