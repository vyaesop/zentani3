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
from django.db.models import Avg, Case, Count, IntegerField, Max, Min, Q, Sum, Value, When
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

from store.models import (
    STATUS_CHOICES,
    Address,
    AffiliateClick,
    AffiliateCommission,
    AffiliateProfile,
    Brand,
    Cart,
    Category,
    Coupon,
    Order,
    Product,
    ProductReview,
    ProductSizeStock,
    RestockRequest,
    TelegramBotOrder,
    Wishlist,
)
from store.telegram_notify import (
    notify_bot_order_lead,
    notify_new_order,
    notify_new_signup,
    send_product_gallery_to_customer,
    send_admin_alert_message,
    send_customer_bot_message,
)

from .forms import AddressForm, ProductReviewForm, RegistrationForm, RestockRequestForm


PRODUCT_LIST_FIELDS = (
    "id",
    "slug",
    "title",
    "price",
    "product_image",
    "available_sizes",
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
COLLECTION_PAGE_SIZE = 24
RECENTLY_VIEWED_SESSION_KEY = "recently_viewed_product_ids"
COLLECTION_SORT_OPTIONS = (
    ("newest", "Newest first", "-created_at"),
    ("price-asc", "Price: Low to High", "price"),
    ("price-desc", "Price: High to Low", "-price"),
    ("name-asc", "Name: A-Z", "title"),
)
SIZE_DISPLAY_ORDER = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL")
ADDIS_FREE_SHIPPING_THRESHOLD = Decimal("3500.00")
ADDIS_SHIPPING_FEE = Decimal("80.00")
OUTSIDE_ADDIS_SHIPPING_FEE = Decimal("180.00")
ORDER_STATUS_SEQUENCE = ["Pending", "Accepted", "Packed", "On The Way", "Delivered"]
ORDER_STATUS_COPY = {
    "Pending": "We received your order and it is waiting for confirmation.",
    "Accepted": "Your order has been confirmed by the store.",
    "Packed": "Your items are being prepared for dispatch.",
    "On The Way": "Your order is currently out for delivery.",
    "Delivered": "The order was delivered successfully.",
    "Cancelled": "This order was cancelled before delivery.",
}


def _telegram_state_key(chat_id):
    return f"{TELEGRAM_ORDER_STATE_PREFIX}:{chat_id}"


def _set_telegram_order_state(chat_id, state):
    cache.set(_telegram_state_key(chat_id), state, TELEGRAM_ORDER_STATE_TTL_SECONDS)


def _get_telegram_order_state(chat_id):
    return cache.get(_telegram_state_key(chat_id))


def _clear_telegram_order_state(chat_id):
    cache.delete(_telegram_state_key(chat_id))


def _send_customer_bot_text(chat_id, text):
    return send_customer_bot_message(text=text, chat_id=str(chat_id))


def _send_admin_bot_text(chat_id, text):
    return send_admin_alert_message(text=text, chat_id=str(chat_id))


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

    send_product_gallery_to_customer(product, str(chat_id))
    sizes_text = ", ".join(sizes) if sizes else "Any size (type what you need)"
    _send_customer_bot_text(
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
        _send_customer_bot_text(chat_id, "Sorry, this product is no longer available.")
        return True

    step = state.get("step")
    data = state.get("data", {})

    if step == "size":
        size = message_text.strip()
        allowed_sizes = state.get("sizes") or []
        if allowed_sizes and size not in allowed_sizes:
            _send_customer_bot_text(chat_id, f"Please choose one of: {', '.join(allowed_sizes)}")
            return True
        data["size"] = size
        state["step"] = "quantity"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_customer_bot_text(chat_id, "Great. Reply with quantity (number).")
        return True

    if step == "quantity":
        try:
            quantity = int(message_text.strip())
        except ValueError:
            _send_customer_bot_text(chat_id, "Quantity must be a number. Please try again.")
            return True
        if quantity <= 0 or quantity > 50:
            _send_customer_bot_text(chat_id, "Please enter a quantity between 1 and 50.")
            return True
        data["quantity"] = quantity
        state["step"] = "full_name"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_customer_bot_text(chat_id, "Please enter your full name.")
        return True

    if step == "full_name":
        data["full_name"] = message_text.strip()
        state["step"] = "phone"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_customer_bot_text(chat_id, "Please enter your phone number.")
        return True

    if step == "phone":
        data["phone"] = message_text.strip()
        state["step"] = "city"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_customer_bot_text(chat_id, "Please enter your city.")
        return True

    if step == "city":
        data["city"] = message_text.strip()
        state["step"] = "address"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_customer_bot_text(chat_id, "Please enter your delivery address.")
        return True

    if step == "address":
        data["address"] = message_text.strip()
        state["step"] = "confirm"
        state["data"] = data
        _set_telegram_order_state(chat_id, state)
        _send_customer_bot_text(chat_id, _format_order_confirmation(product, data))
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
            _send_customer_bot_text(
                chat_id,
                f"Thanks. Your order request was sent. Reference: TG-{bot_order.id}. We will contact you shortly.",
            )
            return True

        if normalized in {"no", "n", "cancel"}:
            _clear_telegram_order_state(chat_id)
            _send_customer_bot_text(chat_id, "Order cancelled. You can start again from the channel post button.")
            return True

        _send_customer_bot_text(chat_id, "Please reply YES to submit or NO to cancel.")
        return True

    return False


def _accepted_webhook_secrets(*env_var_names):
    secrets = []
    for env_var_name in env_var_names:
        value = (os.getenv(env_var_name) or "").strip()
        if value and value not in secrets:
            secrets.append(value)
    return secrets


def _validate_telegram_webhook_secret(request, *env_var_names):
    accepted_secrets = _accepted_webhook_secrets(*env_var_names)
    if not accepted_secrets:
        return True

    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
    if not incoming_secret:
        return True
    return incoming_secret in accepted_secrets


def _telegram_message_context(payload):
    message = payload.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    return {
        "message": message,
        "text": text,
        "chat_id": chat.get("id"),
        "from_user": from_user,
    }


def _customer_bot_welcome_text():
    return (
        "Welcome to Zentanee Orders.\n\n"
        "Use the Choose Size button from our Telegram channel post to start an order."
    )


def _admin_bot_welcome_text():
    return (
        "This is the Zentanee admin alert bot.\n\n"
        "It is used for internal signup and order notifications, not customer shopping.\n"
        "For product orders, use @zentanee_order_bot."
    )


def _handle_customer_bot_start(chat_id, start_payload, username):
    if start_payload.startswith("order_"):
        product_id = start_payload.replace("order_", "", 1)
        try:
            product_id = int(product_id)
        except ValueError:
            _send_customer_bot_text(chat_id, "Invalid product link.")
            return

        product = Product.objects.filter(id=product_id, is_active=True, is_sold_out=False).first()
        if not product:
            _send_customer_bot_text(chat_id, "Sorry, this product is unavailable right now.")
            return

        _start_order_flow(chat_id, product, username)
        return

    _send_customer_bot_text(chat_id, _customer_bot_welcome_text())


@csrf_exempt
def customer_telegram_webhook(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    if not _validate_telegram_webhook_secret(
        request,
        "TELEGRAM_CUSTOMER_WEBHOOK_SECRET",
        "TELEGRAM_WEBHOOK_SECRET",
    ):
        return HttpResponse(status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid-json"}, status=400)

    context = _telegram_message_context(payload)
    text = context["text"]
    chat_id = context["chat_id"]
    from_user = context["from_user"]

    if not chat_id:
        return JsonResponse({"ok": True})

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        start_payload = parts[1] if len(parts) > 1 else ""
        _handle_customer_bot_start(chat_id, start_payload, from_user.get("username"))
        return JsonResponse({"ok": True})

    if text:
        handled = _handle_telegram_order_reply(chat_id, text)
        if handled:
            return JsonResponse({"ok": True})

    _send_customer_bot_text(
        chat_id,
        "Please use the channel's Choose Size button to start an order.",
    )
    return JsonResponse({"ok": True})


@csrf_exempt
def admin_telegram_webhook(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    if not _validate_telegram_webhook_secret(
        request,
        "TELEGRAM_ADMIN_WEBHOOK_SECRET",
        "TELEGRAM_WEBHOOK_SECRET",
    ):
        return HttpResponse(status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid-json"}, status=400)

    context = _telegram_message_context(payload)
    text = context["text"]
    chat_id = context["chat_id"]

    if not chat_id:
        return JsonResponse({"ok": True})

    if text.startswith("/start") or text.startswith("/help"):
        _send_admin_bot_text(chat_id, _admin_bot_welcome_text())
        return JsonResponse({"ok": True})

    _send_admin_bot_text(chat_id, _admin_bot_welcome_text())
    return JsonResponse({"ok": True})


def telegram_webhook(request):
    # Legacy webhook path kept for backward compatibility with the customer bot.
    return customer_telegram_webhook(request)


def _recently_viewed_product_ids(request):
    return [int(product_id) for product_id in request.session.get(RECENTLY_VIEWED_SESSION_KEY, []) if str(product_id).isdigit()]


def _push_recently_viewed_product(request, product):
    existing_ids = [product_id for product_id in _recently_viewed_product_ids(request) if product_id != product.id]
    request.session[RECENTLY_VIEWED_SESSION_KEY] = [product.id, *existing_ids][:8]
    request.session.modified = True


def _recently_viewed_products(request, exclude_id=None, limit=4):
    product_ids = [product_id for product_id in _recently_viewed_product_ids(request) if product_id != exclude_id]
    if not product_ids:
        return []

    products_by_id = {
        product.id: product
        for product in Product.objects.filter(id__in=product_ids, is_active=True)
        .select_related("category", "brand")
        .only(*PRODUCT_LIST_FIELDS)
    }
    ordered_products = [products_by_id[product_id] for product_id in product_ids if product_id in products_by_id]
    return ordered_products[:limit]


def _saved_product_ids_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(Wishlist.objects.filter(user=user).values_list("product_id", flat=True))


def _search_discovery_context(request):
    return {
        "search_help_categories": Category.objects.filter(is_active=True).only("id", "title", "slug").order_by("title")[:6],
        "search_help_brands": Brand.objects.filter(is_active=True).only("id", "title", "slug").order_by("title")[:6],
        "recently_viewed_products": _recently_viewed_products(request, limit=4),
    }


def _build_product_detail_context(request, product):
    related_products = (
        Product.objects.filter(is_active=True, category=product.category)
        .exclude(id=product.id)
        .select_related("category", "brand")
        .only(*PRODUCT_LIST_FIELDS)[:4]
    )
    p_image = product.p_images.only("id", "image").all()
    size_options = _product_size_options(product)
    available_sizes_list = [option["size"] for option in size_options]
    default_selected_size = next((option["size"] for option in size_options if option["available"]), "")
    reviews = list(
        ProductReview.objects.filter(product=product)
        .select_related("user")
        .only("id", "rating", "title", "comment", "created_at", "user__first_name", "user__last_name", "user__username")[:6]
    )
    review_summary = ProductReview.objects.filter(product=product).aggregate(
        average_rating=Avg("rating"),
        review_count=Count("id"),
    )
    saved_product_ids = _saved_product_ids_for_user(request.user)
    existing_restock_request = None
    restock_initial = {}
    if request.user.is_authenticated:
        restock_initial["email"] = request.user.email or ""
        if product.is_sold_out:
            existing_restock_request = RestockRequest.objects.filter(product=product, user=request.user).first()

    return {
        "product": product,
        "related_products": related_products,
        "p_image": p_image,
        "available_sizes": available_sizes_list,
        "size_options": size_options,
        "default_selected_size": default_selected_size,
        "reviews": reviews,
        "review_summary": review_summary,
        "review_form": ProductReviewForm(),
        "restock_form": RestockRequestForm(initial=restock_initial),
        "existing_restock_request": existing_restock_request,
        "saved_product_ids": saved_product_ids,
        "is_saved_product": product.id in saved_product_ids,
        "recently_viewed_products": _recently_viewed_products(request, exclude_id=product.id),
        "product_stock_message": _product_stock_message(product, size_value=default_selected_size or None),
        "product_delivery_note": product.delivery_note or "Addis delivery usually lands within 1-3 days after confirmation.",
        "product_return_note": product.return_note or "If there is an issue with the order, contact support quickly so we can help.",
        "is_cash_on_delivery_only": True,
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


def _safe_redirect_url_with_query(request, fallback_url):
    resolved = _safe_redirect_url(request, fallback_url)
    if resolved.startswith("/"):
        return resolved
    try:
        return reverse(resolved)
    except Exception:
        return reverse(fallback_url)


def _latest_saved_address(user):
    if not getattr(user, "is_authenticated", False):
        return None
    return Address.objects.filter(user=user).order_by("-id").first()


def _address_entry_url(next_url_name="store:profile"):
    return f"{reverse('store:add-address')}?next={reverse(next_url_name)}"


def _build_cart_flow_status(request, cart_products, latest_address):
    if not cart_products:
        return {
            "tone": "muted",
            "eyebrow": "Cart status",
            "title": "Your cart is empty",
            "message": "Browse products and add your favorites before moving to delivery and order confirmation.",
            "primary_label": "Start shopping",
            "primary_url": reverse("store:home"),
        }

    if not request.user.is_authenticated:
        return {
            "tone": "info",
            "eyebrow": "Guest checkout",
            "title": "You can place this order right here",
            "message": "Review your items, fill in your full name, phone number, city, and delivery address below, then submit the order.",
            "meta": "If you already have an account, sign in first to reuse your saved address and view your order history.",
            "primary_label": "Sign in",
            "primary_url": f"{reverse('store:login')}?next={reverse('store:cart')}",
            "secondary_label": "Create account",
            "secondary_url": f"{reverse('store:register')}?next={reverse('store:cart')}",
            "checkout_ready": True,
            "checkout_label": "Place Order as Guest",
        }

    if latest_address:
        return {
            "tone": "success",
            "eyebrow": "Ready to order",
            "title": "Your cart and delivery address are set",
            "message": "Review the cart summary and place the order when you are ready. Your latest saved address will be used for delivery.",
            "meta": f"Current delivery city: {latest_address.city}. Update it from your account if needed.",
            "primary_label": "Manage addresses",
            "primary_url": reverse("store:profile"),
            "checkout_ready": True,
            "checkout_label": "Place Order",
        }

    return {
        "tone": "warning",
        "eyebrow": "Action needed",
        "title": "Add a delivery address before placing your order",
        "message": "Your account is signed in, but there is no saved delivery address yet. Add one first, then come back here to finish checkout.",
        "primary_label": "Add address",
        "primary_url": _address_entry_url("store:cart"),
        "secondary_label": "Go to account",
        "secondary_url": reverse("store:profile"),
        "checkout_ready": False,
        "checkout_label": "Add Address to Continue",
    }


def _build_profile_flow_status(addresses, orders):
    if not addresses.exists():
        return {
            "tone": "warning",
            "eyebrow": "Account setup",
            "title": "Add your delivery address",
            "message": "A saved address makes checkout faster and prevents order delays.",
            "primary_label": "Add address",
            "primary_url": reverse("store:add-address"),
        }

    if not orders.exists():
        return {
            "tone": "info",
            "eyebrow": "Next step",
            "title": "Your account is ready for checkout",
            "message": "Start shopping, add items to your cart, and place your first order when ready.",
            "primary_label": "Browse products",
            "primary_url": reverse("store:all-products"),
            "secondary_label": "Open cart",
            "secondary_url": reverse("store:cart"),
        }

    return {
        "tone": "success",
        "eyebrow": "Account status",
        "title": "Your account is active and ready",
        "message": "Manage addresses here and track your order progress from the orders section.",
        "primary_label": "View orders",
        "primary_url": reverse("store:orders"),
        "secondary_label": "Manage addresses",
        "secondary_url": reverse("store:profile"),
    }


def _build_order_flow_status(orders_queryset):
    if not orders_queryset.exists():
        return {
            "tone": "info",
            "eyebrow": "Orders",
            "title": "No orders yet",
            "message": "Once you place an order, this page will show its status and item details.",
            "primary_label": "Start shopping",
            "primary_url": reverse("store:home"),
        }

    active_count = orders_queryset.exclude(status__in=["Delivered", "Cancelled"]).count()
    latest_order = orders_queryset.order_by("-ordered_date").first()
    return {
        "tone": "success" if active_count else "info",
        "eyebrow": "Order tracking",
        "title": "Track your order progress here",
        "message": "Pending means we received it, Accepted means confirmed, Packed means preparing, On The Way means out for delivery, and Delivered means completed.",
        "meta": f"Latest order: #{latest_order.id} on {latest_order.ordered_date.strftime('%Y-%m-%d %H:%M')}.",
        "primary_label": "Continue shopping",
        "primary_url": reverse("store:home"),
    }


def _order_status_summary(orders_queryset):
    return [
        {"label": label, "count": orders_queryset.filter(status=value).count()}
        for value, label in STATUS_CHOICES
    ]


def _parse_available_sizes(product):
    if not product.available_sizes:
        return []
    return [size.strip() for size in product.available_sizes.split(",") if size.strip()]


def _size_inventory_queryset(product):
    return ProductSizeStock.objects.filter(product=product)


def _size_inventory_map(product):
    return {
        item.size.strip(): item.quantity
        for item in _size_inventory_queryset(product).only("size", "quantity")
        if item.size and item.size.strip()
    }


def _product_size_options(product):
    inventory = _size_inventory_map(product)
    if inventory:
        return [
            {
                "size": size,
                "quantity": quantity,
                "available": quantity > 0,
            }
            for size, quantity in sorted(inventory.items(), key=lambda item: _size_sort_key(item[0]))
        ]

    return [
        {
            "size": size,
            "quantity": None,
            "available": not product.is_sold_out,
        }
        for size in _parse_available_sizes(product)
    ]


def _product_size_stock(product, size_value=None):
    inventory = _size_inventory_map(product)
    if inventory:
        if size_value:
            return inventory.get(size_value, 0)
        return sum(inventory.values())

    return product.stock_quantity


def _product_can_fulfill_quantity(product, requested_quantity, size_value=None):
    if requested_quantity <= 0:
        return False
    available_quantity = _product_size_stock(product, size_value=size_value)
    if available_quantity <= 0:
        return False
    return requested_quantity <= available_quantity


def _product_stock_message(product, size_value=None):
    available_quantity = _product_size_stock(product, size_value=size_value)
    if product.is_sold_out or available_quantity <= 0:
        return "Currently sold out"
    if available_quantity <= 3:
        return f"Only {available_quantity} left"
    return f"{available_quantity} in stock"


def _normalized_multi_param(values):
    seen = []
    for value in values:
        normalized = (value or "").strip()
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def _parse_decimal_param(value):
    normalized = (value or "").strip()
    if not normalized:
        return None

    try:
        return Decimal(normalized)
    except decimal.InvalidOperation:
        return None


def _size_sort_key(size_value):
    normalized = size_value.upper()
    if normalized in SIZE_DISPLAY_ORDER:
        return (0, SIZE_DISPLAY_ORDER.index(normalized))
    return (1, normalized)


def _collection_sort_choices(current_sort, include_relevance=False):
    options = list(COLLECTION_SORT_OPTIONS)
    if include_relevance:
        options = [("relevance", "Most relevant", "relevance"), *options]

    return [
        {
            "value": value,
            "label": label,
            "selected": value == current_sort,
        }
        for value, label, _ in options
    ]


def _querydict_pairs(querydict):
    pairs = []
    for key, values in querydict.lists():
        for value in values:
            pairs.append((key, value))
    return pairs


def _querystring_without(request, *keys_to_remove):
    params = request.GET.copy()
    for key in keys_to_remove:
        params.pop(key, None)
    encoded = params.urlencode()
    return f"{encoded}&" if encoded else ""


def _url_with_query(path, params):
    encoded = params.urlencode()
    if not encoded:
        return path
    return f"{path}?{encoded}"


def _browse_text_query(current_query):
    if not current_query:
        return Q()

    return (
        Q(title__icontains=current_query)
        | Q(short_description__icontains=current_query)
        | Q(detail_description__icontains=current_query)
        | Q(category__title__icontains=current_query)
        | Q(brand__title__icontains=current_query)
        | Q(sku__icontains=current_query)
        | Q(material__icontains=current_query)
        | Q(color__icontains=current_query)
    )


def _search_rank_expression(current_query):
    if not current_query:
        return Value(0, output_field=IntegerField())

    return Case(
        When(title__iexact=current_query, then=Value(90)),
        When(title__istartswith=current_query, then=Value(75)),
        When(brand__title__iexact=current_query, then=Value(65)),
        When(category__title__iexact=current_query, then=Value(60)),
        When(title__icontains=current_query, then=Value(50)),
        When(short_description__icontains=current_query, then=Value(35)),
        When(detail_description__icontains=current_query, then=Value(25)),
        When(material__icontains=current_query, then=Value(18)),
        When(color__icontains=current_query, then=Value(15)),
        default=Value(0),
        output_field=IntegerField(),
    )


def _normalized_city(value):
    return (value or "").strip().lower()


def _shipping_amount_for_city(city, subtotal):
    normalized_city = _normalized_city(city)
    if not normalized_city:
        return Decimal("0.00")
    if "addis" in normalized_city:
        if subtotal >= ADDIS_FREE_SHIPPING_THRESHOLD:
            return Decimal("0.00")
        return ADDIS_SHIPPING_FEE
    return OUTSIDE_ADDIS_SHIPPING_FEE


def _shipping_note_for_city(city, subtotal):
    normalized_city = _normalized_city(city)
    if not normalized_city:
        return f"Shipping is calculated once the delivery city is known. Addis starts at {ADDIS_SHIPPING_FEE:.0f} ETB."
    if "addis" in normalized_city:
        if subtotal >= ADDIS_FREE_SHIPPING_THRESHOLD:
            return "Addis delivery is free for this order total."
        shortfall = (ADDIS_FREE_SHIPPING_THRESHOLD - subtotal).quantize(Decimal("0.01"))
        return f"Addis delivery is {ADDIS_SHIPPING_FEE:.0f} ETB. Add {shortfall:.2f} ETB more for free delivery."
    return f"Outside Addis delivery is {OUTSIDE_ADDIS_SHIPPING_FEE:.0f} ETB."


def _order_status_timeline(status_value):
    if status_value == "Cancelled":
        return [
            {"label": label, "state": "completed" if label == "Pending" else ("cancelled" if label == "Cancelled" else "upcoming")}
            for label in ["Pending", "Cancelled"]
        ]

    try:
        current_index = ORDER_STATUS_SEQUENCE.index(status_value)
    except ValueError:
        current_index = 0

    timeline = []
    for index, label in enumerate(ORDER_STATUS_SEQUENCE):
        if index < current_index:
            state = "completed"
        elif index == current_index:
            state = "current"
        else:
            state = "upcoming"
        timeline.append({"label": label, "state": state})
    return timeline


def _can_cancel_order(order):
    return order.status in {"Pending", "Accepted"}


def _collection_size_options(queryset):
    sizes = set()
    for raw_sizes in queryset.values_list("available_sizes", flat=True):
        if not raw_sizes:
            continue
        for size in raw_sizes.split(","):
            normalized = size.strip()
            if normalized:
                sizes.add(normalized)
    for size_value in ProductSizeStock.objects.filter(product__in=queryset).values_list("size", flat=True):
        normalized = (size_value or "").strip()
        if normalized:
            sizes.add(normalized)
    return sorted(sizes, key=_size_sort_key)


def _build_collection_state(
    request,
    base_queryset,
    *,
    form_action=None,
    show_category_filters=True,
    show_brand_filters=True,
    include_relevance_sort=False,
):
    current_query = (request.GET.get("q") or "").strip()
    selected_categories = (
        _normalized_multi_param(request.GET.getlist("category")) if show_category_filters else []
    )
    selected_brands = (
        _normalized_multi_param(request.GET.getlist("brand")) if show_brand_filters else []
    )
    selected_sizes = _normalized_multi_param(request.GET.getlist("size"))
    availability = "in-stock" if request.GET.get("availability") == "in-stock" else ""
    default_sort = "relevance" if include_relevance_sort and current_query else "newest"
    current_sort = (request.GET.get("sort") or default_sort).strip()
    sort_mapping = {value: ordering for value, _, ordering in COLLECTION_SORT_OPTIONS}
    if include_relevance_sort:
        sort_mapping["relevance"] = "relevance"
    sort_ordering = sort_mapping.get(current_sort, sort_mapping[default_sort])
    if current_sort not in sort_mapping:
        current_sort = default_sort

    query_scoped_queryset = base_queryset
    if current_query:
        query_scoped_queryset = query_scoped_queryset.filter(_browse_text_query(current_query))

    price_bounds = query_scoped_queryset.aggregate(min_price=Min("price"), max_price=Max("price"))
    min_price_bound = price_bounds.get("min_price")
    max_price_bound = price_bounds.get("max_price")
    current_min_price = _parse_decimal_param(request.GET.get("min_price"))
    current_max_price = _parse_decimal_param(request.GET.get("max_price"))

    filtered_queryset = query_scoped_queryset
    if selected_categories:
        filtered_queryset = filtered_queryset.filter(category__slug__in=selected_categories)
    if selected_brands:
        filtered_queryset = filtered_queryset.filter(brand__slug__in=selected_brands)
    if selected_sizes:
        size_query = Q()
        for size in selected_sizes:
            size_query |= Q(available_sizes__icontains=size) | Q(size_inventory__size__iexact=size, size_inventory__quantity__gt=0)
        filtered_queryset = filtered_queryset.filter(size_query)
    if availability:
        filtered_queryset = filtered_queryset.filter(is_sold_out=False)
    if current_min_price is not None:
        filtered_queryset = filtered_queryset.filter(price__gte=current_min_price)
    if current_max_price is not None:
        filtered_queryset = filtered_queryset.filter(price__lte=current_max_price)

    filtered_queryset = filtered_queryset.distinct()
    if sort_ordering == "relevance":
        filtered_queryset = filtered_queryset.annotate(search_rank=_search_rank_expression(current_query)).order_by("-search_rank", "-created_at", "-id")
    else:
        filtered_queryset = filtered_queryset.order_by(sort_ordering, "-id")

    paginator = Paginator(filtered_queryset, COLLECTION_PAGE_SIZE)
    paged_products = paginator.get_page(request.GET.get("page"))
    page_numbers = paginator.get_elided_page_range(
        number=paged_products.number,
        on_each_side=1,
        on_ends=1,
    )

    result_summary = (
        f"Showing {paged_products.start_index()}-{paged_products.end_index()} of {paginator.count}"
        if paginator.count
        else "No products match this view yet"
    )

    category_label_map = dict(
        Category.objects.filter(slug__in=selected_categories).values_list("slug", "title")
    )
    brand_label_map = dict(
        Brand.objects.filter(slug__in=selected_brands).values_list("slug", "title")
    )

    active_filters = []
    if selected_categories:
        active_filters.extend(
            [f"Collection: {category_label_map.get(value, value)}" for value in selected_categories]
        )
    if selected_brands:
        active_filters.extend(
            [f"Brand: {brand_label_map.get(value, value)}" for value in selected_brands]
        )
    if selected_sizes:
        active_filters.extend([f"Size: {value}" for value in selected_sizes])
    if availability:
        active_filters.append("In stock only")
    if current_min_price is not None:
        active_filters.append(f"Min {current_min_price:.2f} ETB")
    if current_max_price is not None:
        active_filters.append(f"Max {current_max_price:.2f} ETB")
    if current_sort != "newest":
        selected_sort_label = next(
            label for value, label, _ in COLLECTION_SORT_OPTIONS if value == current_sort
        )
        active_filters.append(f"Sort: {selected_sort_label}")

    reset_params = request.GET.copy()
    for key in ("category", "brand", "size", "availability", "min_price", "max_price", "sort", "page"):
        reset_params.pop(key, None)

    sort_hidden_params = request.GET.copy()
    sort_hidden_params.pop("sort", None)
    sort_hidden_params.pop("page", None)

    return {
        "products": paged_products,
        "product_count": paginator.count,
        "page_numbers": page_numbers,
        "saved_product_ids": _saved_product_ids_for_user(request.user),
        "browse_state": {
            "form_action": form_action or request.path,
            "sort_options": _collection_sort_choices(current_sort, include_relevance=include_relevance_sort and bool(current_query)),
            "sort_hidden_fields": _querydict_pairs(sort_hidden_params),
            "page_query": _querystring_without(request, "page"),
            "current_query": current_query,
            "current_min_price": f"{current_min_price:.2f}" if current_min_price is not None else "",
            "current_max_price": f"{current_max_price:.2f}" if current_max_price is not None else "",
            "min_price_bound": f"{min_price_bound:.2f}" if min_price_bound is not None else "",
            "max_price_bound": f"{max_price_bound:.2f}" if max_price_bound is not None else "",
            "show_category_filters": show_category_filters,
            "show_brand_filters": show_brand_filters,
            "selected_categories": selected_categories,
            "selected_brands": selected_brands,
            "selected_sizes": selected_sizes,
            "availability": availability,
            "size_options": _collection_size_options(query_scoped_queryset),
            "result_summary": result_summary,
            "active_filters": active_filters,
            "reset_filters_url": _url_with_query(form_action or request.path, reset_params),
        },
    }


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
    latest_products = Product.objects.filter(is_active=True).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS).order_by("-created_at")[:8]
    top_selling_ids = list(
        Order.objects.values("product_id")
        .annotate(total_quantity=Sum("quantity"))
        .order_by("-total_quantity", "-product_id")
        .values_list("product_id", flat=True)[:8]
    )
    top_selling_lookup = {
        product.id: product
        for product in Product.objects.filter(id__in=top_selling_ids, is_active=True)
        .select_related("category", "brand")
        .only(*PRODUCT_LIST_FIELDS)
    }
    top_selling_products = [top_selling_lookup[product_id] for product_id in top_selling_ids if product_id in top_selling_lookup]
    context = {
        "categories": categories,
        "products": products,
        "brands": brands,
        "latest_products": latest_products,
        "top_selling_products": top_selling_products,
        "recently_viewed_products": _recently_viewed_products(request, limit=4),
        "saved_product_ids": _saved_product_ids_for_user(request.user),
    }
    return render(request, "store/index.html", context)


def detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "brand"),
        slug=slug,
    )
    _push_recently_viewed_product(request, product)
    context = _build_product_detail_context(request, product)
    return render(request, "store/detail.html", context)


@login_required
def toggle_wishlist(request, product_id):
    if request.method != "POST":
        messages.warning(request, "Invalid save action.")
        return redirect("store:product-detail", slug=get_object_or_404(Product, id=product_id).slug)

    product = get_object_or_404(Product, id=product_id, is_active=True)
    wishlist_entry = Wishlist.objects.filter(user=request.user, product=product).first()

    if wishlist_entry:
        wishlist_entry.delete()
        saved = False
        message = f"Removed {product.title} from your saved items."
    else:
        Wishlist.objects.create(user=request.user, product=product)
        saved = True
        message = f"Saved {product.title} for later."

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "saved": saved, "message": message})

    messages.success(request, message)
    return redirect(request.POST.get("next") or reverse("store:product-detail", kwargs={"slug": product.slug}))


@login_required
def submit_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    if request.method != "POST":
        return redirect("store:product-detail", slug=product.slug)

    form = ProductReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please complete the review fields before submitting.")
        return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#reviews")

    ProductReview.objects.update_or_create(
        user=request.user,
        product=product,
        defaults=form.cleaned_data,
    )
    messages.success(request, "Your review has been saved.")
    return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#reviews")


def request_restock(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    if request.method != "POST":
        return redirect("store:product-detail", slug=product.slug)

    form = RestockRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a valid email address to join the restock list.")
        return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#restock")

    payload = form.cleaned_data
    defaults = {}
    if request.user.is_authenticated:
        defaults["user"] = request.user
    restock_request, created = RestockRequest.objects.get_or_create(
        product=product,
        email=payload["email"],
        size=payload["size"],
        defaults=defaults,
    )
    if not created and request.user.is_authenticated and restock_request.user_id is None:
        restock_request.user = request.user
        restock_request.save(update_fields=["user"])

    if created:
        messages.success(request, "You are on the restock list for this product.")
    else:
        messages.info(request, "You are already on the restock list for this product.")
    return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#restock")


def search_view(request):
    base_products = Product.objects.filter(is_active=True).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:search"),
        include_relevance_sort=True,
    )
    context["query"] = context["browse_state"]["current_query"]
    context.update(_search_discovery_context(request))
    return render(request, "store/search.html", context)


def search_suggestions(request):
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return JsonResponse({"products": [], "categories": [], "brands": []})

    product_suggestions = list(
        Product.objects.filter(is_active=True)
        .filter(_browse_text_query(query))
        .annotate(search_rank=_search_rank_expression(query))
        .order_by("-search_rank", "-created_at")
        .values("title", "slug")[:5]
    )
    category_suggestions = list(
        Category.objects.filter(is_active=True, title__icontains=query).values("title", "slug")[:4]
    )
    brand_suggestions = list(
        Brand.objects.filter(is_active=True, title__icontains=query).values("title", "slug")[:4]
    )
    return JsonResponse(
        {
            "products": product_suggestions,
            "categories": category_suggestions,
            "brands": brand_suggestions,
        }
    )


def products(request):
    base_products = Product.objects.filter(is_active=True).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:all-products"),
    )
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
    base_products = Product.objects.filter(is_active=True, category=category).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:category-products", kwargs={"slug": category.slug}),
        show_category_filters=False,
    )
    context["category"] = category
    return render(request, "store/category_products.html", context)


