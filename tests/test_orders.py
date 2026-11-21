"""Order tracking from IMAP order emails (synthetic samples)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.kroger_restock.const import (
    DOMAIN,
    EVENT_ORDER_UPDATE,
    ItemStatus,
)
from custom_components.kroger_restock.store import RestockStore

from .helpers import FakeKrogerApi, make_product
from .test_order_email import CHANGES_TEXT, PLACED_TEXT, READY_HTML

SENSOR = "sensor.kroger_test_store_kroger_order"


def fake_imap_entry(hass: HomeAssistant) -> MockConfigEntry:
    """An IMAP entry that looks loaded, without loading the real integration."""
    entry = MockConfigEntry(domain="imap", title="Mail", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def imap_entries(hass: HomeAssistant) -> Generator[list[MockConfigEntry]]:
    entries: list[MockConfigEntry] = []
    yield entries
    # Don't let teardown try to unload the real IMAP integration.
    for entry in entries:
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def imap_entry(
    hass: HomeAssistant, imap_entries: list[MockConfigEntry]
) -> MockConfigEntry:
    entry = fake_imap_entry(hass)
    imap_entries.append(entry)
    return entry


@pytest.fixture
def mailbox(hass: HomeAssistant) -> dict[str, str]:
    """Fake imap.fetch: uid -> full text."""
    messages: dict[str, str] = {}

    async def fetch(call: ServiceCall) -> dict[str, Any]:
        return {"text": messages.get(call.data["uid"], ""), "uid": call.data["uid"]}

    hass.services.async_register(
        "imap", "fetch", fetch, supports_response=SupportsResponse.ONLY
    )
    return messages


@pytest.fixture
async def tracking(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> MockConfigEntry:
    hass.config_entries.async_update_entry(
        setup_integration,
        options={**setup_integration.options, "imap_entry": imap_entry.entry_id},
    )
    await hass.async_block_till_done()
    return setup_integration


_uid = 0


async def deliver(
    hass: HomeAssistant,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    subject: str,
    text: str,
    *,
    sender: str = "orders@email.kroger.com",
    uid: str | None = None,
    event_text: str | None = None,
) -> str:
    global _uid  # noqa: PLW0603
    if uid is None:
        _uid += 1
        uid = str(_uid)
    mailbox[uid] = text
    hass.bus.async_fire(
        "imap_content",
        {
            "entry_id": imap_entry.entry_id,
            "sender": sender,
            "subject": subject,
            "uid": uid,
            "date": dt_util.utcnow(),
            "initial": True,
            "text": event_text if event_text is not None else text[:50],
        },
    )
    await hass.async_block_till_done()
    return uid


async def test_order_lifecycle(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    assert hass.states.get(SENSOR).state == "none"
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)

    await deliver(hass, imap_entry, mailbox, "Thanks for your order!", PLACED_TEXT)
    state = hass.states.get(SENSOR)
    assert state.state == "placed"
    assert state.attributes["order_number"] == "112233445566"
    assert state.attributes["window"].endswith("3:00 PM - 4:00 PM")
    assert state.attributes["modality"] == "pickup"

    await deliver(
        hass, imap_entry, mailbox, "Your order is ready for pickup!", READY_HTML
    )
    state = hass.states.get(SENSOR)
    assert state.state == "ready"
    assert state.attributes["shorted_items"] == [
        "Simple Truth Organic Large Brown Eggs 12 ct",
        "Coca-Cola Classic Soda 12 pk",
    ]
    assert len(state.attributes["substitutions"]) == 1

    await deliver(
        hass, imap_entry, mailbox, "Thanks for picking up your order 112233445566", ""
    )
    assert hass.states.get(SENSOR).state == "completed"
    orders = tracking.runtime_data.coordinator.data.orders
    assert len(orders) == 1
    assert [h["status"] for h in orders[0].history] == ["placed", "ready", "completed"]
    assert [e.data["status"] for e in events] == ["placed", "ready", "completed"]
    # Full text came from imap.fetch, not the truncated event text.
    assert events[1].data["shorted"][0].startswith("Simple Truth")


async def test_sensor_shows_none_after_finished_order_ages(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    freezer: FrozenDateTimeFactory,
) -> None:
    await deliver(hass, imap_entry, mailbox, "Order 998877665 has been delivered", "")
    assert hass.states.get(SENSOR).state == "completed"
    freezer.tick(timedelta(days=3))
    tracking.runtime_data.coordinator.mark_changed()
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "none"
    assert (
        hass.states.get(SENSOR).attributes["recent_orders"][0]["status"] == "completed"
    )


async def test_duplicates_and_foreign_mail_are_ignored(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    imap_entries: list[MockConfigEntry],
    mailbox: dict[str, str],
) -> None:
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    uid = await deliver(
        hass, imap_entry, mailbox, "Thanks for your order!", PLACED_TEXT
    )
    await deliver(
        hass, imap_entry, mailbox, "Thanks for your order!", PLACED_TEXT, uid=uid
    )
    await deliver(
        hass,
        imap_entry,
        mailbox,
        "Your order is ready for pickup",
        "",
        sender="phish@notkroger.com",
    )
    other = fake_imap_entry(hass)
    imap_entries.append(other)
    await deliver(hass, other, mailbox, "Your order is ready for pickup", "")
    await deliver(hass, imap_entry, mailbox, "This week's digital coupons", "Save big")
    assert len(events) == 1
    assert hass.states.get(SENSOR).state == "placed"


async def test_unnumbered_update_applies_to_active_order(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    await deliver(hass, imap_entry, mailbox, "Thanks for your order!", PLACED_TEXT)
    await deliver(hass, imap_entry, mailbox, "Changes to your order", CHANGES_TEXT)
    state = hass.states.get(SENSOR)
    assert state.state == "placed"  # changes email doesn't move the status
    assert state.attributes["shorted_items"] == [
        "Häagen-Dazs Vanilla Ice Cream 14 oz",
        "Birthday Candles",
    ]


async def test_changes_email_without_any_order_is_ignored(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    await deliver(hass, imap_entry, mailbox, "Changes to your order", CHANGES_TEXT)
    assert hass.states.get(SENSOR).state == "none"


async def test_falls_back_to_event_text_without_fetch(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    hass.services.async_remove("imap", "fetch")
    await deliver(
        hass, imap_entry, mailbox, "Order confirmation", "", event_text=PLACED_TEXT
    )
    assert hass.states.get(SENSOR).attributes["order_number"] == "112233445566"


async def setup_cart(hass: HomeAssistant, fake_api: FakeKrogerApi) -> dict[str, str]:
    ids = {}
    for pid, name in (
        ("0001111000101", "Simple Truth Organic Large Brown Eggs"),
        ("0004900002891", "Coca-Cola Classic Soda"),
    ):
        fake_api.add(make_product(pid, name))
        result = await hass.services.async_call(
            DOMAIN, "scan_upc", {"upc": pid}, blocking=True, return_response=True
        )
        ids[name] = result["item_id"]
    return ids


async def test_shorted_items_matched_and_notified(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
) -> None:
    ids = await setup_cart(hass, fake_api)
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    with patch(
        "custom_components.kroger_restock.coordinator.persistent_notification.async_create"
    ) as notify:
        await deliver(
            hass, imap_entry, mailbox, "Your order is ready for pickup!", READY_HTML
        )
    data = events[0].data
    assert data["shorted_item_ids"] == {
        "Simple Truth Organic Large Brown Eggs 12 ct": ids[
            "Simple Truth Organic Large Brown Eggs"
        ],
        "Coca-Cola Classic Soda 12 pk": ids["Coca-Cola Classic Soda"],
    }
    assert data["readded_item_ids"] == []  # auto re-add is off by default
    # No notify targets -> persistent notification
    notify.assert_called_once()
    message = notify.call_args.args[1]
    assert notify.call_args.kwargs["title"] == "Kroger order ready for pickup"
    assert "Missing: Simple Truth Organic Large Brown Eggs 12 ct" in message
    assert "Uncheck them on the list" in message
    assert len(fake_api.cart_calls) == 2  # nothing re-pushed


async def test_shorted_items_readded_when_enabled(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
) -> None:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.config_entries.async_update_entry(
        tracking,
        options={
            **tracking.options,
            "readd_shorted": True,
            "notify_targets": ["notify.mobile_app_pixel"],
        },
    )
    await hass.async_block_till_done()
    ids = await setup_cart(hass, fake_api)
    coordinator = tracking.runtime_data.coordinator
    await coordinator.async_set_received(ids["Coca-Cola Classic Soda"])
    fake_api.set_stock("0001111000101", "TEMPORARILY_OUT_OF_STOCK")

    await deliver(
        hass, imap_entry, mailbox, "Your order is ready for pickup!", READY_HTML
    )
    eggs = coordinator.get_item(ids["Simple Truth Organic Large Brown Eggs"])
    coke = coordinator.get_item(ids["Coca-Cola Classic Soda"])
    assert eggs.status is ItemStatus.WAITING  # out of stock now: waits
    assert coke.status is ItemStatus.IN_CART  # pushed again
    assert fake_api.cart_lines[-1] == ("0004900002891", 1)
    assert len(fake_api.cart_lines) == 3
    assert len(calls) == 1
    assert calls[0].data["title"] == "Kroger order ready for pickup"
    assert "Added back to your list" in calls[0].data["message"]


async def test_tracking_off_without_imap_entry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    await deliver(hass, imap_entry, mailbox, "Thanks for your order!", PLACED_TEXT)
    assert hass.states.get(SENSOR).state == "none"


async def test_options_orders_step(
    hass: HomeAssistant, setup_integration: MockConfigEntry, imap_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "orders"}
    )
    assert result["step_id"] == "orders"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "imap_entry": imap_entry.entry_id,
            "notify_orders": False,
            "readd_shorted": True,
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert setup_integration.options["imap_entry"] == imap_entry.entry_id
    assert setup_integration.options["readd_shorted"] is True
    assert setup_integration.runtime_data.orders.imap_entry_id == imap_entry.entry_id


async def test_storage_migrates_to_1_3(hass: HomeAssistant, hass_storage) -> None:
    hass_storage["kroger_restock.mig"] = {
        "version": 1,
        "minor_version": 2,
        "key": "kroger_restock.mig",
        "data": {"items": [], "barcode_cache": {}},
    }
    data = await RestockStore(hass, "mig").async_load()
    assert data.orders == []
    assert data.seen_emails == []
