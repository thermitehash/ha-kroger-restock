"""Pre-order cart check: a weekly "does this match your Kroger cart?" prompt.

The public API can't read the cart, so before each order day the user gets
a notification listing what Home Assistant believes is in the Kroger cart.
They can confirm it matches, record items that are in the cart but missing
from Home Assistant (recorded with ``already_in_cart``; nothing is sent to
Kroger), or open the list. This never touches the cart.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CART_CHECK,
    CONF_CART_CHECK_DAY,
    CONF_CART_CHECK_HOURS,
    CONF_CART_CHECK_TIME,
    DEFAULT_CART_CHECK_DAY,
    DEFAULT_CART_CHECK_HOURS,
    DEFAULT_CART_CHECK_TIME,
    DOMAIN,
    ItemSource,
    ItemStatus,
)
from .coordinator import entry_option
from .matching import split_names
from .schedule import next_cart_check

if TYPE_CHECKING:
    from .coordinator import KrogerRestockCoordinator

_LOGGER = logging.getLogger(__name__)

EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
ACTION_PREFIX = "KROGER_RESTOCK_CARTCHECK"
CHOICE_OK = "OK"
CHOICE_MISSING = "MISSING"
MAX_LISTED = 15


class CartCheck:
    """Schedules and answers the pre-order cart check."""

    def __init__(
        self, hass: HomeAssistant, coordinator: KrogerRestockCoordinator
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.coordinator = coordinator
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timer: CALLBACK_TYPE | None = None
        self.next_run: datetime | None = None

    @property
    def _entry(self) -> Any:
        return self.coordinator.config_entry

    @property
    def enabled(self) -> bool:
        """Whether the scheduled check is on."""
        return bool(entry_option(self._entry, CONF_CART_CHECK, False))

    @property
    def _action_id(self) -> str:
        return f"{ACTION_PREFIX}_{self._entry.entry_id}"

    @callback
    def async_start(self) -> None:
        """Listen for the notification's buttons; schedule if enabled."""
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_NOTIFICATION_ACTION,
                self._handle_action,
                event_filter=self._action_filter,
            )
        )
        if self.enabled:
            self._schedule()

    @callback
    def _action_filter(self, event_data: dict[str, Any]) -> bool:
        return str(event_data.get("action", "")).startswith(self._action_id)

    @callback
    def async_stop(self) -> None:
        """Cancel the timer and listeners."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._timer is not None:
            self._timer()
            self._timer = None

    @callback
    def _schedule(self) -> None:
        self.next_run = next_cart_check(
            dt_util.now(),
            self.coordinator.order_days,
            float(
                entry_option(
                    self._entry, CONF_CART_CHECK_HOURS, DEFAULT_CART_CHECK_HOURS
                )
            ),
            str(entry_option(self._entry, CONF_CART_CHECK_DAY, DEFAULT_CART_CHECK_DAY)),
            str(
                entry_option(self._entry, CONF_CART_CHECK_TIME, DEFAULT_CART_CHECK_TIME)
            ),
        )
        _LOGGER.debug("Next cart check at %s", self.next_run)
        self._timer = async_track_point_in_time(self.hass, self._fire, self.next_run)

    async def _fire(self, _now: datetime) -> None:
        self._timer = None
        await self.async_send()
        self._schedule()

    def summary(self) -> dict[str, Any]:
        """Return what Home Assistant believes is in the Kroger cart."""
        items = self.coordinator.items
        in_cart = [
            {"item_id": i.id, "name": i.name, "quantity": i.pushed_quantity}
            for i in items
            if i.status == ItemStatus.IN_CART and i.pushed_quantity > 0
        ]
        unconfirmed = [
            {"item_id": i.id, "name": i.name}
            for i in items
            if i.status in (ItemStatus.CHECK_CART, ItemStatus.PUSHING)
        ]
        waiting = sum(1 for i in items if i.status == ItemStatus.WAITING)
        return {"in_cart": in_cart, "unconfirmed": unconfirmed, "waiting": waiting}

    def message(self, summary: dict[str, Any]) -> str:
        """Notification text."""
        in_cart = summary["in_cart"]
        units = sum(i["quantity"] for i in in_cart)
        if in_cart:
            listed = ", ".join(
                f"{i['name']} ×{i['quantity']}" for i in in_cart[:MAX_LISTED]
            )
            more = len(in_cart) - MAX_LISTED
            if more > 0:
                listed += f", and {more} more"
            text = (
                f"Home Assistant thinks your Kroger cart has {units} "
                f"item{'s' if units != 1 else ''}: {listed}."
            )
        else:
            text = "Home Assistant doesn't think anything is in your Kroger cart."
        if summary["unconfirmed"]:
            names = ", ".join(i["name"] for i in summary["unconfirmed"])
            text += f" Not confirmed yet (check Repairs): {names}."
        if summary["waiting"]:
            text += f" {summary['waiting']} waiting on stock."
        return text

    async def async_send(self) -> dict[str, Any]:
        """Send the cart check now. Returns the summary."""
        summary = self.summary()
        actions = [
            {"action": f"{self._action_id}_{CHOICE_OK}", "title": "Matches"},
            {
                "action": f"{self._action_id}_{CHOICE_MISSING}",
                "title": "Something's missing from HA",
                "behavior": "textInput",
                "textInputButtonTitle": "Record",
                "textInputPlaceholder": "Items in the cart, e.g. peanut butter, eggs",
            },
        ]
        registry = er.async_get(self.hass)
        if todo := registry.async_get_entity_id(
            "todo", DOMAIN, f"{self._entry.entry_id}_todo"
        ):
            actions.append(
                {
                    "action": "URI",
                    "title": "Open list",
                    "uri": f"/todo?entity_id={todo}",
                }
            )
        await self.coordinator.async_notify(
            "Kroger cart check", self.message(summary), actions=actions
        )
        return summary

    async def _handle_action(self, event: Event) -> None:
        choice = str(event.data["action"]).removeprefix(self._action_id).lstrip("_")
        if choice != CHOICE_MISSING:
            return  # "Matches": nothing to do
        reply = str(event.data.get("reply_text") or "").strip()
        if not reply:
            return
        await self.async_record_missing(split_names(reply))

    async def async_record_missing(self, names: list[str]) -> dict[str, Any]:
        """Record items that are in the Kroger cart but not in Home Assistant."""
        recorded, review, unknown = [], [], []
        for name in names:
            result = await self.coordinator.async_add_text(
                name, source=ItemSource.MANUAL, already_in_cart=True
            )
            if result["result"] in ("in_cart", "duplicate"):
                recorded.append(result["name"])
            elif result["result"] == "needs_review":
                review.append(name)
            else:
                unknown.append(name)
        parts = []
        if recorded:
            parts.append("Recorded as in your cart: " + ", ".join(recorded) + ".")
        if review:
            parts.append(
                "Pick the product on the list (it'll be recorded, not added again): "
                + ", ".join(review)
                + "."
            )
        if unknown:
            parts.append("Not found in the catalog: " + ", ".join(unknown) + ".")
        await self.coordinator.async_notify("Kroger cart check", " ".join(parts))
        return {"recorded": recorded, "needs_review": review, "not_found": unknown}
