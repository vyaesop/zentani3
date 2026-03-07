import decimal
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views import View

from store.models import Address, Brand, Cart, Category, Coupon, Order, Product

from .forms import AddressForm, RegistrationForm


PRODUCT_LIST_FIELDS = (
    "id",
    "slug",
    "title",
    "price",
    "product_image",
    "is_sold_out",
    "category__title",
    "category__slug",
    "brand__title",
    "brand__slug",
)


def _build_product_detail_context(product):
    related_products = (
        Product.objects.filter(is_active=True, category=product.category)
        .exclude(id=product.id)
        .select_related("category", "brand")
        .only(*PRODUCT_LIST_FIELDS)[:4]
    )
    p_image = product.p_images.only("id", "image").all()
    available_sizes_list = [s.strip() for s in product.available_sizes.split(",") if s.strip()] if product.available_sizes else []
    return {
        "product": product,
        "related_products": related_products,
        "p_image": p_image,
        "available_sizes": available_sizes_list,
    }


def home(request):
    categories = Category.objects.filter(is_active=True, is_featured=True).only("id", "title", "slug", "category_image").order_by("-created_at")[:8]
    brands = Brand.objects.filter(is_active=True, is_featured=True).only("id", "title", "slug", "brand_image").order_by("-created_at")[:12]
    products = Product.objects.filter(is_active=True, is_featured=True).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)[:24]
    context = {
        "categories": categories,
        "products": products,
        "brands": brands,
    }
    return render(request, "store/index.html", context)


def detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "brand"),
        slug=slug,
    )
    context = _build_product_detail_context(product)
    return render(request, "store/detail.html", context)


def search_view(request):
    query = request.GET.get("q")
    products = Product.objects.filter(
        title__icontains="" if query is None else query,
        is_active=True,
    ).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)

    context = {
        "products": products,
        "query": query,
    }

    return render(request, "store/search.html", context)


def products(request):
    products = Product.objects.filter(is_active=True).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)
    context = {
        "products": products,
    }
    return render(request, "store/products.html", context)


def filter_product(request):
    categories = request.GET.getlist("category[]")

    min_price = request.GET["min_price"]
    max_price = request.GET["max_price"]

    try:
        min_price = Decimal(min_price)
        max_price = Decimal(max_price)
    except decimal.InvalidOperation:
        return JsonResponse({"error": "Invalid price values"})

    products = Product.objects.filter(is_active=True).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS).order_by("-id").distinct()

    products = products.filter(price__gte=min_price)
    products = products.filter(price__lte=max_price)

    if categories:
        products = products.filter(category__id__in=categories).distinct()

    data = render_to_string("store/product-list.html", {"products": products})
    return JsonResponse({"data": data})


def all_categories(request):
    categories = Category.objects.filter(is_active=True).only("id", "title", "slug", "category_image")
    return render(request, "store/categories.html", {"categories": categories})


def all_brands(request):
    brands = Brand.objects.filter(is_active=True).only("id", "title", "slug", "brand_image")
    return render(request, "store/brands.html", {"brands": brands})


def category_products(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = Product.objects.filter(is_active=True, category=category).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS).order_by("-sku")
    categories = Category.objects.filter(is_active=True).only("id", "title", "slug", "category_image")
    paginator = Paginator(products, 24)
    product_count = products.count()
    page = request.GET.get("page")
    paged_products = paginator.get_page(page)

    context = {
        "category": category,
        "products": paged_products,
        "categories": categories,
        "paginator": paginator,
        "product_count": product_count,
    }
    return render(request, "store/category_products.html", context)


def brand_products(request, slug):
    brand = get_object_or_404(Brand, slug=slug)
    products = Product.objects.filter(is_active=True, brand=brand).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)
    brands = Brand.objects.filter(is_active=True).only("id", "title", "slug", "brand_image")
    paginator = Paginator(products, 24)
    product_count = products.count()
    page = request.GET.get("page")
    paged_products = paginator.get_page(page)

    context = {
        "brand": brand,
        "products": paged_products,
        "brands": brands,
        "paginator": paginator,
        "product_count": product_count,
    }
    return render(request, "store/brand_products.html", context)


class RegistrationView(View):
    def get(self, request):
        form = RegistrationForm()
        return render(request, "account/register.html", {"form": form})

    def post(self, request):
        form = RegistrationForm(request.POST)
        if form.is_valid():
            messages.success(request, "Congratulations! Registration Successful!")
            user = form.save()
            login(request, user)
            return redirect("store:home")
        return render(request, "account/register.html", {"form": form})


@login_required
def profile(request):
    addresses = Address.objects.filter(user=request.user)
    orders = Order.objects.filter(user=request.user).select_related("product").only(
        "id",
        "quantity",
        "size",
        "status",
        "ordered_date",
        "line_total",
        "price_at_purchase",
        "product__id",
        "product__title",
        "product__slug",
    )
    return render(request, "account/profile.html", {"addresses": addresses, "orders": orders})


