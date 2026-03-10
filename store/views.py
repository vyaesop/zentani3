import decimal
import json
import os
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.views import View

from store.models import Address, AffiliateClick, AffiliateCommission, AffiliateProfile, Brand, Cart, Category, Coupon, Order, Product, TelegramBotOrder
from store.telegram_notify import notify_bot_order_lead, notify_new_order, notify_new_signup, send_telegram_message

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
GUEST_SESSION_USER_ID_KEY = "guest_session_user_id"
TELEGRAM_ORDER_STATE_PREFIX = "telegram_order_state"
TELEGRAM_ORDER_STATE_TTL_SECONDS = 60 * 30


def _telegram_state_key(chat_id):
    return f"{TELEGRAM_ORDER_STATE_PREFIX}:{chat_id}"


def _set_telegram_order_state(chat_id, state):
    cache.set(_telegram_state_key(chat_id), state, TELEGRAM_ORDER_STATE_TTL_SECONDS)


def _get_telegram_order_state(chat_id):
    return cache.get(_telegram_state_key(chat_id))


def _clear_telegram_order_state(chat_id):
    cache.delete(_telegram_state_key(chat_id))


def _send_bot_text(chat_id, text):
    return send_telegram_message(text=text, chat_id=str(chat_id))


def _start_order_flow(chat_id, product, telegram_username):
    sizes = _parse_available_sizes(product)
    state = {
        "step": "size",
        "product_id": product.id,
        "telegram_username": telegram_username,
        "data": {},
        "sizes": sizes,
    }
    _set_telegram_order_state(chat_id, state)

    sizes_text = ", ".join(sizes) if sizes else "Any size (type what you need)"
    _send_bot_text(
        chat_id,
        (
            f"Order started for: {product.title}\n"
            f"Available sizes: {sizes_text}\n\n"
            "Please reply with your size."
        ),
    )


def _format_order_confirmation(product, state_data):
    qty = int(state_data.get("quantity", 1))
    unit_price = product.price
    total = unit_price * qty
    return (
        "Please confirm your order details:\n\n"
        f"Product: {product.title}\n"
        f"SKU: {product.sku}\n"
        f"Size: {state_data.get('size')}\n"
        f"Quantity: {qty}\n"
        f"Unit price: {unit_price:.2f} ETB\n"
        f"Estimated total: {total:.2f} ETB\n\n"
        f"Full name: {state_data.get('full_name')}\n"
        f"Phone: {state_data.get('phone')}\n"
        f"City: {state_data.get('city')}\n"
        f"Address: {state_data.get('address')}\n\n"
        "Reply YES to submit or NO to cancel."
    )