def brand_products(request, slug):
    brand = get_object_or_404(Brand, slug=slug)
    base_products = Product.objects.filter(is_active=True, brand=brand).select_related("category", "brand").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:brand-products", kwargs={"slug": brand.slug}),
        show_brand_filters=False,
    )
    context["brand"] = brand
    return render(request, "store/brand_products.html", context)


class RegistrationView(View):
    def get(self, request):
        form = RegistrationForm()
        return render(request, "account/register.html", {"form": form, "next_url": request.GET.get("next", "")})

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
            messages.success(request, "Account created successfully. You can continue with your order now.")
            return redirect(_safe_redirect_url_with_query(request, "store:profile"))
        return render(request, "account/register.html", {"form": form, "next_url": request.POST.get("next", "")})


@login_required
def profile(request):
    addresses = Address.objects.filter(user=request.user).order_by("-id")
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
    saved_items = (
        Wishlist.objects.filter(user=request.user)
        .select_related("product", "product__category", "product__brand")
        .only(
            "id",
            "created_at",
            "product__id",
            "product__slug",
            "product__title",
            "product__price",
            "product__product_image",
            "product__available_sizes",
            "product__is_sold_out",
            "product__category__title",
            "product__category__slug",
            "product__brand__title",
            "product__brand__slug",
        )[:6]
    )
    has_affiliate_profile = AffiliateProfile.objects.filter(user=request.user).exists()
    profile_flow_status = _build_profile_flow_status(addresses, orders)
    return render(
        request,
        "account/profile.html",
        {
            "addresses": addresses,
            "orders": orders,
            "saved_items": saved_items,
            "saved_product_ids": _saved_product_ids_for_user(request.user),
            "has_affiliate_profile": has_affiliate_profile,
            "profile_flow_status": profile_flow_status,
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
        return render(request, "account/add_address.html", {"form": form, "next_url": request.GET.get("next", "")})

    def post(self, request):
        form = AddressForm(request.POST)
        if form.is_valid():
            user = request.user
            address = form.cleaned_data["address"]
            city = form.cleaned_data["city"]
            phone = form.cleaned_data["phone"]
            reg = Address(user=user, address=address, city=city, phone=phone)
            reg.save()
            redirect_target = _safe_redirect_url_with_query(request, "store:profile")
            if redirect_target == reverse("store:cart"):
                messages.success(request, "Address saved. You can now return to your cart and place the order.")
            else:
                messages.success(request, "New address added successfully.")
            return redirect(redirect_target)
        return render(request, "account/add_address.html", {"form": form, "next_url": request.POST.get("next", "")})


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

    requested_quantity = 1 if created else cart_item.quantity + 1
    if not _product_can_fulfill_quantity(product, requested_quantity, size_value=selected_size_value):
        message = f"Only {_product_size_stock(product, size_value=selected_size_value)} unit(s) are available for {product.title} ({selected_size_value or 'default size'})."
        if created:
            cart_item.delete()
        if is_ajax:
            return _json(message, ok=False, status=400)
        messages.warning(request, message)
        return redirect("store:product-detail", slug=product.slug)

    if not created:
        cart_item.quantity = requested_quantity
        cart_item.save(update_fields=["quantity", "updated_at"])
        success_message = f"Quantity of {product.title} (Size: {selected_size_value or 'N/A'}) updated in cart. Open your cart when you are ready to place the order."
        messages.success(request, success_message)
    else:
        success_message = f"Added {product.title} (Size: {selected_size_value or 'N/A'}) to cart. Open your cart to review delivery details and place the order."
        messages.success(request, success_message)

    if is_ajax:
        return _json(success_message, ok=True, status=200)

    return redirect(_safe_redirect_url(request, fallback_url="store:cart"))


def cart(request):
    user = _cart_owner_user(request)
    cart_products = Cart.objects.filter(user=user).select_related("product", "coupon", "product__category", "product__brand")
    latest_address = _latest_saved_address(request.user)

    amount = decimal.Decimal(0)
    for item in cart_products:
        line_total = item.quantity * _effective_unit_price(item.product.price, item.coupon)
        item.display_total_price = line_total
        amount += line_total

    shipping_city = latest_address.city if latest_address else ""
    shipping_amount = _shipping_amount_for_city(shipping_city, amount) if request.user.is_authenticated else decimal.Decimal(0)
    shipping_note = _shipping_note_for_city(shipping_city, amount) if request.user.is_authenticated else "Shipping will be calculated after you enter your delivery city during guest checkout."

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
        "latest_address": latest_address,
        "flow_status": _build_cart_flow_status(request, cart_products, latest_address),
        "shipping_note": shipping_note,
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

    requested_quantity = cp.quantity + 1
    if not _product_can_fulfill_quantity(cp.product, requested_quantity, size_value=cp.size):
        messages.warning(
            request,
            f"Only {_product_size_stock(cp.product, size_value=cp.size)} unit(s) are available for {cp.product.title} ({cp.size or 'default size'}).",
        )
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
    customer_address = _latest_saved_address(request.user)
    guest_checkout_address = None
    created_order_ids = []
    order_lines = []
    shipping_amount = Decimal("0.00")

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
    elif customer_address is None:
        messages.error(request, "Add a delivery address before placing your order.")
        return redirect(_address_entry_url("store:cart"))

    shipping_source_address = guest_checkout_address or customer_address

    try:
        with transaction.atomic():
            commissions_to_create = []
            for c in cart_items:
                locked_product = Product.objects.select_for_update().get(id=c.product_id)
                locked_size_stock = None
                if c.size:
                    locked_size_stock = ProductSizeStock.objects.select_for_update().filter(product_id=c.product_id, size=c.size).first()

                available_quantity = locked_size_stock.quantity if locked_size_stock else locked_product.stock_quantity
                if locked_product.is_sold_out or available_quantity < c.quantity:
                    raise ValueError(
                        f"{locked_product.title} ({c.size or 'default size'}) no longer has enough stock to fulfill your order."
                    )

                effective_price_per_item = _effective_unit_price(c.product.price, c.coupon)
                line_total_for_order = c.quantity * effective_price_per_item
                order = Order.objects.create(
                    user=user,
                    product=locked_product,
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

                if locked_size_stock:
                    locked_size_stock.quantity = max(0, locked_size_stock.quantity - c.quantity)
                    locked_size_stock.save(update_fields=["quantity", "updated_at"])

                locked_product.stock_quantity = max(0, locked_product.stock_quantity - c.quantity)
                if locked_product.stock_quantity == 0:
                    locked_product.is_sold_out = True
                    locked_product.save(update_fields=["stock_quantity", "is_sold_out", "updated_at"])
                else:
                    locked_product.save(update_fields=["stock_quantity", "updated_at"])

            if commissions_to_create:
                AffiliateCommission.objects.bulk_create(commissions_to_create)

            Cart.objects.filter(id__in=[c.id for c in cart_items]).delete()

            click_id = request.session.get(AFFILIATE_CLICK_SESSION_KEY)
            if click_id:
                AffiliateClick.objects.filter(id=click_id).update(converted=True)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("store:cart")

    shipping_amount = _shipping_amount_for_city(
        getattr(shipping_source_address, "city", ""),
        order_total,
    )

    notify_new_order(
        user=user,
        order_count=order_count,
        order_total=order_total,
        address=guest_checkout_address or customer_address,
        order_lines=order_lines,
        order_ids=created_order_ids,
    )

    messages.success(
        request,
        f"Order placed successfully. Estimated grand total including delivery: {(order_total + shipping_amount):.2f} ETB.",
    )
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
        "product__product_image",
        "product__title",
        "product__slug",
    ).order_by("-ordered_date")
    orders_for_display = []
    for order in all_orders:
        order.timeline = _order_status_timeline(order.status)
        order.status_copy = ORDER_STATUS_COPY.get(order.status, "")
        order.can_cancel = _can_cancel_order(order)
        orders_for_display.append(order)
    return render(
        request,
        "store/orders.html",
        {
            "orders": orders_for_display,
            "flow_status": _build_order_flow_status(all_orders),
            "order_status_summary": _order_status_summary(all_orders),
        },
    )


@login_required
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if request.method != "POST":
        messages.warning(request, "Invalid order action.")
        return redirect("store:orders")

    if not _can_cancel_order(order):
        messages.warning(request, "This order can no longer be cancelled online.")
        return redirect("store:orders")

    order.status = "Cancelled"
    order.save(update_fields=["status"])
    messages.success(request, f"Order #{order.id} was cancelled.")
    return redirect("store:orders")


def shop(request):
    return redirect("store:all-products")


def about(request):
    return render(request, "store/about-us.html")


def contact(request):
    return render(request, "store/contact.html")


def test(request):
    return redirect("store:home")
