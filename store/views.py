import decimal
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.views import View

from store.models import Address, AffiliateClick, AffiliateCommission, AffiliateProfile, Brand, Cart, Category, Coupon, Order, Product

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


AFFILIATE_SESSION_KEY = "affiliate_profile_id"
AFFILIATE_CLICK_SESSION_KEY = "affiliate_click_id"
AFFILIATE_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
AFFILIATE_RATE_PERCENT = Decimal("5.00")


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


def _safe_redirect_url(request, fallback_url):
    candidate = (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
    )
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host(), *getattr(settings, "ALLOWED_HOSTS", [])},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback_url


def _parse_available_sizes(product):
    if not product.available_sizes:
        return []
    return [size.strip() for size in product.available_sizes.split(",") if size.strip()]


def _coupon_issue(coupon):
    if not coupon:
        return "Coupon does not exist."

    today = timezone.localdate()

    if not coupon.active:
        return "This coupon is not active."
    if coupon.active_date and today < coupon.active_date:
        return "This coupon is not active yet."
    if coupon.expiry_date and today > coupon.expiry_date:
        return "This coupon has expired."
    if coupon.discount is None or coupon.discount <= 0 or coupon.discount > 100:
        return "This coupon is invalid."

    return None


def _effective_unit_price(product_price, coupon):
    if _coupon_issue(coupon):
        return product_price

    discount_percentage = Decimal(coupon.discount) / Decimal(100)
    discount_amount_per_item = product_price * discount_percentage
    return product_price - discount_amount_per_item


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _affiliate_profile_from_session(request):
    affiliate_profile_id = request.session.get(AFFILIATE_SESSION_KEY)
    if not affiliate_profile_id:
        return None
    return AffiliateProfile.objects.filter(id=affiliate_profile_id, is_active=True).select_related("user").first()


def _calculate_commission_amount(line_total):
    return (line_total * AFFILIATE_RATE_PERCENT / Decimal("100")).quantize(Decimal("0.01"))


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
    has_affiliate_profile = AffiliateProfile.objects.filter(user=request.user).exists()
    return render(
        request,
        "account/profile.html",
        {
            "addresses": addresses,
            "orders": orders,
            "has_affiliate_profile": has_affiliate_profile,
        },
    )


@login_required
def affiliate_dashboard(request):
    affiliate_profile, _ = AffiliateProfile.objects.get_or_create(
        user=request.user,
        defaults={"code": AffiliateProfile.generate_unique_code()},
    )

    if not affiliate_profile.code:
        affiliate_profile.code = AffiliateProfile.generate_unique_code()
        affiliate_profile.save(update_fields=["code", "updated_at"])

    base_ref_link = request.build_absolute_uri(reverse("store:affiliate-track", args=[affiliate_profile.code]))
    default_share_link = f"{base_ref_link}?next=/"
    total_clicks = AffiliateClick.objects.filter(affiliate=affiliate_profile).count()
    total_converted_clicks = AffiliateClick.objects.filter(affiliate=affiliate_profile, converted=True).count()

    commissions = AffiliateCommission.objects.filter(affiliate=affiliate_profile).select_related("order", "customer").order_by("-created_at")
    products_for_sharing = Product.objects.filter(is_active=True, is_sold_out=False).only("id", "title", "slug").order_by("-created_at")[:24]
    pending_total = commissions.filter(status="Pending").aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    paid_total = commissions.filter(status="Paid").aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    lifetime_total = commissions.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    context = {
        "affiliate_profile": affiliate_profile,
        "base_ref_link": base_ref_link,
        "default_share_link": default_share_link,
        "total_clicks": total_clicks,
        "total_converted_clicks": total_converted_clicks,
        "pending_total": pending_total,
        "paid_total": paid_total,
        "lifetime_total": lifetime_total,
        "commissions": commissions[:25],
        "products_for_sharing": products_for_sharing,
    }
    return render(request, "account/affiliate_dashboard.html", context)


