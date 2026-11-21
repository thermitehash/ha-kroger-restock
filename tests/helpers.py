"""Shared test helpers: Kroger payload builders and a fake API client."""

from __future__ import annotations

from typing import Any

from custom_components.kroger_restock.api import (
    CartItem,
    KrogerAuthError,
    Location,
    Product,
)

LOCATION_ID = "01400943"


def product_payload(
    product_id: str,
    description: str,
    *,
    brand: str | None = "Kroger",
    size: str | None = "1 gal",
    stock: str | None = "HIGH",
    aisle: str | None = "12",
    aisle_description: str | None = None,
    price: float | None = 3.49,
    promo: float | None = 0,
) -> dict[str, Any]:
    """Return a product as the Kroger API shapes it."""
    item: dict[str, Any] = {
        "itemId": product_id,
        "size": size,
        "price": {"regular": price, "promo": promo},
        "fulfillment": {
            "curbside": True,
            "delivery": True,
            "instore": True,
            "shiptohome": False,
        },
    }
    if stock is not None:
        item["inventory"] = {"stockLevel": stock}
    data: dict[str, Any] = {
        "productId": product_id,
        "upc": product_id,
        "description": description,
        "brand": brand,
        "items": [item],
        "images": [
            {
                "perspective": "front",
                "default": True,
                "sizes": [
                    {"size": "medium", "url": f"https://img.example/{product_id}.jpg"}
                ],
            }
        ],
        "aisleLocations": (
            [{"number": aisle, "description": aisle_description or f"AISLE {aisle}"}]
            if aisle
            else []
        ),
    }
    return data


def make_product(product_id: str, description: str, **kwargs: Any) -> Product:
    """Build a Product model."""
    return Product.from_api(product_payload(product_id, description, **kwargs))


class FakeKrogerApi:
    """In-memory stand-in for KrogerApiClient."""

    def __init__(self) -> None:
        """Initialize."""
        self.products: dict[str, Product] = {}
        # Per-store overrides: location_id -> product_id -> Product.
        self.store_products: dict[str, dict[str, Product]] = {}
        self.search_results: dict[str, list[Product]] = {}
        self.locations: list[Location] = [
            Location(
                location_id=LOCATION_ID,
                name="Kroger Test Store",
                address_line="1 Main St",
                city="Cincinnati",
                state="OH",
                zip_code="45202",
            )
        ]
        self.cart_calls: list[list[CartItem]] = []
        self.product_calls: list[str] = []
        self.search_calls: list[str] = []
        self.location_calls: list[str] = []
        self.fail_cart: Exception | None = None
        self.call_counts: dict[str, int] = {}
        self.products_use_app_token = False
        self.profile_id = "profile-123"

    def add(self, product: Product) -> Product:
        """Register a product."""
        self.products[product.product_id] = product
        return product

    def set_stock(self, product_id: str, stock: str | None) -> None:
        """Change a product's stock level."""
        old = self.products[product_id]
        self.products[product_id] = Product(
            **{
                **{f: getattr(old, f) for f in old.__dataclass_fields__},
                "stock_level": stock,
            }
        )

    @property
    def cart_lines(self) -> list[tuple[str, int]]:
        """Every cart line pushed, flattened."""
        return [(i.upc, i.quantity) for call in self.cart_calls for i in call]

    async def async_get_product(
        self, product_id: str, location_id: str
    ) -> Product | None:
        """Look up a product."""
        self.product_calls.append(product_id)
        return self.store_products.get(location_id, self.products).get(product_id)

    async def async_search_products(
        self, term: str, location_id: str, limit: int = 10
    ) -> list[Product]:
        """Search."""
        self.search_calls.append(term)
        return self.search_results.get(term.lower(), [])

    async def async_add_to_cart(self, items: list[CartItem]) -> None:
        """Record a cart push."""
        if self.fail_cart is not None:
            raise self.fail_cart
        self.cart_calls.append(list(items))

    async def async_get_locations(
        self, zip_code: str, limit: int = 10
    ) -> list[Location]:
        """Return stores."""
        return self.locations if zip_code == "45202" else []

    async def async_get_location(self, location_id: str) -> Location | None:
        """Return one store."""
        self.location_calls.append(location_id)
        return next(
            (loc for loc in self.locations if loc.location_id == location_id), None
        )

    async def async_get_profile_id(self) -> str:
        """Return the profile id."""
        return self.profile_id


__all__ = ["FakeKrogerApi", "KrogerAuthError", "make_product", "product_payload"]
