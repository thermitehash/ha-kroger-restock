"""Buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KrogerConfigEntry
from .coordinator import KrogerRestockCoordinator
from .entity import KrogerRestockEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KrogerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([SyncButton(coordinator), CheckStockButton(coordinator)])


class SyncButton(KrogerRestockEntity, ButtonEntity):
    """Push any pending cart items now."""

    _attr_translation_key = "sync"

    def __init__(self, coordinator: KrogerRestockCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "sync")

    async def async_press(self) -> None:
        """Handle the press."""
        await self.coordinator.async_sync()


class CheckStockButton(KrogerRestockEntity, ButtonEntity):
    """Re-check waiting items now."""

    _attr_translation_key = "check_stock"

    def __init__(self, coordinator: KrogerRestockCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "check_stock")

    async def async_press(self) -> None:
        """Handle the press."""
        await self.coordinator.async_check_stock()
        await self.coordinator.async_push_held()
