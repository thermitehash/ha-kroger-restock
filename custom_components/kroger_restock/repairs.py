"""Repair flow for items that have waited too long."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult


class GiveUpRepairFlow(RepairsFlow):
    """Let the user decide what to do with a long-waiting item."""

    def __init__(self, entry_id: str, item_id: str) -> None:
        """Initialize."""
        self._entry_id = entry_id
        self._item_id = item_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Offer the choices."""
        return self.async_show_menu(
            step_id="init", menu_options=["keep_waiting", "remove"]
        )

    def _coordinator(self) -> Any:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data.coordinator

    async def async_step_keep_waiting(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Keep the item waiting and restart the give-up clock."""
        if (coordinator := self._coordinator()) is None:
            return self.async_abort(reason="not_loaded")
        await coordinator.async_keep_waiting(self._item_id)
        return self.async_create_entry(data={})

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove the item from the list."""
        if (coordinator := self._coordinator()) is None:
            return self.async_abort(reason="not_loaded")
        await coordinator.async_delete([self._item_id])
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Create the fix flow for a give-up issue."""
    assert data is not None
    return GiveUpRepairFlow(str(data["entry_id"]), str(data["item_id"]))
