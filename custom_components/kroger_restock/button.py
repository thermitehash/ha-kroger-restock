"""Buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KrogerConfigEntry
from .const import PRINT_PDF, PRINT_RECEIPT
from .coordinator import KrogerRestockCoordinator
from .entity import KrogerRestockEntity
from .printer import async_print

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KrogerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            SyncButton(coordinator),
            CheckStockButton(coordinator),
            PrintButton(coordinator, PRINT_RECEIPT),
            PrintButton(coordinator, PRINT_PDF),
        ]
    )


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


class PrintButton(KrogerRestockEntity, ButtonEntity):
    """Print the list to the receipt printer or as a PDF."""

    def __init__(self, coordinator: KrogerRestockCoordinator, target: str) -> None:
        """Initialize."""
        super().__init__(coordinator, f"print_{target}")
        self._target = target
        self._attr_translation_key = f"print_{target}"

    async def async_press(self) -> None:
        """Handle the press."""
        await async_print(self.coordinator, self._target)
