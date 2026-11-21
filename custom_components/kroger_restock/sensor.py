"""Count and timestamp sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import KrogerConfigEntry
from .const import ItemStatus
from .coordinator import KrogerRestockCoordinator
from .entity import KrogerRestockEntity
from .order_email import OrderStatus
from .orders import current_order

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class KrogerSensorDescription(SensorEntityDescription):
    """Describes a Kroger Restock sensor."""

    value_fn: Callable[[KrogerRestockCoordinator], int | datetime | None]


def _counter(status: ItemStatus) -> KrogerSensorDescription:
    return KrogerSensorDescription(
        key=str(status),
        translation_key=str(status),
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.count(status),
    )


SENSORS: tuple[KrogerSensorDescription, ...] = (
    _counter(ItemStatus.IN_CART),
    _counter(ItemStatus.WAITING),
    _counter(ItemStatus.HELD),
    _counter(ItemStatus.NEEDS_REVIEW),
    _counter(ItemStatus.UNMATCHED),
    KrogerSensorDescription(
        key="last_stock_check",
        translation_key="last_stock_check",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.last_stock_check(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KrogerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            *(KrogerSensor(coordinator, d) for d in SENSORS),
            KrogerOrderSensor(coordinator),
        ]
    )


class KrogerSensor(KrogerRestockEntity, SensorEntity):
    """A Kroger Restock sensor."""

    entity_description: KrogerSensorDescription

    def __init__(
        self,
        coordinator: KrogerRestockCoordinator,
        description: KrogerSensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | datetime | None:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator)


class KrogerOrderSensor(KrogerRestockEntity, SensorEntity):
    """Status of the current Kroger order, from order emails."""

    _attr_translation_key = "order"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [str(s) for s in OrderStatus]

    def __init__(self, coordinator: KrogerRestockCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "order")

    @property
    def native_value(self) -> str:
        """Return the order status, or "none"."""
        order = current_order(self.coordinator.data.orders, dt_util.utcnow())
        return str(order.status) if order else str(OrderStatus.NONE)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Order details."""
        orders = self.coordinator.data.orders
        order = current_order(orders, dt_util.utcnow())
        attrs: dict[str, object] = {
            "recent_orders": [
                {
                    "order_number": o.order_number,
                    "status": o.status,
                    "updated": o.updated_at.isoformat(),
                }
                for o in orders[:5]
            ]
        }
        if order is not None:
            attrs.update(
                {
                    "order_number": order.order_number,
                    "window": order.window,
                    "modality": order.modality,
                    "item_count": order.item_count,
                    "total": order.total,
                    "updated": order.updated_at.isoformat(),
                    "placed": order.placed_at.isoformat() if order.placed_at else None,
                    "shorted_items": order.shorted,
                    "substitutions": order.substitutions,
                    "last_email": order.last_subject,
                }
            )
        return attrs