def track_affiliate_link(request, code):
    affiliate_profile = get_object_or_404(AffiliateProfile.objects.select_related("user"), code=code, is_active=True)

    # Prevent self-referrals.
    if request.user.is_authenticated and request.user.id == affiliate_profile.user_id:
        messages.info(request, "You cannot use your own affiliate link.")
        return redirect("store:home")

    request.session[AFFILIATE_SESSION_KEY] = affiliate_profile.id
    request.session.set_expiry(AFFILIATE_SESSION_MAX_AGE_SECONDS)
    session_key = _ensure_session_key(request)

    click = AffiliateClick.objects.create(
        affiliate=affiliate_profile,
        session_key=session_key,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
        landing_path=(request.GET.get("next") or "")[:300],
    )
    request.session[AFFILIATE_CLICK_SESSION_KEY] = click.id

    destination = request.GET.get("next") or "/"
    if url_has_allowed_host_and_scheme(
        url=destination,
        allowed_hosts={request.get_host(), *getattr(settings, "ALLOWED_HOSTS", [])},
        require_https=request.is_secure(),
    ):
        return redirect(destination)
    return redirect("store:home")


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
    if request.method != "POST":
        messages.warning(request, "Invalid request method.")
        return redirect("store:profile")

    a = get_object_or_404(Address, user=request.user, id=id)
    a.delete()
    messages.success(request, "Address removed.")
    return redirect("store:profile")


@login_required
def add_to_cart(request):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _json(message, ok=True, status=200):
        payload = {
            "ok": ok,
            "message": message,
            "cart_items_count": Cart.objects.filter(user=request.user).count(),
        }
        return JsonResponse(payload, status=status)

    if request.method != "POST":
        if is_ajax:
            return _json("Please use the add-to-cart button to add an item.", ok=False, status=405)
        messages.warning(request, "Please use the add-to-cart button to add an item.")
        return redirect("store:home")

    user = request.user
    product_id = request.POST.get("prod_id")
    selected_size = (request.POST.get("size") or "").strip()

    if not product_id:
        if is_ajax:
            return _json("Unable to add product to cart. Please try again.", ok=False, status=400)
        messages.error(request, "Unable to add product to cart. Please try again.")
        return redirect("store:home")

    product = get_object_or_404(
        Product.objects.select_related("category", "brand"),
        id=product_id,
        is_active=True,
    )

    if product.is_sold_out:
        if is_ajax:
            return _json(f"{product.title} is currently sold out.", ok=False, status=400)
        messages.warning(request, f"{product.title} is currently sold out.")
        return redirect("store:product-detail", slug=product.slug)

    available_sizes = _parse_available_sizes(product)
    selected_size_value = selected_size or None

    if available_sizes and not selected_size:
        if is_ajax:
            return _json("Please select a size for this product.", ok=False, status=400)
        messages.error(request, "Please select a size for this product.")
        return redirect("store:product-detail", slug=product.slug)

    if selected_size and selected_size not in available_sizes:
        if is_ajax:
            return _json("Selected size is not available for this product.", ok=False, status=400)
        messages.error(request, "Selected size is not available for this product.")
        return redirect("store:product-detail", slug=product.slug)


    cart_item, created = Cart.objects.get_or_create(
        user=user,
        product=product,
        size=selected_size_value,
        defaults={"quantity": 1},
    )

    if not created:
        cart_item.quantity += 1
        cart_item.save(update_fields=["quantity", "updated_at"])
        success_message = f"Quantity of {product.title} (Size: {selected_size_value or 'N/A'}) updated in cart."
        messages.success(request, success_message)
    else:
        success_message = f"Added {product.title} (Size: {selected_size_value or 'N/A'}) to cart."
        messages.success(request, success_message)

    if is_ajax:
        return _json(success_message, ok=True, status=200)

    return redirect(_safe_redirect_url(request, fallback_url="store:cart"))


@login_required
def cart(request):
    user = request.user
    cart_products = Cart.objects.filter(user=user).select_related("product", "coupon", "product__category", "product__brand")

    amount = decimal.Decimal(0)
    for item in cart_products:
        line_total = item.quantity * _effective_unit_price(item.product.price, item.coupon)
        item.display_total_price = line_total
        amount += line_total

    shipping_amount = decimal.Decimal(0)

    coupon_for_display = None
    first_item_with_coupon = cart_products.filter(coupon__isnull=False).first()
    if first_item_with_coupon and not _coupon_issue(first_item_with_coupon.coupon):
        coupon_for_display = first_item_with_coupon.coupon

    context = {
        "cart_products": cart_products,
        "amount": amount,
        "shipping_amount": shipping_amount,
        "total_amount": amount + shipping_amount,
        "coupon": coupon_for_display,
    }
    return render(request, "store/cart.html", context)


