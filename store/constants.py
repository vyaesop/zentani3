from decimal import Decimal

# Affiliate
AFFILIATE_SESSION_KEY = "affiliate_profile_id"
AFFILIATE_CLICK_SESSION_KEY = "affiliate_click_id"
AFFILIATE_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
AFFILIATE_RATE_PERCENT = Decimal("5.00")

# Delivery (ETB). Addis Ababa is the only area we deliver to.
DELIVERY_CITY = "Addis Ababa"
DELIVERY_CITY_CHOICES = ((DELIVERY_CITY, DELIVERY_CITY),)
OUTSIDE_DELIVERY_AREA_MESSAGE = "We deliver inside Addis Ababa only."
ADDIS_FREE_SHIPPING_THRESHOLD = Decimal("3500.00")
ADDIS_SHIPPING_FEE = Decimal("200.00")

# Pagination
COLLECTION_PAGE_SIZE = 24
DIRECTORY_PAGE_SIZE = 24
ACCOUNT_ORDERS_PAGE_SIZE = 12

# Product / sizes
SIZE_DISPLAY_ORDER = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL")
RECENTLY_VIEWED_SESSION_KEY = "recently_viewed_product_ids"

# Brands
# Unbranded stock is filed under a placeholder brand rather than a null FK,
# because the scraper and the AI intake both need something to point at. That
# is bookkeeping, not a label, so it never reaches shoppers: no brand line on
# the product page or card, no brand row in a Telegram post, and no entry in
# the brand directory, filters or sitemap.
PLACEHOLDER_BRAND_TITLES = ("no brand", "nobrand", "no-brand")


def is_placeholder_brand_title(title):
    return str(title or "").strip().casefold() in PLACEHOLDER_BRAND_TITLES


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
