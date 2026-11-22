"""Pre-order cart check."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.kroger_restock.const import DOMAIN, ItemStatus
from custom_components.kroger_restock.schedule import next_cart_check

from .helpers import FakeKrogerApi, make_product

TZ = ZoneInfo("America/Chicago")
WED_NOON = datetime(2026, 11, 18, 12, 0, tzinfo=TZ)


@pytest.mark.parametrize(
    ("order_days", "hours", "expected"),
    [
        (["sat"], 6, datetime(2026, 11, 20, 18, 0, tzinfo=TZ)),  # Fri 6 pm
        (["sat"], 30, datetime(2026, 11, 19, 18, 0, tzinfo=TZ)),  # Thu 6 pm
        (["thu", "sat"], 6, datetime(2026, 11, 18, 18, 0, tzinfo=TZ)),  # Wed 6 pm
        (["wed"], 6, datetime(2026, 11, 24, 18, 0, tzinfo=TZ)),  # next week
    ],
)
def test_next_cart_check_with_order_days(
    order_days: list[str], hours: int, expected: datetime
) -> None:
    assert next_cart_check(WED_NOON, order_days, hours, "sat", "18:00:00") == expected


def test_next_cart_check_weekly_fallback() -> None:
    assert next_cart_check(WED_NOON, [], 6, "sun", "09:30:00") == datetime(
        2026, 11, 22, 9, 30, tzinfo=TZ
    )
    # Later the same day.
    assert next_cart_check(WED_NOON, [], 6, "wed", "15:00") == datetime(
        2026, 11, 18, 15, 0, tzinfo=TZ
    )


async def setup_cart(hass: HomeAssistant, fake_api: FakeKrogerApi) -> None:
    fake_api.add(make_product("0004900002891", "Coca-Cola"))
    fake_api.add(
        make_product("0000000000033", "Eggs", stock="TEMPORARILY_OUT_OF_STOCK")
    )
    await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": "049000028911", "quantity": 2}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "scan_upc", {"upc": "0000000000033"}, blocking=True
    )


@pytest.fixture
async def phone(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> list[ServiceCall]:
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            "notify_targets": ["notify.mobile_app_pixel"],
        },
    )
    return calls


async def test_send_now_lists_cart_and_never_touches_it(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    phone: list[ServiceCall],
) -> None:
    await setup_cart(hass, fake_api)
    pushes = len(fake_api.cart_calls)
    result = await hass.services.async_call(
        DOMAIN, "cart_check", {}, blocking=True, return_response=True
    )
    assert [(i["name"], i["quantity"]) for i in result["in_cart"]] == [("Coca-Cola", 2)]
    assert result["waiting"] == 1
    [call] = phone
    assert call.data["title"] == "Kroger cart check"
    assert call.data["message"] == (
        "Home Assistant thinks your Kroger cart has 2 items: Coca-Cola ×2. "
        "1 waiting on stock."
    )
    titles = [a["title"] for a in call.data["data"]["actions"]]
    assert titles == ["Matches", "Something's missing from HA", "Open list"]
    assert call.data["data"]["actions"][1]["behavior"] == "textInput"
    assert len(fake_api.cart_calls) == pushes


async def test_matches_does_nothing(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    phone: list[ServiceCall],
) -> None:
    await setup_cart(hass, fake_api)
    await hass.services.async_call(DOMAIN, "cart_check", {}, blocking=True)
    action = phone[0].data["data"]["actions"][0]["action"]
    phone.clear()
    items_before = len(setup_integration.runtime_data.coordinator.items)
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()
    assert phone == []
    assert len(setup_integration.runtime_data.coordinator.items) == items_before


async def test_missing_reply_records_already_in_cart(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    phone: list[ServiceCall],
) -> None:
    jif = fake_api.add(make_product("0005150025516", "Jif Creamy Peanut Butter"))
    fake_api.search_results["jif creamy peanut butter"] = [jif]
    fake_api.search_results["milk"] = [
        make_product("0001111041700", "Kroger 2% Milk"),
        make_product("0001111041600", "Kroger Whole Milk"),
    ]
    await hass.services.async_call(DOMAIN, "cart_check", {}, blocking=True)
    action = phone[0].data["data"]["actions"][1]["action"]
    phone.clear()
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": action, "reply_text": "Jif creamy peanut butter, milk, unobtainium"},
    )
    await hass.async_block_till_done()
    coordinator = setup_integration.runtime_data.coordinator
    pb = next(i for i in coordinator.items if i.product_id == "0005150025516")
    assert pb.status is ItemStatus.IN_CART
    assert pb.pushed_quantity == 1
    milk = next(i for i in coordinator.items if i.name == "milk")
    assert milk.status is ItemStatus.NEEDS_REVIEW
    assert milk.already_in_cart is True  # recorded, not pushed, once resolved
    assert fake_api.cart_calls == []  # never touches the cart
    [summary] = phone
    assert (
        "Recorded as in your cart: Jif Creamy Peanut Butter." in summary.data["message"]
    )
    assert "Pick the product on the list" in summary.data["message"]
    assert "Not found in the catalog: unobtainium." in summary.data["message"]


async def test_scheduled_before_order_day(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeKrogerApi,
    phone: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    await hass.config.async_set_time_zone("America/Chicago")
    freezer.move_to("2026-11-18 12:00:00-06:00")  # Wednesday noon
    hass.config_entries.async_update_entry(
        setup_integration,
        options={
            **setup_integration.options,
            "order_days": ["sat"],
            "cart_check": True,
            "cart_check_hours_before": 6,
        },
    )
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    cart_check = setup_integration.runtime_data.cart_check
    assert cart_check.next_run == datetime(2026, 11, 20, 18, 0, tzinfo=TZ)

    freezer.move_to("2026-11-20 18:00:01-06:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [c.data["title"] for c in phone] == ["Kroger cart check"]
    # Rescheduled for the next week.
    assert cart_check.next_run == datetime(2026, 11, 27, 18, 0, tzinfo=TZ)


async def test_options_cart_check_step(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "cart_check"}
    )
    assert result["step_id"] == "cart_check"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "cart_check": True,
            "cart_check_hours_before": 4,
            "cart_check_day": "sun",
            "cart_check_time": "09:30:00",
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert setup_integration.options["cart_check"] is True
    assert setup_integration.runtime_data.cart_check.next_run is not None


async def test_no_phone_targets_uses_persistent_notification(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeKrogerApi
) -> None:
    from unittest.mock import patch

    with patch(
        "custom_components.kroger_restock.coordinator.persistent_notification.async_create"
    ) as notify:
        await hass.services.async_call(DOMAIN, "cart_check", {}, blocking=True)
    notify.assert_called_once()
    assert "doesn't think anything is in your Kroger cart" in notify.call_args.args[1]
