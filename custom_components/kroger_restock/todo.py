"""To-do list entity: the household grocery list."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import KrogerConfigEntry
from .const import ItemSource, ItemStatus
from .coordinator import KrogerRestockCoordinator
from .entity import KrogerRestockEntity
from .store import ListItem

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KrogerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do list."""
    async_add_entities([KrogerRestockTodoList(entry.runtime_data.coordinator)])


def item_summary(item: ListItem) -> str:
    """Return ``Name (size) ×qty``."""
    text = item.name
    if item.size:
        text = f"{text} ({item.size})"
    if item.quantity > 1:
        text = f"{text} ×{item.quantity}"
    return text


def _date(value) -> str:  # type: ignore[no-untyped-def]
    local = dt_util.as_local(value)
    return f"{local:%b} {local.day}"


def status_line(item: ListItem) -> str:
    """Return a one-line status, e.g. ``In cart · Aisle 12``."""
    aisle = item.aisle_label
    match item.status:
        case ItemStatus.IN_CART:
            text = (
                "In cart"
                if item.pushed_quantity >= item.quantity
                else "Cart push pending"
            )
        case ItemStatus.WAITING:
            since = item.out_of_stock_since
            text = (
                f"Waiting on stock since {_date(since)}"
                if since
                else "Waiting on stock"
            )
        case ItemStatus.HELD:
            text = "Back in stock · held for order day"
        case ItemStatus.NEEDS_REVIEW:
            text = "Needs review"
            if item.candidates:
                text += f" · {len(item.candidates)} possible matches"
        case ItemStatus.UNMATCHED:
            text = "Not found in the Kroger catalog · fix with resolve_item"
        case ItemStatus.RECEIVED:
            text = (
                f"Received {_date(item.received_at)}"
                if item.received_at
                else "Received"
            )
    if aisle and item.status in (
        ItemStatus.IN_CART,
        ItemStatus.WAITING,
        ItemStatus.HELD,
    ):
        text += f" · {aisle}"
    return text


class KrogerRestockTodoList(KrogerRestockEntity, TodoListEntity):
    """The grocery list. Home Assistant is the source of truth."""

    _attr_translation_key = "grocery_list"
    _attr_name = None
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator: KrogerRestockCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "todo")
        self._update_items()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_items()
        super()._handle_coordinator_update()

    def _update_items(self) -> None:
        items: list[TodoItem] = []
        for item in self.coordinator.items:
            description = status_line(item)
            if item.note:
                description = f"{description}\n{item.note}"
            items.append(
                TodoItem(
                    uid=item.id,
                    summary=item_summary(item),
                    status=(
                        TodoItemStatus.COMPLETED
                        if item.status == ItemStatus.RECEIVED
                        else TodoItemStatus.NEEDS_ACTION
                    ),
                    description=description,
                    completed=item.received_at,
                )
            )
        self._attr_todo_items = items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Typed or spoken item: product search, then match or review."""
        await self.coordinator.async_add_text(
            item.summary or "",
            source=ItemSource.MANUAL,
            note=item.description or None,
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Check off, uncheck, rename or change the quantity."""
        assert item.uid is not None
        current = self.coordinator.get_item(item.uid)
        if (
            item.status == TodoItemStatus.COMPLETED
            and current.status != ItemStatus.RECEIVED
        ):
            await self.coordinator.async_set_received(item.uid)
            return
        if (
            item.status == TodoItemStatus.NEEDS_ACTION
            and current.status == ItemStatus.RECEIVED
        ):
            # Unchecked: shorted at pickup. Stock check, then push again.
            await self.coordinator.async_readd(item.uid)
            return
        note = item.description
        if note is not None:
            # Drop our generated status line so only the user's note is kept.
            first, _, rest = note.partition("\n")
            note = rest if first == status_line(current) else note
        await self.coordinator.async_edit(item.uid, item.summary, note)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove items entirely."""
        await self.coordinator.async_delete(uids)

    async def async_move_todo_item(
        self, uid: str, previous_uid: str | None = None
    ) -> None:
        """Reorder."""
        await self.coordinator.async_move(uid, previous_uid)
