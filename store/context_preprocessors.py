from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.urls import reverse

from .cache_utils import HOME_TOP_SELLING_TTL, MENU_BRAND_CACHE_KEY, MENU_CATEGORY_CACHE_KEY, catalog_version
from .constants import ADDIS_FREE_SHIPPING_THRESHOLD, ADDIS_SHIPPING_FEE, OUTSIDE_ADDIS_SHIPPING_FEE
from .models import Brand, Cart, Category, Order, Wishlist


MENU_CACHE_TTL = 60 * 10

TOP_SELLING_IDS_CACHE_KEY = "home_top_selling_ids"


def top_selling_product_ids():
    """Cached ids of the best-selling products (shared by home + card badges)."""
    return cache.get_or_set(
        TOP_SELLING_IDS_CACHE_KEY,
        lambda: list(
            Order.objects.filter(product__is_active=True)
            .values("product_id")
            .annotate(total_quantity=Sum("quantity"))
            .order_by("-total_quantity", "-product_id")
            .values_list("product_id", flat=True)[:8]
        ),
        HOME_TOP_SELLING_TTL,
    )


def merch_badges(request):
    """Bestseller ids for product-card badges, available on every page."""
    return {"bestseller_product_ids": set(top_selling_product_ids())}


def _active_product_count():
    return Count("product", filter=Q(product__is_active=True))


def store_menu(request):
    # Only collections that actually have something to show: a nav or filter
    # entry that leads to an empty page is a dead end for the shopper.
    categories = cache.get(MENU_CATEGORY_CACHE_KEY)
    if categories is None:
        categories = list(
            Category.objects.filter(is_active=True)
            .annotate(live_count=_active_product_count())
            .filter(live_count__gt=0)
            .only("id", "title", "slug")
            .order_by("title")
        )
        cache.set(MENU_CATEGORY_CACHE_KEY, categories, MENU_CACHE_TTL)

    context = {
        "categories_menu": categories,
    }
    return context


def brand_menu(request):
    brands = cache.get(MENU_BRAND_CACHE_KEY)
    if brands is None:
        brands = list(
            Brand.objects.filter(is_active=True)
            .annotate(live_count=_active_product_count())
            .filter(live_count__gt=0)
            .only("id", "title", "slug")
            .order_by("title")
        )
        cache.set(MENU_BRAND_CACHE_KEY, brands, MENU_CACHE_TTL)

    context = {
        "brands_menu": brands,
    }
    return context


def cache_versions(request):
    """Expose the catalog cache version for `{% cache %}` fragment keys."""
    return {"catalog_version": catalog_version()}


def cart_menu(request):
    if request.user.is_authenticated:
        cart_items_count = Cart.objects.filter(user=request.user).count()
        wishlist_count = Wishlist.objects.filter(user=request.user).count()
        return {"cart_items_count": cart_items_count, "wishlist_count": wishlist_count}

    session_key = request.session.session_key
    if session_key:
        return {
            "cart_items_count": Cart.objects.filter(user=None, session_key=session_key).count(),
            "wishlist_count": 0,
        }

    return {"cart_items_count": 0, "wishlist_count": 0}


def _telegram_channel_url():
    from store.telegram_notify import _customer_bot_settings

    _, channel_chat_id, bot_username = _customer_bot_settings()
    channel = (channel_chat_id or "").strip()
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    if bot_username:
        return f"https://t.me/{bot_username}"
    return "https://t.me/zentanee_order_bot"


def _telegram_bot_url():
    from store.telegram_notify import _customer_bot_settings

    _, _, bot_username = _customer_bot_settings()
    return f"https://t.me/{bot_username}" if bot_username else "https://t.me/zentanee_order_bot"


def _canonical_url(request):
    """Scheme + host (SITE_URL when configured) + path, query string dropped."""
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if not base:
        base = f"{request.scheme}://{request.get_host()}"
    return f"{base}{request.path}"


def store_settings(request):
    """Business identity, policy numbers and integration flags for templates.

    Every value here is env-driven so copy such as the delivery promise cannot
    drift from the fee constants the cart actually charges.
    """
    free_threshold = f"{ADDIS_FREE_SHIPPING_THRESHOLD:,.0f}"
    return {
        "store": {
            "name": settings.STORE_NAME,
            "legal_name": settings.STORE_LEGAL_NAME,
            "phone": settings.STORE_PHONE,
            "phone_href": "tel:" + "".join(ch for ch in settings.STORE_PHONE if ch.isdigit() or ch == "+"),
            "email": settings.STORE_EMAIL,
            "address": settings.STORE_ADDRESS,
            "trade_license": settings.STORE_TRADE_LICENSE,
            "tin": settings.STORE_TIN,
            "instagram_url": settings.STORE_INSTAGRAM_URL,
            "support_hours": settings.STORE_SUPPORT_HOURS,
            "telegram_channel_url": _telegram_channel_url(),
            "telegram_bot_url": _telegram_bot_url(),
            "addis_fee": f"{ADDIS_SHIPPING_FEE:.0f}",
            "outside_fee": f"{OUTSIDE_ADDIS_SHIPPING_FEE:.0f}",
            "free_threshold": free_threshold,
            "delivery_promise": f"Free delivery in Addis Ababa on orders over {free_threshold} ETB · Pay on delivery",
            "online_payments_enabled": getattr(settings, "ONLINE_PAYMENTS_ENABLED", False),
            "show_stock_counts": getattr(settings, "STORE_SHOW_STOCK_COUNTS", False),
        },
        "ga_measurement_id": getattr(settings, "GA_MEASUREMENT_ID", ""),
        "canonical_url": _canonical_url(request),
        "site_base_url": (getattr(settings, "SITE_URL", "") or f"{request.scheme}://{request.get_host()}").rstrip("/"),
        "affiliate_program_url": reverse("store:affiliate-dashboard"),
    }
