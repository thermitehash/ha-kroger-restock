"""Constants for the Kroger Restock integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "kroger_restock"

API_BASE_URL: Final = "https://api.kroger.com/v1"
OAUTH2_AUTHORIZE: Final = f"{API_BASE_URL}/connect/oauth2/authorize"
OAUTH2_TOKEN: Final = f"{API_BASE_URL}/connect/oauth2/token"

SCOPE_PRODUCT: Final = "product.compact"
SCOPE_CART: Final = "cart.basic:write"
SCOPE_PROFILE: Final = "profile.compact"
OAUTH2_SCOPES: Final = (SCOPE_PRODUCT, SCOPE_CART, SCOPE_PROFILE)

# Config entry data / options keys
CONF_LOCATION_ID: Final = "location_id"
CONF_LOCATION_NAME: Final = "location_name"
CONF_ZIP_CODE: Final = "zip_code"
CONF_MODALITY: Final = "modality"
CONF_DEBOUNCE_SECONDS: Final = "debounce_seconds"
CONF_STOCK_CHECK_HOURS: Final = "stock_check_hours"
CONF_GIVE_UP_DAYS: Final = "give_up_days"
CONF_ORDER_DAYS: Final = "order_days"
CONF_LEAD_TIME_DAYS: Final = "lead_time_days"
CONF_NOTIFY_TARGETS: Final = "notify_targets"

# Option values (lowercase for translations); the API wants them uppercased.
MODALITY_PICKUP: Final = "pickup"
MODALITY_DELIVERY: Final = "delivery"
MODALITIES: Final = (MODALITY_PICKUP, MODALITY_DELIVERY)

DEFAULT_MODALITY: Final = MODALITY_PICKUP
DEFAULT_DEBOUNCE_SECONDS: Final = 3.0
DEFAULT_STOCK_CHECK_HOURS: Final = 3.0
DEFAULT_GIVE_UP_DAYS: Final = 30
DEFAULT_LEAD_TIME_DAYS: Final = 1

WEEKDAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 1

EVENT_SCANNED: Final = f"{DOMAIN}_scanned"

# Services
SERVICE_SCAN_UPC: Final = "scan_upc"
SERVICE_ADD_ITEM: Final = "add_item"
SERVICE_RESOLVE_ITEM: Final = "resolve_item"
SERVICE_SYNC: Final = "sync"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_UPC: Final = "upc"
ATTR_QUANTITY: Final = "quantity"
ATTR_SOURCE: Final = "source"
ATTR_NAME: Final = "name"
ATTR_ITEM_ID: Final = "item_id"
ATTR_PRODUCT_ID: Final = "product_id"

SEARCH_LIMIT: Final = 10
MAX_REVIEW_CANDIDATES: Final = 5
PRODUCT_CACHE_SECONDS: Final = 600
MISS_CACHE_SECONDS: Final = 86_400


class ItemStatus(StrEnum):
    """Lifecycle status of a list item."""

    UNMATCHED = "unmatched"
    NEEDS_REVIEW = "needs_review"
    WAITING = "waiting"
    HELD = "held"
    IN_CART = "in_cart"
    RECEIVED = "received"


ACTIVE_STATUSES: Final = frozenset(
    {
        ItemStatus.UNMATCHED,
        ItemStatus.NEEDS_REVIEW,
        ItemStatus.WAITING,
        ItemStatus.HELD,
        ItemStatus.IN_CART,
    }
)


class ItemSource(StrEnum):
    """Where an item came from."""

    SCAN = "scan"
    SHORTCUT = "shortcut"
    ESPHOME = "esphome"
    MANUAL = "manual"
    ASSIST = "assist"


class ScanResult(StrEnum):
    """Result reported for a scan or add."""

    IN_CART = "in_cart"
    WAITING = "waiting"
    UNMATCHED = "unmatched"
    NEEDS_REVIEW = "needs_review"
    DUPLICATE = "duplicate"


class StockLevel(StrEnum):
    """Kroger inventory stock levels."""

    HIGH = "HIGH"
    LOW = "LOW"
    TEMPORARILY_OUT_OF_STOCK = "TEMPORARILY_OUT_OF_STOCK"
