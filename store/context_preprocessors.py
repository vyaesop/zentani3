from django.core.cache import cache
from django.contrib.auth.models import User

from .cache_utils import MENU_BRAND_CACHE_KEY, MENU_CATEGORY_CACHE_KEY, catalog_version
from .models import Brand, Cart, Category, Wishlist


MENU_CACHE_TTL = 60 * 10


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
    wishlist_count = 0
    if request.user.is_authenticated:
        cart_items_count = Cart.objects.filter(user=request.user).count()
        wishlist_count = Wishlist.objects.filter(user=request.user).count()
        return {"cart_items_count": cart_items_count, "wishlist_count": wishlist_count}

    guest_user_id = request.session.get("guest_session_user_id")
    if guest_user_id:
        guest_user = User.objects.filter(id=guest_user_id).first()
        if guest_user:
            return {"cart_items_count": Cart.objects.filter(user=guest_user).count(), "wishlist_count": 0}

    return {"cart_items_count": 0, "wishlist_count": 0}