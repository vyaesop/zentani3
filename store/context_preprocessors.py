from django.core.cache import cache
from django.db.models import Min, Max
from django.contrib.auth.models import User

from .models import Brand, Cart, Category, Product


MENU_CACHE_TTL = 60 * 10


def store_menu(request):
    categories = cache.get("store_menu_categories")
    if categories is None:
        categories = list(
            Category.objects.filter(is_active=True)
            .only("id", "title", "slug")
            .order_by("title")
        )
        cache.set("store_menu_categories", categories, MENU_CACHE_TTL)

    context = {
        "categories_menu": categories,
    }
    return context


def brand_menu(request):
    brands = cache.get("store_menu_brands")
    if brands is None:
        brands = list(
            Brand.objects.filter(is_active=True)
            .only("id", "title", "slug")
            .order_by("title")
        )
        cache.set("store_menu_brands", brands, MENU_CACHE_TTL)

    context = {
        "brands_menu": brands,
    }
    return context


def cart_menu(request):
    if request.user.is_authenticated:
        cart_items_count = Cart.objects.filter(user=request.user).count()
        return {"cart_items_count": cart_items_count}

    guest_user_id = request.session.get("guest_session_user_id")
    if guest_user_id:
        guest_user = User.objects.filter(id=guest_user_id).first()
        if guest_user:
            return {"cart_items_count": Cart.objects.filter(user=guest_user).count()}

    return {"cart_items_count": 0}


def default(request):
    min_max_price = Product.objects.aggregate(Min("price"), Max("price"))

    return {
        "min_max_price": min_max_price,
    }