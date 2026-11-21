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
CONF_LOCATION_ADDRESS: Final = "location_address"
CONF_ZIP_CODE: Final = "zip_code"
CONF_MODALITY: Final = "modality"
CONF_DEBOUNCE_SECONDS: Final = "debounce_seconds"
CONF_STOCK_CHECK_HOURS: Final = "stock_check_hours"
CONF_GIVE_UP_DAYS: Final = "give_up_days"
CONF_ORDER_DAYS: Final = "order_days"
CONF_LEAD_TIME_DAYS: Final = "lead_time_days"
CONF_NOTIFY_TARGETS: Final = "notify_targets"
CONF_RECEIPT_HOST: Final = "receipt_host"
CONF_RECEIPT_PORT: Final = "receipt_port"
CONF_PAPER_WIDTH: Final = "paper_width"
CONF_IPP_URL: Final = "ipp_url"
CONF_SAVE_PDF: Final = "save_pdf"
CONF_IMAP_ENTRY: Final = "imap_entry"
CONF_READD_SHORTED: Final = "readd_shorted"
CONF_NOTIFY_ORDERS: Final = "notify_orders"
CONF_EXTRA_SENDER_DOMAINS: Final = "extra_sender_domains"
DEFAULT_READD_SHORTED: Final = False
DEFAULT_NOTIFY_ORDERS: Final = True

DEFAULT_RECEIPT_PORT: Final = 9100
DEFAULT_PAPER_WIDTH: Final = "80"
PAPER_WIDTHS: Final = ("58", "80")
DEFAULT_SAVE_PDF: Final = True
PDF_SUBDIR: Final = "kroger_restock"

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
STORAGE_MINOR_VERSION: Final = 3

EVENT_SCANNED: Final = f"{DOMAIN}_scanned"
EVENT_BACK_IN_STOCK: Final = f"{DOMAIN}_back_in_stock"
EVENT_ORDER_UPDATE: Final = f"{DOMAIN}_order_update"

# Services
SERVICE_SCAN_UPC: Final = "scan_upc"
SERVICE_ADD_ITEM: Final = "add_item"
SERVICE_RESOLVE_ITEM: Final = "resolve_item"
SERVICE_SYNC: Final = "sync"
SERVICE_READD_ITEM: Final = "readd_item"
SERVICE_CHECK_STOCK: Final = "check_stock"
SERVICE_PRINT_LIST: Final = "print_list"
SERVICE_MARK_CART_RECEIVED: Final = "mark_cart_received"

PRINT_RECEIPT: Final = "receipt"
PRINT_PDF: Final = "pdf"
PRINT_BOTH: Final = "both"
PRINT_TARGETS: Final = (PRINT_RECEIPT, PRINT_PDF, PRINT_BOTH)

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_UPC: Final = "upc"
ATTR_QUANTITY: Final = "quantity"
ATTR_SOURCE: Final = "source"
ATTR_NAME: Final = "name"
ATTR_ITEM_ID: Final = "item_id"
ATTR_PRODUCT_ID: Final = "product_id"
ATTR_TARGET: Final = "target"

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
