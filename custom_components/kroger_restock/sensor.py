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

from . import KrogerConfigEntry
from .const import ItemStatus
from .coordinator import KrogerRestockCoordinator
from .entity import KrogerRestockEntity

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
    async_add_entities(KrogerSensor(coordinator, d) for d in SENSORS)


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
