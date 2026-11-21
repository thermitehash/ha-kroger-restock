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
from .test_order_email import (
    CHANGES_TEXT,
    CONFIRMED_TEXT,
    DELIVERY_ORDER_NUMBER,
    DELIVERY_TEXT,
    DEVELOPER_SENDER,
    DEVELOPER_TEXT,
    INSTACART_RECEIPT_TEXT,
    KROGER_SENDER,
    ORDER_NUMBER,
    READY_HTML,
    READY_TEXT,
    RECEIPT_TEXT,
    SHORTED_HTML,
    SUBJECTS,
)

PLACED_TEXT = CONFIRMED_TEXT

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
    await set_options(hass, setup_integration, imap_entry=imap_entry.entry_id)
    return setup_integration


async def set_options(
    hass: HomeAssistant, entry: MockConfigEntry, **options: Any
) -> None:
    """Change options and reload, like finishing the options flow does."""
    hass.config_entries.async_update_entry(entry, options={**entry.options, **options})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


_uid = 0


async def deliver(
    hass: HomeAssistant,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    subject: str,
    text: str,
    *,
    sender: str = KROGER_SENDER,
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

    # Real Kroger sequence: confirmed -> ready -> final receipt.
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    state = hass.states.get(SENSOR)
    assert state.state == "placed"
    assert state.attributes["order_number"] == ORDER_NUMBER
    assert state.attributes["window"] == "Mar 4, 2027 4:00pm–5:00pm"
    assert state.attributes["modality"] == "pickup"
    assert state.attributes["item_count"] == 12
    assert state.attributes["total"] == 48.75
    assert state.attributes["fee"] == 0.0
    # Store-local window, interpreted in HA's time zone.
    assert state.attributes["window_start"].startswith("2027-03-04T16:00:00")
    assert state.attributes["window_end"].startswith("2027-03-04T17:00:00")
    # No item data in Kroger's emails: unknown, so the attributes are absent.
    assert "shorted_items" not in state.attributes
    assert "substitutions" not in state.attributes

    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], READY_HTML)
    state = hass.states.get(SENSOR)
    assert state.state == "ready"
    assert state.attributes["window"] == "Today 4:00pm–5:00pm"
    assert state.attributes["item_count"] == 12  # kept from the confirmation

    # The receipt has no order number; it completes the active order.
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
    assert hass.states.get(SENSOR).state == "completed"
    orders = tracking.runtime_data.coordinator.data.orders
    assert len(orders) == 1
    assert [h["status"] for h in orders[0].history] == ["placed", "ready", "completed"]
    assert [e.data["status"] for e in events] == ["placed", "ready", "completed"]
    assert events[0].data["previous_status"] == "none"


async def test_receipt_without_known_order_is_ignored(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
    assert hass.states.get(SENSOR).state == "none"
    assert tracking.runtime_data.coordinator.data.orders == []


async def test_full_text_comes_from_imap_fetch(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    # The event only carries the first 50 characters; shorted items are further down.
    await deliver(
        hass, imap_entry, mailbox, "Your order is ready for pickup!", SHORTED_HTML
    )
    assert events[0].data["shorted"][0].startswith("Simple Truth")
    state = hass.states.get(SENSOR)
    assert len(state.attributes["shorted_items"]) == 2
    assert len(state.attributes["substitutions"]) == 1


async def test_sensor_shows_none_after_finished_order_ages(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    freezer: FrozenDateTimeFactory,
) -> None:
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], READY_HTML)
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
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
    await deliver(
        hass,
        imap_entry,
        mailbox,
        "Changes to your order",
        CHANGES_TEXT.replace(" 112233445566", ""),
    )
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
    assert hass.states.get(SENSOR).attributes["order_number"] == ORDER_NUMBER


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
            hass, imap_entry, mailbox, "Your order is ready for pickup!", SHORTED_HTML
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


async def test_shorted_items_never_readded_automatically(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
) -> None:
    """Auto re-add is disabled entirely, even if an old option is still set."""
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await set_options(
        hass,
        tracking,
        readd_shorted=True,  # left over from v0.6.0
        notify_targets=["notify.mobile_app_pixel"],
    )
    ids = await setup_cart(hass, fake_api)
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    await deliver(
        hass, imap_entry, mailbox, "Your order is ready for pickup!", SHORTED_HTML
    )
    coordinator = tracking.runtime_data.coordinator
    assert all(
        coordinator.get_item(i).status is ItemStatus.IN_CART for i in ids.values()
    )
    assert len(fake_api.cart_lines) == 2  # nothing pushed again
    assert events[0].data["readded_item_ids"] == []
    assert len(events[0].data["shorted_item_ids"]) == 2
    assert len(calls) == 1
    assert "Uncheck them on the list" in calls[0].data["message"]


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
            "extra_sender_domains": " ralphsmail.com ",
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert setup_integration.options["imap_entry"] == imap_entry.entry_id
    assert "readd_shorted" not in setup_integration.options
    assert setup_integration.options["extra_sender_domains"] == "ralphsmail.com"
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


