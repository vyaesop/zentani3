from .models import Category, Cart, Product, Brand
from django.db.models import Min, Max
def store_menu(request):
    categories = Category.objects.filter(is_active=True)
    context = {
        'categories_menu': categories,
    }
    return context
def brand_menu(request):
    brands = Brand.objects.filter(is_active=True)
    context = {
        'brands_menu': brands,
    }
    return context

def cart_menu(request):
    if request.user.is_authenticated:
        cart_items= Cart.objects.filter(user=request.user)
        context = {
            'cart_items': cart_items,
        }
    else:
        context = {}
    return context
def default(request):
    min_max_price = Product.objects.aggregate(Min("price"), Max("price"))

    return{
        'min_max_price':min_max_price,
    }