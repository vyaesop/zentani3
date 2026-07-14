from decimal import Decimal

# Affiliate
AFFILIATE_SESSION_KEY = "affiliate_profile_id"
AFFILIATE_CLICK_SESSION_KEY = "affiliate_click_id"
AFFILIATE_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
AFFILIATE_RATE_PERCENT = Decimal("5.00")

# Shipping (ETB)
ADDIS_FREE_SHIPPING_THRESHOLD = Decimal("3500.00")
ADDIS_SHIPPING_FEE = Decimal("80.00")
OUTSIDE_ADDIS_SHIPPING_FEE = Decimal("180.00")

# Pagination
COLLECTION_PAGE_SIZE = 24
DIRECTORY_PAGE_SIZE = 24
ACCOUNT_ORDERS_PAGE_SIZE = 12

# Product / sizes
SIZE_DISPLAY_ORDER = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL")
RECENTLY_VIEWED_SESSION_KEY = "recently_viewed_product_ids"


def size_sort_key(size_value):
    """Sort sizes garment-first (XS < S < M …), then alphabetically."""
    normalized = size_value.upper()
    if normalized in SIZE_DISPLAY_ORDER:
        return (0, SIZE_DISPLAY_ORDER.index(normalized))
    return (1, normalized)

COLLECTION_SORT_OPTIONS = (
    ("newest", "Newest first", "-created_at"),
    ("price-asc", "Price: Low to High", "price"),
    ("price-desc", "Price: High to Low", "-price"),
    ("name-asc", "Name: A-Z", "title"),
)

# Order status
ORDER_STATUS_SEQUENCE = ["Pending", "Accepted", "Packed", "On The Way", "Delivered"]
ORDER_STATUS_COPY = {
    "Pending": "We received your order and it is waiting for confirmation.",
    "Accepted": "Your order has been confirmed by the store.",
    "Packed": "Your items are being prepared for dispatch.",
    "On The Way": "Your order is currently out for delivery.",
    "Delivered": "The order was delivered successfully.",
    "Cancelled": "This order was cancelled before delivery.",
}

# Session keys
TELEGRAM_ORDER_STATE_PREFIX = "telegram_order_state"
TELEGRAM_ORDER_STATE_TTL_SECONDS = 60 * 30
