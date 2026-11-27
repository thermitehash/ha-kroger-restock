"""Order tracking from IMAP order emails (synthetic samples)."""

from __future__ import annotations

from collections import namedtuple
from collections.abc import Generator
from datetime import datetime, timedelta
from email.utils import format_datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.kroger_restock.const import (
    DOMAIN,
    EVENT_ORDER_UPDATE,
    ItemStatus,
)
from custom_components.kroger_restock.orders import OrderWatcher
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
    entry = MockConfigEntry(
        domain="imap",
        title="Mail",
        state=ConfigEntryState.LOADED,
        data={"folder": "Kroger", "search": 'FROM "e.krogermail.com"'},
    )
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
    await hass.async_block_till_done(wait_background_tasks=True)


Response = namedtuple("Response", "result lines")


def header_block(message_id: str, subject: str, when: datetime) -> bytes:
    """Raw header bytes, as IMAP returns them for HEADER.FIELDS."""
    return (
        f"Message-ID: {message_id}\r\n"
        f"From: Kroger <{KROGER_SENDER}>\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {format_datetime(when)}\r\n\r\n"
    ).encode()


class FakeImapClient:
    """Answers SEARCH and header FETCH like aioimaplib does."""

    def __init__(self, messages: list[bytes]) -> None:
        self.messages = messages

    async def search(self, search: str, charset: str = "utf-8") -> Response:
        if not self.messages:
            return Response("OK", [b"SEARCH completed"])
        numbers = " ".join(str(n) for n in range(1, len(self.messages) + 1))
        return Response("OK", [numbers.encode(), b"SEARCH completed"])

    async def fetch(self, sequence: str, spec: str) -> Response:
        lines: list[Any] = []
        for number in sequence.split(","):
            header = self.messages[int(number) - 1]
            lines += [
                f"{number} FETCH (BODY[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)]"
                f" {{{len(header)}}}".encode(),
                bytearray(header),
                b")",
            ]
        lines.append(b"Fetch completed")
        return Response("OK", lines)

    async def logout(self) -> None:
        return None


