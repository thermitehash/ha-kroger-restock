"""Optional live check: does Kroger's cart accept an out-of-stock UPC?

Skipped unless you provide real credentials, so CI never touches the API.
The integration never pushes out-of-stock items regardless of the answer
(see test_scan_out_of_stock_waits_and_is_not_pushed).

Run manually with a *disposable* cart (it adds one unit to your real cart):

    KROGER_LIVE_USER_TOKEN=... KROGER_LIVE_LOCATION_ID=... \
    KROGER_LIVE_OOS_UPC=0001111000000 pytest tests/test_live_cart.py -s
"""

from __future__ import annotations

import os

import aiohttp
import pytest

from custom_components.kroger_restock.api import CartItem, KrogerApiClient, KrogerError

TOKEN = os.environ.get("KROGER_LIVE_USER_TOKEN")
LOCATION = os.environ.get("KROGER_LIVE_LOCATION_ID")
OOS_UPC = os.environ.get("KROGER_LIVE_OOS_UPC")

pytestmark = pytest.mark.skipif(
    not (TOKEN and LOCATION and OOS_UPC), reason="live Kroger credentials not set"
)


@pytest.mark.allow_hosts(["api.kroger.com"])
async def test_cart_accepts_out_of_stock_upc() -> None:
    async def token() -> str:
        return str(TOKEN)

    async with aiohttp.ClientSession() as session:
        api = KrogerApiClient(session, token)
        product = await api.async_get_product(str(OOS_UPC), str(LOCATION))
        assert product is not None, "UPC not found at this store"
        print(f"stockLevel={product.stock_level!r}")
        assert not product.in_stock, "pick a UPC that is currently out of stock"
        try:
            await api.async_add_to_cart([CartItem(product.upc, 1)])
        except KrogerError as err:
            print(f"RESULT: cart REJECTED out-of-stock UPC: {err}")
        else:
            print("RESULT: cart ACCEPTED out-of-stock UPC (HTTP 204)")