async def test_delivery_placed_then_completed_by_instacart_receipt(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    await deliver(
        hass, imap_entry, mailbox, SUBJECTS["delivery_confirmed"], DELIVERY_TEXT
    )
    state = hass.states.get(SENSOR)
    assert state.state == "placed"
    assert state.attributes["order_number"] == DELIVERY_ORDER_NUMBER
    assert state.attributes["modality"] == "delivery"
    assert state.attributes["fee"] == 3.99
    # The delivery address is never stored.
    assert "1 Example Way" not in str(state.attributes)
    assert "1 Example Way" not in str(tracking.runtime_data.coordinator.data.orders)

    await deliver(
        hass,
        imap_entry,
        mailbox,
        SUBJECTS["instacart_receipt"],
        INSTACART_RECEIPT_TEXT,
    )
    assert hass.states.get(SENSOR).state == "completed"
    assert hass.states.get(SENSOR).attributes["modality"] == "delivery"


async def test_developer_verification_email_ignored(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    await deliver(
        hass,
        imap_entry,
        mailbox,
        SUBJECTS["developer"],
        DEVELOPER_TEXT,
        sender=DEVELOPER_SENDER,
    )
    assert events == []
    assert tracking.runtime_data.coordinator.data.seen_emails == []  # never read


async def test_receipt_completes_most_recent_ready_order_only(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Fixture 10: two open orders from two household members."""
    sam_text = CONFIRMED_TEXT.replace(ORDER_NUMBER, "5555666677778888999").replace(
        "Alex", "Sam"
    )
    sam_ready = READY_TEXT.replace(ORDER_NUMBER, "5555666677778888999")
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    freezer.tick(timedelta(minutes=5))
    await deliver(hass, imap_entry, mailbox, "Pickup Order Confirmed, Sam", sam_text)
    freezer.tick(timedelta(minutes=5))
    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], sam_ready)

    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
    orders = {
        o.order_number: o.status for o in tracking.runtime_data.coordinator.data.orders
    }
    # Only Sam's order was ready, so only it completes; Alex's stays placed.
    assert orders == {"5555666677778888999": "completed", ORDER_NUMBER: "placed"}


async def test_receipt_ignores_ready_orders_older_than_a_day(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    freezer: FrozenDateTimeFactory,
) -> None:
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], READY_TEXT)
    freezer.tick(timedelta(hours=25))
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
    assert hass.states.get(SENSOR).state == "ready"


async def test_same_email_in_another_folder_is_not_processed_twice(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
) -> None:
    """UIDs change when mail moves folder; content/Message-ID keys catch it."""
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    when = dt_util.utcnow()
    for uid in ("10", "77"):
        mailbox[uid] = CONFIRMED_TEXT
        hass.bus.async_fire(
            "imap_content",
            {
                "entry_id": imap_entry.entry_id,
                "sender": KROGER_SENDER,
                "subject": SUBJECTS["confirmed"],
                "uid": uid,
                "date": when,
                "headers": {"Message-ID": ["<abc@e.krogermail.com>"]},
            },
        )
        await hass.async_block_till_done()
    assert len(events) == 1


async def test_completed_order_asks_to_mark_received(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await set_options(hass, tracking, notify_targets=["notify.mobile_app_pixel"])
    ids = await setup_cart(hass, fake_api)
    coordinator = tracking.runtime_data.coordinator
    freezer.tick(timedelta(minutes=1))
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    freezer.tick(timedelta(minutes=1))
    late = await hass.services.async_call(  # added after the order was placed
        DOMAIN,
        "add_item",
        {"name": "unobtainium"},
        blocking=True,
        return_response=True,
    )
    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], READY_TEXT)
    calls.clear()
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)

    # Never checked off automatically...
    assert all(
        coordinator.get_item(i).status is ItemStatus.IN_CART for i in ids.values()
    )
    # ...the user is asked instead, with a button.
    assert len(calls) == 1
    assert calls[0].data["title"] == "Kroger order picked up"
    assert calls[0].data["message"].startswith("Mark the 2 in-cart items received?")
    actions = calls[0].data["data"]["actions"]
    assert [a["title"] for a in actions] == [
        "All received",
        "Some missing…",
        "Open list",
    ]
    assert actions[1]["behavior"] == "textInput"
    assert actions[2]["uri"] == "/todo?entity_id=todo.kroger_test_store"
    action = actions[0]

    hass.bus.async_fire("mobile_app_notification_action", {"action": action["action"]})
    await hass.async_block_till_done()
    assert all(
        coordinator.get_item(i).status is ItemStatus.RECEIVED for i in ids.values()
    )
    assert coordinator.get_item(late["item_id"]).status is ItemStatus.UNMATCHED


async def test_mark_cart_received_action(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    ids = await setup_cart(hass, fake_api)
    result = await hass.services.async_call(
        DOMAIN, "mark_cart_received", {}, blocking=True, return_response=True
    )
    assert result == {"received": 2, "missing": [], "unmatched": []}
    coordinator = setup_integration.runtime_data.coordinator
    assert all(
        coordinator.get_item(i).status is ItemStatus.RECEIVED for i in ids.values()
    )


async def _complete_order_with_cart(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> tuple[dict[str, str], list[ServiceCall], dict[str, str]]:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await set_options(hass, tracking, notify_targets=["notify.mobile_app_pixel"])
    ids = await setup_cart(hass, fake_api)
    freezer.tick(timedelta(minutes=1))
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], READY_TEXT)
    calls.clear()
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
    actions = {
        a["title"]: a.get("action", "") for a in calls[0].data["data"]["actions"]
    }
    calls.clear()
    return ids, calls, actions


async def test_some_missing_reply_readds_those_items(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Out-of-stock/replacement notices come by text; the user types what's missing."""
    ids, calls, actions = await _complete_order_with_cart(
        hass, tracking, imap_entry, mailbox, fake_api, freezer
    )
    coordinator = tracking.runtime_data.coordinator
    fake_api.set_stock("0004900002891", "TEMPORARILY_OUT_OF_STOCK")
    pushes = len(fake_api.cart_lines)

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {
            "action": actions["Some missing…"],
            "reply_text": "brown eggs and coca cola, kale",
        },
    )
    await hass.async_block_till_done()

    eggs = coordinator.get_item(ids["Simple Truth Organic Large Brown Eggs"])
    coke = coordinator.get_item(ids["Coca-Cola Classic Soda"])
    assert eggs.status is ItemStatus.IN_CART  # in stock: pushed again for next order
    assert coke.status is ItemStatus.WAITING  # now out of stock: waits
    assert fake_api.cart_lines[pushes:] == [("0001111000101", 1)]
    assert len(calls) == 1
    message = calls[0].data["message"]
    assert message.startswith("0 marked received.")
    assert "Simple Truth Organic Large Brown Eggs (back in the cart)" in message
    assert "Coca-Cola Classic Soda (waiting on stock)" in message
    assert 'Couldn\'t match: "kale"' in message


async def test_some_missing_with_empty_reply_changes_nothing(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls, actions = await _complete_order_with_cart(
        hass, tracking, imap_entry, mailbox, fake_api, freezer
    )
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": actions["Some missing…"], "reply_text": "  "},
    )
    await hass.async_block_till_done()
    coordinator = tracking.runtime_data.coordinator
    assert all(
        coordinator.get_item(i).status is ItemStatus.IN_CART for i in ids.values()
    )
    assert calls[0].data["title"] == "Nothing marked"


async def test_mark_cart_received_with_missing(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    ids = await setup_cart(hass, fake_api)
    coke_id = ids["Coca-Cola Classic Soda"]
    result = await hass.services.async_call(
        DOMAIN,
        "mark_cart_received",
        {"missing": [coke_id, "dragon fruit"]},
        blocking=True,
        return_response=True,
    )
    assert result["received"] == 1
    assert result["missing"] == [
        {"item_id": coke_id, "name": "Coca-Cola Classic Soda", "status": "in_cart"}
    ]
    assert result["unmatched"] == ["dragon fruit"]
    coordinator = setup_integration.runtime_data.coordinator
    eggs = coordinator.get_item(ids["Simple Truth Organic Large Brown Eggs"])
    assert eggs.status is ItemStatus.RECEIVED
    assert coordinator.get_item(coke_id).status is ItemStatus.IN_CART


async def test_mark_cart_received_missing_as_text(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    await setup_cart(hass, fake_api)
    result = await hass.services.async_call(
        DOMAIN,
        "mark_cart_received",
        {"missing": "eggs"},
        blocking=True,
        return_response=True,
    )
    assert [m["name"] for m in result["missing"]] == [
        "Simple Truth Organic Large Brown Eggs"
    ]
