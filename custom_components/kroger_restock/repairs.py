"""Repair flows: long-waiting items and interrupted cart pushes."""

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


class CheckCartRepairFlow(RepairsFlow):
    """An interrupted push: the item may or may not be in the Kroger cart."""

    def __init__(self, entry_id: str, item_id: str) -> None:
        """Initialize."""
        self._entry_id = entry_id
        self._item_id = item_id

    def _coordinator(self) -> Any:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return None
        return entry.runtime_data.coordinator

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Offer the choices."""
        return self.async_show_menu(
            step_id="init", menu_options=["confirm", "push_again", "remove"]
        )

    async def _resolve(self, action: str) -> FlowResult:
        if (coordinator := self._coordinator()) is None:
            return self.async_abort(reason="not_loaded")
        await coordinator.async_resolve_check_cart(self._item_id, action)
        return self.async_create_entry(data={})

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Record it as in the cart, with no cart call."""
        return await self._resolve("confirm")

    async def async_step_push_again(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Push it now (it isn't in the cart)."""
        return await self._resolve("push_again")

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove it from the list (remove it from the Kroger cart yourself)."""
        return await self._resolve("remove")


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Create the fix flow for a give-up or check-cart issue."""
    assert data is not None
    if issue_id.startswith("check_cart_"):
        return CheckCartRepairFlow(str(data["entry_id"]), str(data["item_id"]))
    return GiveUpRepairFlow(str(data["entry_id"]), str(data["item_id"]))