def _handle_telegram_order_reply(chat_id, message_text):
    state = _get_telegram_order_state(chat_id)
    if not state:
        return False

    product = Product.objects.filter(id=state.get("product_id"), is_active=True).first()
    if not product:
        _clear_telegram_order_state(chat_id)
        _send_bot_text(chat_id, "Sorry, this product is no longer available.")
        return True

    step = state.get("step")
    data = state.get("data", {})

    if step == "size":
        size = message_text.strip()
        allowed_sizes = state.get("sizes") or []
        if allowed_sizes and size not in allowed_sizes:
            _send_bot_text(chat_id, f"Please choose one of: {', '.join(allowed_sizes)}")
            return True
        data["size"] = size
        state["step"] = "quantity"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_bot_text(chat_id, "Great. Reply with quantity (number).")
        return True

    if step == "quantity":
        try:
            quantity = int(message_text.strip())
        except ValueError:
            _send_bot_text(chat_id, "Quantity must be a number. Please try again.")
            return True
        if quantity <= 0 or quantity > 50:
            _send_bot_text(chat_id, "Please enter a quantity between 1 and 50.")
            return True
        data["quantity"] = quantity
        state["step"] = "full_name"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_bot_text(chat_id, "Please enter your full name.")
        return True

    if step == "full_name":
        data["full_name"] = message_text.strip()
        state["step"] = "phone"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_bot_text(chat_id, "Please enter your phone number.")
        return True

    if step == "phone":
        data["phone"] = message_text.strip()
        state["step"] = "city"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_bot_text(chat_id, "Please enter your city.")
        return True

    if step == "city":
        data["city"] = message_text.strip()
        state["step"] = "address"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_bot_text(chat_id, "Please enter your delivery address.")
        return True

    if step == "address":
        data["address"] = message_text.strip()
        state["step"] = "confirm"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_bot_text(chat_id, _format_order_confirmation(product, data))
        return True

    if step == "confirm":
        normalized = message_text.strip().lower()
        if normalized in {"yes", "y"}:
            qty = int(data.get("quantity", 1))
            estimated_total = product.price * qty
            bot_order = TelegramBotOrder.objects.create(
                product=product,
                product_title=product.title,
                product_sku=product.sku,
                size=data.get("size", ""),
                quantity=qty,
                unit_price=product.price,
                estimated_total=estimated_total,
                customer_full_name=data.get("full_name", ""),
                customer_phone=data.get("phone", ""),
                customer_city=data.get("city", ""),
                customer_address=data.get("address", ""),
                telegram_chat_id=str(chat_id),
                telegram_username=state.get("telegram_username") or "",
            )
            notify_bot_order_lead(
                {
                    "order_ref": f"TG-{bot_order.id}",
                    "full_name": data.get("full_name"),
                    "phone": data.get("phone"),
                    "city": data.get("city"),
                    "address": data.get("address"),
                    "telegram_username": state.get("telegram_username") or "N/A",
                    "product_title": product.title,
                    "product_sku": product.sku,
                    "size": data.get("size"),
                    "quantity": qty,
                    "unit_price": product.price,
                    "estimated_total": estimated_total,
                    "requested_at": timezone.now().strftime("%Y-%m-%d %H:%M"),
                }
            )
            _clear_telegram_order_state(chat_id)
            _send_bot_text(
                chat_id,
                f"Thanks. Your order request was sent. Reference: TG-{bot_order.id}. We will contact you shortly.",
            )
            return True

        if normalized in {"no", "n", "cancel"}:
            _clear_telegram_order_state(chat_id)
            _send_bot_text(chat_id, "Order cancelled. You can start again from the channel post button.")
            return True

        _send_bot_text(chat_id, "Please reply YES to submit or NO to cancel.")
        return True

    return False


@csrf_exempt
def telegram_webhook(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    required_secret = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if required_secret:
        incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
        if incoming_secret and incoming_secret != required_secret:
            return HttpResponse(status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid-json"}, status=400)

    message = payload.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return JsonResponse({"ok": True})

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        start_payload = parts[1] if len(parts) > 1 else ""
        if start_payload.startswith("order_"):
            product_id = start_payload.replace("order_", "", 1)
            try:
                product_id = int(product_id)
            except ValueError:
                _send_bot_text(chat_id, "Invalid product link.")
                return JsonResponse({"ok": True})

            product = Product.objects.filter(id=product_id, is_active=True, is_sold_out=False).first()
            if not product:
                _send_bot_text(chat_id, "Sorry, this product is unavailable right now.")
                return JsonResponse({"ok": True})

            _start_order_flow(chat_id, product, from_user.get("username"))
            return JsonResponse({"ok": True})

        _send_bot_text(
            chat_id,
            "Welcome. To order, tap the Choose Size button from our channel post.",
        )
        return JsonResponse({"ok": True})

    if text:
        handled = _handle_telegram_order_reply(chat_id, text)
        if handled:
            return JsonResponse({"ok": True})

    _send_bot_text(
        chat_id,
        "Please use the channel's Choose Size button to start an order.",
    )
    return JsonResponse({"ok": True})


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


def _cart_owner_user(request):
    if request.user.is_authenticated:
        return request.user

    _ensure_session_key(request)
    guest_user_id = request.session.get(GUEST_SESSION_USER_ID_KEY)
    if guest_user_id:
        existing = User.objects.filter(id=guest_user_id).first()
        if existing:
            return existing

    username = f"guest-{request.session.session_key}"
    user, created = User.objects.get_or_create(username=username)
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])

    request.session[GUEST_SESSION_USER_ID_KEY] = user.id
    return user


