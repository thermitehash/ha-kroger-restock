"""HTTP-level tests for the Kroger API client."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.kroger_restock.api import (
    CartItem,
    KrogerApiClient,
    KrogerAuthError,
    KrogerRateLimitError,
    KrogerResponseError,
)

from .helpers import LOCATION_ID, product_payload

BASE = "https://api.kroger.com/v1"


def client(hass: HomeAssistant, *, app: bool = True) -> KrogerApiClient:
    async def user() -> str:
        return "user-token"

    async def app_token() -> str:
        return "app-token"

    return KrogerApiClient(
        async_get_clientsession(hass), user, app_token if app else None
    )


async def test_get_product_parses_fields(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        f"{BASE}/products/0001111041700",
        json={
            "data": product_payload(
                "0001111041700", "Kroger 2% Milk", stock="LOW", promo=2.99
            )
        },
    )
    product = await client(hass).async_get_product("0001111041700", LOCATION_ID)
    assert product is not None
    assert product.description == "Kroger 2% Milk"
    assert product.size == "1 gal"
    assert product.price == 2.99
    assert product.regular_price == 3.49
    assert product.stock_level == "LOW"
    assert product.in_stock
    assert product.aisle is not None and product.aisle.label == "Aisle 12"
    assert product.image_url == "https://img.example/0001111041700.jpg"
    assert product.fulfillment["curbside"] is True
    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert url.query["filter.locationId"] == LOCATION_ID
    assert headers["Authorization"] == "Bearer user-token"


async def test_out_of_stock_flag(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        f"{BASE}/products/0000000000001",
        json={
            "data": product_payload(
                "0000000000001", "X", stock="TEMPORARILY_OUT_OF_STOCK"
            )
        },
    )
    product = await client(hass).async_get_product("0000000000001", LOCATION_ID)
    assert product is not None and not product.in_stock


async def test_get_product_not_found(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        f"{BASE}/products/0000000000404",
        status=404,
        json={"errors": {"reason": "nope"}},
    )
    assert await client(hass).async_get_product("0000000000404", LOCATION_ID) is None


async def test_product_falls_back_to_app_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    calls: list[str] = []

    async def side_effect(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import (
            AiohttpClientMockResponse,
        )

        token = aioclient_mock.mock_calls[-1][3]["Authorization"]
        calls.append(token)
        if token == "Bearer user-token":
            return AiohttpClientMockResponse(method, url, status=403, json={})
        return AiohttpClientMockResponse(
            method, url, json={"data": [product_payload("0000000000001", "Apple")]}
        )

    aioclient_mock.get(f"{BASE}/products", side_effect=side_effect)
    api = client(hass)
    results = await api.async_search_products("apple", LOCATION_ID)
    assert [p.description for p in results] == ["Apple"]
    assert calls == ["Bearer user-token", "Bearer app-token"]
    assert api.products_use_app_token
    # Sticks with the app token afterwards.
    await api.async_search_products("apple", LOCATION_ID)
    assert calls[-1] == "Bearer app-token"
    assert api.call_counts["products"] == 3


async def test_search_params_and_short_term(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/products", json={"data": []})
    api = client(hass)
    assert await api.async_search_products("ab", LOCATION_ID) == []
    assert aioclient_mock.call_count == 0
    await api.async_search_products("greek yogurt", LOCATION_ID)
    url = aioclient_mock.mock_calls[0][1]
    assert url.query["filter.term"] == "greek yogurt"
    assert url.query["filter.limit"] == "10"


async def test_add_to_cart_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.put(f"{BASE}/cart/add", status=204)
    await client(hass).async_add_to_cart(
        [
            CartItem("0004900002891", 2, "PICKUP"),
            CartItem("0001111041700", 1, "DELIVERY"),
        ]
    )
    method, _, body, headers = aioclient_mock.mock_calls[0]
    assert method.lower() == "put"
    assert body == {
        "items": [
            {"upc": "0004900002891", "quantity": 2, "modality": "PICKUP"},
            {"upc": "0001111041700", "quantity": 1, "modality": "DELIVERY"},
        ]
    }
    assert headers["Authorization"] == "Bearer user-token"


async def test_add_to_cart_empty_is_noop(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await client(hass).async_add_to_cart([])
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, KrogerAuthError),
        (429, KrogerRateLimitError),
        (400, KrogerResponseError),
        (500, KrogerResponseError),
    ],
)
async def test_cart_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    exc: type[Exception],
) -> None:
    aioclient_mock.put(
        f"{BASE}/cart/add", status=status, json={"error_description": "bad"}
    )
    with pytest.raises(exc):
        await client(hass).async_add_to_cart([CartItem("0004900002891")])


async def test_locations(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(
        f"{BASE}/locations",
        json={
            "data": [
                {
                    "locationId": LOCATION_ID,
                    "chain": "KROGER",
                    "name": "Kroger - Downtown",
                    "address": {
                        "addressLine1": "1 Main St",
                        "city": "Cincinnati",
                        "state": "OH",
                        "zipCode": "45202",
                    },
                }
            ]
        },
    )
    locations = await client(hass).async_get_locations("45202")
    assert locations[0].location_id == LOCATION_ID
    assert locations[0].label == "Kroger - Downtown — 1 Main St, Cincinnati, OH 45202"
    assert locations[0].address == "1 Main St, Cincinnati, OH 45202"
    assert aioclient_mock.mock_calls[0][1].query["filter.zipCode.near"] == "45202"


async def test_profile(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(f"{BASE}/identity/profile", json={"data": {"id": "abc-123"}})
    assert await client(hass).async_get_profile_id() == "abc-123"
