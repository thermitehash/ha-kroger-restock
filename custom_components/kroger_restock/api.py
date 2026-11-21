"""Async client for the Kroger public API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from http import HTTPStatus
from json import loads as json_loads
import logging
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import API_BASE_URL, MODALITY_PICKUP, SEARCH_LIMIT, StockLevel

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = ClientTimeout(total=20)

TokenGetter = Callable[[], Awaitable[str]]


class KrogerError(Exception):
    """Base error for the Kroger API."""


class KrogerConnectionError(KrogerError):
    """Network-level failure talking to Kroger."""


class KrogerAuthError(KrogerError):
    """The user token was rejected."""


class KrogerRateLimitError(KrogerError):
    """Kroger returned HTTP 429."""


class KrogerResponseError(KrogerError):
    """Kroger returned an unexpected status."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


@dataclass(frozen=True, slots=True)
class Location:
    """A Kroger-family store."""

    location_id: str
    name: str
    chain: str | None = None
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None

    @property
    def label(self) -> str:
        """Human-readable label for selectors."""
        parts = [p for p in (self.address_line, self.city, self.state) if p]
        address = ", ".join(parts)
        return f"{self.name} — {address}" if address else self.name

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Location:
        """Build from an API payload."""
        address = data.get("address") or {}
        return cls(
            location_id=str(data["locationId"]),
            name=str(data.get("name") or data.get("chain") or data["locationId"]),
            chain=data.get("chain"),
            address_line=address.get("addressLine1"),
            city=address.get("city"),
            state=address.get("state"),
            zip_code=address.get("zipCode"),
        )


@dataclass(frozen=True, slots=True)
class Aisle:
    """Where a product is in the store."""

    number: str | None
    description: str | None

    @property
    def label(self) -> str | None:
        """Short label, e.g. 'Aisle 12'."""
        if self.number and self.number not in {"0", ""}:
            return f"Aisle {self.number}"
        return self.description or None

    @property
    def sort_key(self) -> tuple[int, str]:
        """Sort numerically by aisle number; unknown aisles last."""
        try:
            return (int(str(self.number)), self.description or "")
        except TypeError, ValueError:
            return (10_000, self.description or "")


@dataclass(frozen=True, slots=True)
class Product:
    """A Kroger product as seen at one location."""

    product_id: str
    upc: str
    description: str
    brand: str | None = None
    size: str | None = None
    image_url: str | None = None
    price: float | None = None
    regular_price: float | None = None
    stock_level: str | None = None
    aisle: Aisle | None = None
    fulfillment: dict[str, bool] = field(default_factory=dict)

    @property
    def in_stock(self) -> bool:
        """Return False only when Kroger says it's temporarily out of stock.

        Products without inventory data are treated as available.
        """
        return self.stock_level != StockLevel.TEMPORARILY_OUT_OF_STOCK

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Product:
        """Build from an API payload."""
        items: list[dict[str, Any]] = data.get("items") or []
        item = items[0] if items else {}
        price_data = item.get("price") or {}
        regular = _as_float(price_data.get("regular"))
        promo = _as_float(price_data.get("promo"))
        price = promo if promo else regular
        inventory = item.get("inventory") or {}
        aisles: list[dict[str, Any]] = data.get("aisleLocations") or []
        aisle = None
        if aisles:
            first = aisles[0]
            number = first.get("number")
            aisle = Aisle(
                number=str(number) if number is not None else None,
                description=first.get("description"),
            )
        product_id = str(data["productId"])
        return cls(
            product_id=product_id,
            upc=str(data.get("upc") or product_id),
            description=str(data.get("description") or product_id).strip(),
            brand=data.get("brand"),
            size=item.get("size"),
            image_url=_pick_image(data.get("images") or []),
            price=price,
            regular_price=regular,
            stock_level=inventory.get("stockLevel"),
            aisle=aisle,
            fulfillment={
                k: bool(v) for k, v in (item.get("fulfillment") or {}).items()
            },
        )


@dataclass(frozen=True, slots=True)
class CartItem:
    """One line for PUT /cart/add."""

    upc: str
    quantity: int = 1
    modality: str = MODALITY_PICKUP

    def as_dict(self) -> dict[str, Any]:
        """Return the API representation."""
        return {"upc": self.upc, "quantity": self.quantity, "modality": self.modality}


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except TypeError, ValueError:
        return None


_IMAGE_SIZE_ORDER = ("medium", "large", "small", "xlarge", "thumbnail")


def _pick_image(images: list[dict[str, Any]]) -> str | None:
    """Pick the front (or featured) image at a reasonable size."""
    if not images:
        return None
    ordered = sorted(
        images,
        key=lambda img: (
            img.get("perspective") != "front",
            not (img.get("featured") or img.get("default")),
        ),
    )
    sizes = {s.get("size"): s.get("url") for s in ordered[0].get("sizes") or []}
    for size in _IMAGE_SIZE_ORDER:
        if sizes.get(size):
            return sizes[size]
    return next((url for url in sizes.values() if url), None)