@pytest.fixture(autouse=True)
def imap_server() -> Generator[dict[str, Any]]:
    """Fake mailbox per IMAP folder; records connections."""
    server: dict[str, Any] = {"folders": {}, "connects": 0, "fail": None}

    async def connect(entry_data: Any) -> FakeImapClient:
        server["connects"] += 1
        if server["fail"] is not None:
            raise server["fail"]
        return FakeImapClient(server["folders"].get(entry_data.get("folder"), []))

    with patch(
        "custom_components.kroger_restock.imap_baseline.async_connect",
        side_effect=connect,
    ):
        yield server


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
    date: datetime | None = None,
    message_id: str | None = None,
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
            "date": date or dt_util.utcnow(),
            "initial": True,
            **({"headers": {"Message-ID": [message_id]}} if message_id else {}),
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
    when = dt_util.utcnow()
    uid = await deliver(
        hass, imap_entry, mailbox, "Thanks for your order!", PLACED_TEXT, date=when
    )
    await deliver(
        hass,
        imap_entry,
        mailbox,
        "Thanks for your order!",
        PLACED_TEXT,
        uid=uid,
        date=when,
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


@pytest.fixture
def no_order_stock_check() -> Generator[None]:
    """As if the order-time stock check never ran (confirmation missed)."""
    with patch.object(OrderWatcher, "async_check_order_stock", AsyncMock()):
        yield


@pytest.mark.usefixtures("no_order_stock_check")
async def test_completed_order_asks_to_mark_received(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without the order-time stock check, the user is asked about everything."""
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


@pytest.mark.usefixtures("no_order_stock_check")
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


@pytest.mark.usefixtures("no_order_stock_check")
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


async def test_imap_picker_labels_and_warnings(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entries: list[MockConfigEntry],
) -> None:
    """Two connections to one account are told apart; risky ones warn."""
    good = MockConfigEntry(
        domain="imap",
        title="Gmail - Kroger orders",
        data={"folder": "Kroger", "search": 'FROM "e.krogermail.com"'},
    )
    risky = MockConfigEntry(
        domain="imap",
        title="Gmail - Bills",
        data={"folder": "INBOX", "search": "UnSeen UnDeleted"},
    )
    for entry in (good, risky):
        entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "orders"}
    )
    selector = result["data_schema"].schema["imap_entry"]
    labels = {o["value"]: o["label"] for o in selector.config["options"]}
    assert labels[good.entry_id] == (
        'Gmail - Kroger orders — folder: Kroger · search: FROM "e.krogermail.com"'
    )
    assert labels[risky.entry_id] == (
        "Gmail - Bills — folder: INBOX · search: UnSeen UnDeleted"
    )

    # Picking the risky one shows a warning step before saving.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"imap_entry": risky.entry_id, "notify_orders": True}
    )
    assert result["step_id"] == "orders_confirm"
    warnings = result["description_placeholders"]["warnings"]
    assert "UnSeen" in warnings and "INBOX" in warnings
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert setup_integration.options["imap_entry"] == risky.entry_id


async def test_imap_picker_good_entry_saves_directly(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "orders"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"imap_entry": imap_entry.entry_id, "notify_orders": True}
    )
    assert result["type"] == "create_entry"


# --- Folder baseline (linking to a folder that holds order history) ----------

HISTORY_SUBJECTS = [
    "Pickup Order Confirmed, Alex",
    "Your Order is Ready for Pickup at 100 Main St Anytown OH 45000",
    "Alex, Here’s Your Final Receipt. Tell Us How We Did with Your Order.",
]


def history(count: int, prefix: str = "old") -> list[tuple[str, str, datetime]]:
    start = datetime(2026, 1, 5, 12, 0, tzinfo=dt_util.UTC)
    return [
        (
            f"<{prefix}-{n}@e.krogermail.com>",
            HISTORY_SUBJECTS[n % 3],
            start + timedelta(days=n // 3 * 3, hours=n % 3),
        )
        for n in range(count)
    ]


async def link(
    hass: HomeAssistant, entry: MockConfigEntry, imap_entry: MockConfigEntry
) -> None:
    await set_options(hass, entry, imap_entry=imap_entry.entry_id)


async def test_link_baselines_existing_history(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    imap_server: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    old = history(100)
    imap_server["folders"]["Kroger"] = [header_block(*m) for m in old]
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    with caplog.at_level("INFO"):
        await link(hass, setup_integration, imap_entry)
    data = setup_integration.runtime_data.coordinator.data
    assert data.imap_baseline["count"] == 100
    assert data.imap_baseline["folder"] == "Kroger"
    assert data.orders == []
    assert "Baselined 100 existing messages in folder Kroger" in caplog.text

    # HA's IMAP integration fires for the newest existing message on start:
    # it's in the baseline, so nothing happens.
    message_id, subject, when = old[-1]
    await deliver(
        hass,
        imap_entry,
        mailbox,
        subject,
        CONFIRMED_TEXT,
        date=when,
        message_id=message_id,
    )
    # An old email without headers is matched by sender/subject/date instead.
    message_id, subject, when = old[-3]
    await deliver(hass, imap_entry, mailbox, subject, CONFIRMED_TEXT, date=when)
    assert events == []
    assert data.orders == []

    # A new confirmation after the baseline is processed.
    await deliver(
        hass,
        imap_entry,
        mailbox,
        SUBJECTS["confirmed"],
        CONFIRMED_TEXT,
        message_id="<new-1@e.krogermail.com>",
    )
    assert hass.states.get(SENSOR).state == "placed"
    assert len(events) == 1


async def test_relink_to_another_entry_rebaselines(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    imap_entries: list[MockConfigEntry],
    mailbox: dict[str, str],
    imap_server: dict[str, Any],
) -> None:
    imap_server["folders"]["Kroger"] = [header_block(*m) for m in history(10)]
    await link(hass, setup_integration, imap_entry)
    other = MockConfigEntry(
        domain="imap",
        title="Mail 2",
        state=ConfigEntryState.LOADED,
        data={"folder": "Kroger2", "search": 'FROM "e.krogermail.com"'},
    )
    other.add_to_hass(hass)
    imap_entries.append(other)
    second = history(3, prefix="other")
    imap_server["folders"]["Kroger2"] = [header_block(*m) for m in second]

    await link(hass, setup_integration, other)
    data = setup_integration.runtime_data.coordinator.data
    assert data.imap_baseline["entry_id"] == other.entry_id
    assert data.imap_baseline["count"] == 3
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    message_id, subject, when = second[0]
    await deliver(
        hass, other, mailbox, subject, CONFIRMED_TEXT, date=when, message_id=message_id
    )
    assert events == []
    assert data.orders == []


async def test_changed_folder_rebaselines(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    imap_server: dict[str, Any],
) -> None:
    imap_server["folders"]["Kroger"] = [header_block(*m) for m in history(4)]
    await link(hass, setup_integration, imap_entry)
    imap_server["folders"]["[Gmail]/All Mail"] = [header_block(*m) for m in history(7)]
    hass.config_entries.async_update_entry(
        imap_entry, data={**imap_entry.data, "folder": "[Gmail]/All Mail"}
    )
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    baseline = setup_integration.runtime_data.coordinator.data.imap_baseline
    assert (baseline["folder"], baseline["count"]) == ("[Gmail]/All Mail", 7)


async def test_restart_does_not_reprocess_or_rebaseline(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    imap_server: dict[str, Any],
) -> None:
    imap_server["folders"]["Kroger"] = [header_block(*m) for m in history(5)]
    await link(hass, setup_integration, imap_entry)
    when = dt_util.utcnow()
    await deliver(
        hass,
        imap_entry,
        mailbox,
        SUBJECTS["confirmed"],
        CONFIRMED_TEXT,
        date=when,
        message_id="<new-2@e.krogermail.com>",
    )
    connects = imap_server["connects"]

    # Restart (reload): the seen set and the baseline persist.
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert imap_server["connects"] == connects  # no new baseline
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    # HA's IMAP integration re-fires the newest message after a restart.
    await deliver(
        hass,
        imap_entry,
        mailbox,
        SUBJECTS["confirmed"],
        CONFIRMED_TEXT,
        date=when,
        message_id="<new-2@e.krogermail.com>",
    )
    assert events == []
    assert len(setup_integration.runtime_data.coordinator.data.orders) == 1


async def test_baseline_failure_pauses_processing_and_retries(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    imap_server: dict[str, Any],
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    imap_server["fail"] = OSError("network unreachable")
    await link(hass, setup_integration, imap_entry)
    issue_id = f"imap_baseline_{setup_integration.entry_id}"
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert "network unreachable" in issue.translation_placeholders["error"]
    events = async_capture_events(hass, EVENT_ORDER_UPDATE)
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    assert events == []  # nothing is processed without a baseline

    imap_server["fail"] = None
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
    await deliver(
        hass,
        imap_entry,
        mailbox,
        SUBJECTS["confirmed"],
        CONFIRMED_TEXT,
        message_id="<after-fix@e.krogermail.com>",
    )
    assert len(events) == 1


async def test_unlink_clears_baseline(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    imap_entry: MockConfigEntry,
    imap_server: dict[str, Any],
) -> None:
    await link(hass, setup_integration, imap_entry)
    assert setup_integration.runtime_data.coordinator.data.imap_baseline is not None
    await set_options(hass, setup_integration, imap_entry="")
    assert setup_integration.runtime_data.coordinator.data.imap_baseline is None


# ---------------------------------------------------------------------------
# Order-time stock check: checked when the order is placed; at pickup/delivery
# the in-stock items are marked received and only out-of-stock ones are asked.

EGGS = "Simple Truth Organic Large Brown Eggs"
COKE = "Coca-Cola Classic Soda"


async def place_order(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
    out_of_stock: tuple[str, ...] = (),
    notify: bool = True,
) -> tuple[dict[str, str], list[ServiceCall]]:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await set_options(
        hass,
        tracking,
        notify_targets=["notify.mobile_app_pixel"],
        notify_orders=notify,
    )
    ids = await setup_cart(hass, fake_api)
    pids = {EGGS: "0001111000101", COKE: "0004900002891"}
    for name in out_of_stock:  # sold out between the push and the order
        fake_api.set_stock(pids[name], "TEMPORARILY_OUT_OF_STOCK")
    freezer.tick(timedelta(minutes=1))
    calls.clear()
    await deliver(hass, imap_entry, mailbox, SUBJECTS["confirmed"], CONFIRMED_TEXT)
    await hass.async_block_till_done()
    return ids, calls


async def pick_up(
    hass: HomeAssistant, imap_entry: MockConfigEntry, mailbox: dict[str, str]
) -> None:
    await deliver(hass, imap_entry, mailbox, SUBJECTS["ready"], READY_TEXT)
    await deliver(hass, imap_entry, mailbox, SUBJECTS["receipt"], RECEIPT_TEXT)
    await hass.async_block_till_done()


def last_order(entry: MockConfigEntry):  # type: ignore[no-untyped-def]
    return entry.runtime_data.coordinator.data.orders[0]


async def test_placed_order_is_stock_checked_quietly(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    order = last_order(tracking)
    assert order.stock_checked_at is not None
    assert order.out_of_stock == [
        {"item_id": ids[COKE], "name": COKE, "when": "placed"}
    ]
    coordinator = tracking.runtime_data.coordinator
    coke = coordinator.get_item(ids[COKE])
    assert coke.status is ItemStatus.IN_CART  # the cart can't be changed
    assert coke.stock_level == "TEMPORARILY_OUT_OF_STOCK"
    from custom_components.kroger_restock.todo import status_line

    assert status_line(coke) == "In cart · out of stock now"
    assert status_line(coordinator.get_item(ids[EGGS])).startswith("In cart · Aisle")
    assert calls == []  # nothing asked when the order is placed
    pushes = len(fake_api.cart_lines)
    assert pushes == 2  # and nothing pushed
    # Survives a restart.
    await hass.config_entries.async_reload(tracking.entry_id)
    await hass.async_block_till_done()
    assert last_order(tracking).out_of_stock == [
        {"item_id": ids[COKE], "name": COKE, "when": "placed"}
    ]


async def test_nothing_out_of_stock_marks_all_received_without_asking(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer
    )
    freezer.tick(timedelta(minutes=1))
    late = await hass.services.async_call(  # added after the order was placed
        DOMAIN, "add_item", {"name": "unobtainium"}, blocking=True, return_response=True
    )
    calls.clear()
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert all(
        coordinator.get_item(i).status is ItemStatus.RECEIVED for i in ids.values()
    )
    assert coordinator.get_item(late["item_id"]).status is ItemStatus.UNMATCHED
    [note] = [c for c in calls if "picked up" in c.data["title"]]
    assert note.data["title"] == "Kroger order picked up"
    assert note.data["message"] == (
        "2 items marked received. Nothing was out of stock when you ordered or at pickup."
    )
    assert "data" not in note.data  # no question, no buttons


async def test_one_out_of_stock_item_is_the_only_question(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.RECEIVED
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.IN_CART
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    assert ask.data["title"] == "Kroger order picked up: did these come?"
    assert ask.data["message"] == (
        f"1 item marked received. {COKE} was out of stock when you ordered or at pickup. "
        "Did it come? Anything that didn't come goes back on the list."
    )
    actions = {a["title"]: a["action"] for a in ask.data["data"]["actions"]}
    assert list(actions) == ["Yes, it came", "No"]

    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": actions["Yes, it came"]}
    )
    await hass.async_block_till_done()
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.RECEIVED


async def test_no_puts_the_out_of_stock_item_back_on_the_list(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    await pick_up(hass, imap_entry, mailbox)
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    actions = {a["title"]: a["action"] for a in ask.data["data"]["actions"]}
    calls.clear()
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions["No"]})
    await hass.async_block_till_done()
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.WAITING  # still out
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.RECEIVED
    assert "Coca-Cola Classic Soda (waiting on stock)" in calls[0].data["message"]


async def test_several_out_of_stock_items_some_missing(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass,
        tracking,
        imap_entry,
        mailbox,
        fake_api,
        freezer,
        out_of_stock=(EGGS, COKE),
    )
    await pick_up(hass, imap_entry, mailbox)
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    assert ask.data["message"].startswith(
        f"0 items marked received. These were out of stock when you ordered or at pickup: "
        f"{EGGS}, {COKE}. Did they come?"
    )
    actions = {a["title"]: a for a in ask.data["data"]["actions"]}
    assert list(actions) == ["All came", "None came", "Some missing…"]
    assert actions["Some missing…"]["behavior"] == "textInput"
    fake_api.set_stock("0001111000101", "HIGH")  # eggs are back now
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": actions["Some missing…"]["action"], "reply_text": "eggs"},
    )
    await hass.async_block_till_done()
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.IN_CART  # pushed again
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.RECEIVED


async def test_none_came_puts_every_out_of_stock_item_back(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass,
        tracking,
        imap_entry,
        mailbox,
        fake_api,
        freezer,
        out_of_stock=(EGGS, COKE),
    )
    await pick_up(hass, imap_entry, mailbox)
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    actions = {a["title"]: a["action"] for a in ask.data["data"]["actions"]}
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": actions["None came"]}
    )
    await hass.async_block_till_done()
    coordinator = tracking.runtime_data.coordinator
    assert all(
        coordinator.get_item(i).status is ItemStatus.WAITING for i in ids.values()
    )


async def test_with_order_notifications_off_in_stock_items_still_received(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass,
        tracking,
        imap_entry,
        mailbox,
        fake_api,
        freezer,
        out_of_stock=(COKE,),
        notify=False,
    )
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.RECEIVED
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.IN_CART  # left as is
    assert calls == []


async def test_out_of_stock_at_pickup_only_is_asked(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer
    )
    assert last_order(tracking).out_of_stock == []
    fake_api.set_stock("0001111000101", "TEMPORARILY_OUT_OF_STOCK")  # sold out later
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.IN_CART
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.RECEIVED
    order = last_order(tracking)
    assert order.out_of_stock == [
        {"item_id": ids[EGGS], "name": EGGS, "when": "completed"}
    ]
    assert order.asked == [{"item_id": ids[EGGS], "name": EGGS}]
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    assert (
        f"{EGGS} was out of stock when you ordered or at pickup." in ask.data["message"]
    )


async def test_out_of_stock_when_placed_but_back_at_pickup_is_still_asked(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    fake_api.set_stock("0004900002891", "HIGH")  # back by pickup time
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.IN_CART  # asked
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.RECEIVED
    assert [c for c in calls if "did these come" in c.data["title"]]


async def test_out_of_stock_both_times_is_recorded_once(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, _calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    await pick_up(hass, imap_entry, mailbox)
    assert last_order(tracking).out_of_stock == [
        {"item_id": ids[COKE], "name": COKE, "when": "placed+completed"}
    ]


@pytest.mark.usefixtures("no_order_stock_check_at_placement")
async def test_pickup_check_alone_is_enough(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Confirmation email missed: the pickup check still drives the question."""
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    assert last_order(tracking).stock_checked_at is None
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.RECEIVED
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.IN_CART
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    assert COKE in ask.data["message"]


@pytest.fixture
def no_order_stock_check_at_placement() -> Generator[None]:
    original = OrderWatcher.async_check_order_stock

    async def only_at_completion(self, order, when="placed"):  # type: ignore[no-untyped-def]
        if when == "completed":
            await original(self, order, when)

    with patch.object(OrderWatcher, "async_check_order_stock", only_at_completion):
        yield


async def test_item_that_couldnt_be_checked_is_asked(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer
    )
    coordinator = tracking.runtime_data.coordinator
    # Pretend the placement check never read the eggs, and they've left the
    # catalog by pickup (lookup returns nothing).
    last_order(tracking).stock_checked_items = [ids[COKE]]
    fake_api.products.pop("0001111000101")
    coordinator._product_cache.clear()
    await pick_up(hass, imap_entry, mailbox)
    assert coordinator.get_item(ids[EGGS]).status is ItemStatus.IN_CART
    assert coordinator.get_item(ids[COKE]).status is ItemStatus.RECEIVED
    [ask] = [c for c in calls if "did these come" in c.data["title"]]
    assert "was out of stock (or couldn't be checked)" in ask.data["message"]


async def test_no_check_could_read_anything_asks_about_everything(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    from custom_components.kroger_restock.api import KrogerConnectionError

    ids, calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer
    )
    last_order(tracking).stock_checked_items = []

    async def unreachable(*_args: Any) -> None:
        raise KrogerConnectionError("down")

    fake_api.async_get_product = unreachable  # type: ignore[method-assign]
    tracking.runtime_data.coordinator._product_cache.clear()
    await pick_up(hass, imap_entry, mailbox)
    coordinator = tracking.runtime_data.coordinator
    assert all(
        coordinator.get_item(i).status is ItemStatus.IN_CART for i in ids.values()
    )
    [ask] = [c for c in calls if "picked up" in c.data["title"]]
    assert ask.data["message"].startswith("Mark the 2 in-cart items received?")


async def test_received_event_carries_the_order_number(
    hass: HomeAssistant,
    tracking: MockConfigEntry,
    imap_entry: MockConfigEntry,
    mailbox: dict[str, str],
    fake_api: FakeKrogerApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    from pytest_homeassistant_custom_component.common import async_capture_events

    ids, _calls = await place_order(
        hass, tracking, imap_entry, mailbox, fake_api, freezer, out_of_stock=(COKE,)
    )
    events = async_capture_events(hass, f"{DOMAIN}_received")
    await pick_up(hass, imap_entry, mailbox)
    order = last_order(tracking)
    # In stock: received at pickup, with the order number.
    assert [(e.data["item_id"], e.data["order_ref"]) for e in events] == [
        (ids[EGGS], order.order_number)
    ]
    # The out-of-stock one is reported once the user says it came.
    [ask] = [c for c in _calls if "did these come" in c.data["title"]]
    yes = ask.data["data"]["actions"][0]["action"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": yes})
    await hass.async_block_till_done()
    assert [e.data["item_id"] for e in events] == [ids[EGGS], ids[COKE]]
    assert events[1].data["order_ref"] == order.order_number