def _apply_guest_checkout_profile(guest_user, full_name, phone, city, address):
    clean_name = (full_name or "").strip()
    parts = clean_name.split(None, 1)
    guest_user.first_name = parts[0] if parts else ""
    guest_user.last_name = parts[1] if len(parts) > 1 else ""
    guest_user.save(update_fields=["first_name", "last_name"])

    return Address.objects.create(
        user=guest_user,
        address=(address or "").strip(),
        city=(city or "").strip(),
        phone=(phone or "").strip(),
    )


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
            with transaction.atomic():
                user = form.save()
                signup_address = Address.objects.create(
                    user=user,
                    address=form.cleaned_data.get("address"),
                    city=form.cleaned_data.get("city"),
                    phone=form.cleaned_data.get("username"),
                )

            # Re-authenticate so Django can attach the correct backend when multiple backends are configured.
            authenticated_user = authenticate(
                request,
                username=form.cleaned_data.get("username"),
                password=form.cleaned_data.get("password1"),
            )
            if authenticated_user is not None:
                login(request, authenticated_user)

            notify_new_signup(user=user, address=signup_address)
            messages.success(request, "Congratulations! Registration Successful!")
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


def add_to_cart(request):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _json(message, ok=True, status=200):
        owner_user = _cart_owner_user(request)
        payload = {
            "ok": ok,
            "message": message,
            "cart_items_count": Cart.objects.filter(user=owner_user).count(),
        }
        return JsonResponse(payload, status=status)

    if request.method != "POST":
        if is_ajax:
            return _json("Please use the add-to-cart button to add an item.", ok=False, status=405)
        messages.warning(request, "Please use the add-to-cart button to add an item.")
        return redirect("store:home")

    user = _cart_owner_user(request)
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


def cart(request):
    user = _cart_owner_user(request)
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
        "guest_checkout": not request.user.is_authenticated,
    }
    return render(request, "store/cart.html", context)


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

        cart_products = Cart.objects.filter(user=_cart_owner_user(request))
        if not cart_products.exists():
            messages.warning(request, "Your cart is empty.")
            return redirect("store:cart")

        cart_products.update(coupon=coupon)
        messages.success(request, "Coupon applied successfully.")

        return redirect("store:cart")


def remove_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    c = get_object_or_404(Cart, id=cart_id, user=_cart_owner_user(request))
    c.delete()
    messages.success(request, "Product removed from cart.")
    return redirect("store:cart")


def plus_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    cp = get_object_or_404(Cart.objects.select_related("product"), id=cart_id, user=_cart_owner_user(request))
    if not cp.product.is_active or cp.product.is_sold_out:
        messages.warning(request, f"{cp.product.title} is no longer available.")
        return redirect("store:cart")

    cp.quantity += 1
    cp.save(update_fields=["quantity", "updated_at"])
    return redirect("store:cart")


def minus_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    cp = get_object_or_404(Cart, id=cart_id, user=_cart_owner_user(request))
    if cp.quantity == 1:
        cp.delete()
    else:
        cp.quantity -= 1
        cp.save(update_fields=["quantity", "updated_at"])
    return redirect("store:cart")


def checkout(request):
    if request.method != "POST":
        messages.warning(request, "Invalid checkout request.")
        return redirect("store:cart")

    user = _cart_owner_user(request)
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

    order_count = 0
    order_total = Decimal("0.00")
    customer_address = Address.objects.filter(user=user).order_by("-id").first()
    guest_checkout_address = None
    created_order_ids = []
    order_lines = []

    if not request.user.is_authenticated:
        full_name = (request.POST.get("full_name") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        city = (request.POST.get("city") or "").strip()
        address = (request.POST.get("address") or "").strip()

        if not all([full_name, phone, city, address]):
            messages.error(request, "Please fill name, phone, city, and address to complete guest checkout.")
            return redirect("store:cart")

        guest_checkout_address = _apply_guest_checkout_profile(
            guest_user=user,
            full_name=full_name,
            phone=phone,
            city=city,
            address=address,
        )

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
            order_count += 1
            order_total += line_total_for_order
            created_order_ids.append(order.id)
            order_lines.append(
                {
                    "title": c.product.title,
                    "sku": c.product.sku,
                    "quantity": c.quantity,
                    "size": c.size or "N/A",
                    "unit_price": f"{effective_price_per_item:.2f}",
                    "line_total": f"{line_total_for_order:.2f}",
                    "coupon": c.coupon.code if c.coupon else "N/A",
                    "status": order.status,
                }
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

    notify_new_order(
        user=user,
        order_count=order_count,
        order_total=order_total,
        address=guest_checkout_address or customer_address,
        order_lines=order_lines,
        order_ids=created_order_ids,
    )

    messages.success(request, "Order placed successfully.")
    if request.user.is_authenticated:
        return redirect("store:orders")
    return redirect("store:home")


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