@method_decorator(login_required, name="dispatch")
class AddressView(View):
    def get(self, request):
        form = AddressForm()
        return render(request, "account/add_address.html", {"form": form})

    def post(self, request):
        form = AddressForm(request.POST)
        if form.is_valid():
            user = request.user
            address = form.cleaned_data["address"]
            city = form.cleaned_data["city"]
            phone = form.cleaned_data["phone"]
            reg = Address(user=user, address=address, city=city, phone=phone)
            reg.save()
            messages.success(request, "New Address Added Successfully.")
        return redirect("store:profile")


@login_required
def remove_address(request, id):
    a = get_object_or_404(Address, user=request.user, id=id)
    a.delete()
    messages.success(request, "Address removed.")
    return redirect("store:profile")


@login_required
def add_to_cart(request):
    user = request.user
    product_id = request.GET.get("prod_id")
    product = get_object_or_404(Product.objects.select_related("category", "brand"), id=product_id)
    selected_size = request.GET.get("size")

    if product.available_sizes and not selected_size:
        messages.error(request, "Please select a size for this product.")
        context_for_render = _build_product_detail_context(product)
        return render(request, "store/detail.html", context_for_render)

    cart_item, created = Cart.objects.get_or_create(
        user=user,
        product=product,
        size=selected_size if selected_size else None,
        defaults={"quantity": 1},
    )

    if not created:
        cart_item.quantity += 1
        cart_item.save()
        messages.success(request, f"Quantity of {product.title} (Size: {selected_size or 'N/A'}) updated in cart.")
    else:
        messages.success(request, f"Added {product.title} (Size: {selected_size or 'N/A'}) to cart.")

    context_for_render = _build_product_detail_context(product)
    return render(request, "store/detail.html", context_for_render)


@login_required
def cart(request):
    user = request.user
    cart_products = Cart.objects.filter(user=user).select_related("product", "coupon", "product__category", "product__brand")

    amount = decimal.Decimal(0)
    for item in cart_products:
        amount += item.total_price

    shipping_amount = decimal.Decimal(0)

    coupon_for_display = None
    first_item_with_coupon = cart_products.filter(coupon__isnull=False, coupon__active=True).first()
    if first_item_with_coupon:
        coupon_for_display = first_item_with_coupon.coupon

    context = {
        "cart_products": cart_products,
        "amount": amount,
        "shipping_amount": shipping_amount,
        "total_amount": amount + shipping_amount,
        "coupon": coupon_for_display,
    }
    return render(request, "store/cart.html", context)


class AddCoupon(View):
    def post(self, request, *args, **kwargs):
        code = request.POST.get("coupon", "")
        coupon = Coupon.objects.filter(code__iexact=code)

        if coupon.exists():
            cart_products = Cart.objects.filter(user=request.user)
            active_coupon = coupon.first()
            if not active_coupon.active:
                messages.warning(request, "This coupon is not active.")
                return redirect("store:cart")
            cart_products.update(coupon=active_coupon)
            messages.success(request, "Coupon applied successfully")
        else:
            messages.warning(request, "Invalid coupon code")

        return redirect("store:cart")


@login_required
def remove_cart(request, cart_id):
    if request.method == "GET":
        c = get_object_or_404(Cart, id=cart_id)
        c.delete()
        messages.success(request, "Product removed from Cart.")
    return redirect("store:cart")


@login_required
def plus_cart(request, cart_id):
    if request.method == "GET":
        cp = get_object_or_404(Cart, id=cart_id)
        cp.quantity += 1
        cp.save()
    return redirect("store:cart")


@login_required
def minus_cart(request, cart_id):
    if request.method == "GET":
        cp = get_object_or_404(Cart, id=cart_id)
        if cp.quantity == 1:
            cp.delete()
        else:
            cp.quantity -= 1
            cp.save()
    return redirect("store:cart")


@login_required
def checkout(request):
    user = request.user
    cart = Cart.objects.filter(user=user).select_related("product", "coupon")

    for c in cart:
        base_price_per_item = c.product.price
        effective_price_per_item = base_price_per_item
        if c.coupon and c.coupon.discount is not None and c.coupon.active:
            discount_percentage = Decimal(c.coupon.discount) / Decimal(100)
            discount_amount_per_item = base_price_per_item * discount_percentage
            effective_price_per_item = base_price_per_item - discount_amount_per_item

        line_total_for_order = c.quantity * effective_price_per_item
        Order(
            user=user,
            product=c.product,
            quantity=c.quantity,
            size=c.size,
            price_at_purchase=effective_price_per_item,
            line_total=line_total_for_order,
        ).save()
        c.delete()
    return redirect("store:orders")


@login_required
def orders(request):
    all_orders = Order.objects.filter(user=request.user).select_related("product").only(
        "id",
        "quantity",
        "size",
        "status",
        "ordered_date",
        "line_total",
        "price_at_purchase",
        "product__id",
        "product__title",
        "product__slug",
    ).order_by("-ordered_date")
    return render(request, "store/orders.html", {"orders": all_orders})


def shop(request):
    return render(request, "store/shop.html")


def about(request):
    return render(request, "store/about-us.html")


def contact(request):
    return render(request, "store/contact.html")


def test(request):
    return render(request, "store/test.html")