@method_decorator(login_required, name="dispatch")
class AddCoupon(View):
    def post(self, request, *args, **kwargs):
        code = (request.POST.get("coupon") or "").strip()
        if not code:
            messages.warning(request, "Please enter a coupon code.")
            return redirect("store:cart")

        coupon = Coupon.objects.filter(code__iexact=code).first()
        if coupon is None:
            messages.warning(request, "Invalid coupon code.")
            return redirect("store:cart")

        issue = _coupon_issue(coupon)
        if issue:
            messages.warning(request, issue)
            return redirect("store:cart")

        cart_products = Cart.objects.filter(user=request.user)
        if not cart_products.exists():
            messages.warning(request, "Your cart is empty.")
            return redirect("store:cart")

        cart_products.update(coupon=coupon)
        messages.success(request, "Coupon applied successfully.")

        return redirect("store:cart")


@login_required
def remove_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    c = get_object_or_404(Cart, id=cart_id, user=request.user)
    c.delete()
    messages.success(request, "Product removed from cart.")
    return redirect("store:cart")


@login_required
def plus_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    cp = get_object_or_404(Cart.objects.select_related("product"), id=cart_id, user=request.user)
    if not cp.product.is_active or cp.product.is_sold_out:
        messages.warning(request, f"{cp.product.title} is no longer available.")
        return redirect("store:cart")

    cp.quantity += 1
    cp.save(update_fields=["quantity", "updated_at"])
    return redirect("store:cart")


@login_required
def minus_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    cp = get_object_or_404(Cart, id=cart_id, user=request.user)
    if cp.quantity == 1:
        cp.delete()
    else:
        cp.quantity -= 1
        cp.save(update_fields=["quantity", "updated_at"])
    return redirect("store:cart")


@login_required
def checkout(request):
    if request.method != "POST":
        messages.warning(request, "Invalid checkout request.")
        return redirect("store:cart")

    user = request.user
    affiliate_profile = _affiliate_profile_from_session(request)
    if affiliate_profile and affiliate_profile.user_id == user.id:
        affiliate_profile = None

    cart_items = list(Cart.objects.filter(user=user).select_related("product", "coupon"))

    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect("store:cart")

    unavailable_products = [
        c.product.title
        for c in cart_items
        if (not c.product.is_active) or c.product.is_sold_out
    ]

    if unavailable_products:
        messages.error(request, "Some items are no longer available: " + ", ".join(unavailable_products))
        return redirect("store:cart")

    with transaction.atomic():
        commissions_to_create = []
        for c in cart_items:
            effective_price_per_item = _effective_unit_price(c.product.price, c.coupon)
            line_total_for_order = c.quantity * effective_price_per_item
            order = Order.objects.create(
                user=user,
                product=c.product,
                quantity=c.quantity,
                size=c.size,
                price_at_purchase=effective_price_per_item,
                line_total=line_total_for_order,
            )

            if affiliate_profile:
                commission_amount = _calculate_commission_amount(line_total_for_order)
                if commission_amount > Decimal("0.00"):
                    commissions_to_create.append(
                        AffiliateCommission(
                            affiliate=affiliate_profile,
                            order=order,
                            customer=user,
                            rate=AFFILIATE_RATE_PERCENT,
                            amount=commission_amount,
                        )
                    )

        if commissions_to_create:
            AffiliateCommission.objects.bulk_create(commissions_to_create)

        Cart.objects.filter(id__in=[c.id for c in cart_items]).delete()

        click_id = request.session.get(AFFILIATE_CLICK_SESSION_KEY)
        if click_id:
            AffiliateClick.objects.filter(id=click_id).update(converted=True)

    messages.success(request, "Order placed successfully.")
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
