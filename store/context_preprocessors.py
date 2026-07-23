from django.core.cache import cache
from django.db.models import Sum

from .cache_utils import HOME_TOP_SELLING_TTL, MENU_BRAND_CACHE_KEY, MENU_CATEGORY_CACHE_KEY, catalog_version
from .models import Brand, Cart, Category, Order, Wishlist


MENU_CACHE_TTL = 60 * 10

TOP_SELLING_IDS_CACHE_KEY = "home_top_selling_ids"


def top_selling_product_ids():
    """Cached ids of the best-selling products (shared by home + card badges)."""
    return cache.get_or_set(
        TOP_SELLING_IDS_CACHE_KEY,
        lambda: list(
            Order.objects.values("product_id")
            .annotate(total_quantity=Sum("quantity"))
            .order_by("-total_quantity", "-product_id")
            .values_list("product_id", flat=True)[:8]
        ),
        HOME_TOP_SELLING_TTL,
    )


def merch_badges(request):
    """Bestseller ids for product-card badges, available on every page."""
    return {"bestseller_product_ids": set(top_selling_product_ids())}


def store_menu(request):
    categories = cache.get(MENU_CATEGORY_CACHE_KEY)
    if categories is None:
        categories = list(
            Category.objects.filter(is_active=True)
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