class KrogerApiClient:
    """Thin async wrapper around the endpoints this integration uses."""

    def __init__(
        self,
        session: ClientSession,
        user_token: TokenGetter,
        app_token: TokenGetter | None = None,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize.

        ``user_token`` returns a valid authorization-code access token.
        ``app_token`` returns a client-credentials token, used for product
        calls only if the user token is refused for them.
        """
        self._session = session
        self._user_token = user_token
        self._app_token = app_token
        self._base_url = base_url.rstrip("/")
        self.products_use_app_token = False
        self._call_day: date = date.today()
        self.call_counts: dict[str, int] = {}

    def _count(self, endpoint: str) -> None:
        today = date.today()
        if today != self._call_day:
            self._call_day = today
            self.call_counts = {}
        self.call_counts[endpoint] = self.call_counts.get(endpoint, 0) + 1

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> ClientResponse:
        self._count(endpoint)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            response = await self._session.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except (ClientError, TimeoutError) as err:
            raise KrogerConnectionError(str(err)) from err
        if response.status == HTTPStatus.TOO_MANY_REQUESTS:
            raise KrogerRateLimitError(f"Rate limited on {endpoint}")
        return response

    async def _catalog_request(
        self, path: str, params: dict[str, Any], endpoint: str = "products"
    ) -> tuple[int, dict[str, Any]]:
        """GET a catalog endpoint, falling back to an app token if needed.

        Kroger documents products and locations with a client-credentials
        token. We try the user token first and switch for good if refused.
        """
        if self.products_use_app_token and self._app_token is not None:
            token = await self._app_token()
        else:
            token = await self._user_token()
        response = await self._request(
            "GET", path, token, endpoint=endpoint, params=params
        )
        if (
            response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)
            and not self.products_use_app_token
            and self._app_token is not None
        ):
            _LOGGER.info(
                "User token refused for product calls (HTTP %s); "
                "using client-credentials token instead",
                response.status,
            )
            response.release()
            self.products_use_app_token = True
            token = await self._app_token()
            response = await self._request(
                "GET", path, token, endpoint=endpoint, params=params
            )
        return await _read_json(response)

    async def async_get_locations(
        self, zip_code: str, limit: int = 10
    ) -> list[Location]:
        """Find stores near a ZIP code."""
        status, body = await self._catalog_request(
            "/locations",
            {"filter.zipCode.near": zip_code, "filter.limit": limit},
            endpoint="locations",
        )
        _raise_for_status(status, body, user_call=not self.products_use_app_token)
        return [Location.from_api(row) for row in body.get("data") or []]

    async def async_get_product(
        self, product_id: str, location_id: str
    ) -> Product | None:
        """Look up a product by its 13-digit ID. Returns None if not found."""
        status, body = await self._catalog_request(
            f"/products/{product_id}", {"filter.locationId": location_id}
        )
        if status in (HTTPStatus.NOT_FOUND, HTTPStatus.BAD_REQUEST):
            return None
        _raise_for_status(status, body, user_call=not self.products_use_app_token)
        data = body.get("data")
        if not data:
            return None
        if isinstance(data, list):
            data = data[0]
        return Product.from_api(data)

    async def async_search_products(
        self, term: str, location_id: str, limit: int = SEARCH_LIMIT
    ) -> list[Product]:
        """Search products by free text (Kroger requires >= 3 characters)."""
        term = " ".join(term.split()[:8])
        if len(term) < 3:
            return []
        status, body = await self._catalog_request(
            "/products",
            {
                "filter.term": term,
                "filter.locationId": location_id,
                "filter.limit": limit,
            },
        )
        if status == HTTPStatus.NOT_FOUND:
            return []
        _raise_for_status(status, body, user_call=not self.products_use_app_token)
        return [Product.from_api(row) for row in body.get("data") or []]

    async def async_add_to_cart(self, items: list[CartItem]) -> None:
        """Add items to the user's cart. The cart is write-only."""
        if not items:
            return
        token = await self._user_token()
        response = await self._request(
            "PUT",
            "/cart/add",
            token,
            endpoint="cart",
            json={"items": [item.as_dict() for item in items]},
        )
        status, body = await _read_json(response)
        _raise_for_status(status, body, user_call=True)

    async def async_get_profile_id(self) -> str:
        """Return the Kroger profile ID of the signed-in user."""
        token = await self._user_token()
        response = await self._request(
            "GET", "/identity/profile", token, endpoint="identity"
        )
        status, body = await _read_json(response)
        _raise_for_status(status, body, user_call=True)
        return str((body.get("data") or {})["id"])


async def _read_json(response: ClientResponse) -> tuple[int, dict[str, Any]]:
    status = response.status
    body: Any = {}
    try:
        text = await response.text()
        if text:
            body = json_loads(text)
    except ClientError, ValueError:
        body = {}
    finally:
        response.release()
    return status, body if isinstance(body, dict) else {"data": body}


def _raise_for_status(status: int, body: dict[str, Any], *, user_call: bool) -> None:
    if HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES:
        return
    errors = body.get("errors")
    reason = errors.get("reason") if isinstance(errors, dict) else None
    message = str(
        body.get("error_description") or body.get("message") or reason or body
    )
    if status == HTTPStatus.UNAUTHORIZED and user_call:
        raise KrogerAuthError(message)
    raise KrogerResponseError(status, message)
