"""Cart contents, cart mutations, and coupon application."""
import decimal
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from store.constants import (
    ADDIS_FREE_SHIPPING_THRESHOLD,
    ADDIS_SHIPPING_FEE,
    OUTSIDE_ADDIS_SHIPPING_FEE,
)
from store.models import Address, Cart, Coupon, Product
from store.services.checkout import coupon_issue as _coupon_issue, effective_unit_price as _effective_unit_price

from .catalog import _parse_available_sizes, _product_can_fulfill_quantity, _product_size_stock
from .common import _ensure_session_key, _is_htmx, _safe_redirect_url


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


def _cart_owner_kwargs(request):
    """Cart ownership scope: the user when authenticated, else the session.

    Guests never get placeholder rows in auth_user — their cart rows carry
    the session key instead.
    """
    if request.user.is_authenticated:
        return {"user": request.user}
    return {"user": None, "session_key": _ensure_session_key(request)}


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


def add_to_cart(request):
    def _feedback(message, tone="success"):
        return render(
            request,
            "store/_add_to_cart_result.html",
            {"message": message, "tone": tone, "include_oob_badge": True},
        )

    if request.method != "POST":
        messages.warning(request, "Please use the add-to-cart button to add an item.")
        return redirect("store:home")

    is_htmx = _is_htmx(request)
    owner = _cart_owner_kwargs(request)
    product_id = request.POST.get("prod_id")
    selected_size = (request.POST.get("size") or "").strip()

    if not product_id:
        if is_htmx:
            return _feedback("Unable to add product to cart. Please try again.", tone="danger")
        messages.error(request, "Unable to add product to cart. Please try again.")
        return redirect("store:home")

    product = get_object_or_404(
        Product.objects.select_related("category", "brand"),
        id=product_id,
        is_active=True,
    )

    if product.is_sold_out:
        if is_htmx:
            return _feedback(f"{product.title} is currently sold out.", tone="warning")
        messages.warning(request, f"{product.title} is currently sold out.")
        return redirect("store:product-detail", slug=product.slug)

    available_sizes = _parse_available_sizes(product)
    selected_size_value = selected_size or None

    if available_sizes and not selected_size:
        if is_htmx:
            return _feedback("Please select a size for this product.", tone="danger")
        messages.error(request, "Please select a size for this product.")
        return redirect("store:product-detail", slug=product.slug)

    if selected_size and selected_size not in available_sizes:
        if is_htmx:
            return _feedback("Selected size is not available for this product.", tone="danger")
        messages.error(request, "Selected size is not available for this product.")
        return redirect("store:product-detail", slug=product.slug)

    cart_item, created = Cart.objects.get_or_create(
        product=product,
        size=selected_size_value,
        defaults={"quantity": 1},
        **owner,
    )

    requested_quantity = 1 if created else cart_item.quantity + 1
    if not _product_can_fulfill_quantity(product, requested_quantity, size_value=selected_size_value):
        message = f"Only {_product_size_stock(product, size_value=selected_size_value)} unit(s) are available for {product.title} ({selected_size_value or 'default size'})."
        if created:
            cart_item.delete()
        if is_htmx:
            return _feedback(message, tone="warning")
        messages.warning(request, message)
        return redirect("store:product-detail", slug=product.slug)

    if not created:
        cart_item.quantity = requested_quantity
        cart_item.save(update_fields=["quantity", "updated_at"])
        success_message = f"Quantity of {product.title} (Size: {selected_size_value or 'N/A'}) updated in cart. Open your cart when you are ready to place the order."
    else:
        success_message = f"Added {product.title} (Size: {selected_size_value or 'N/A'}) to cart. Open your cart to review delivery details and place the order."

    if is_htmx:
        return _feedback(success_message, tone="success")

    messages.success(request, success_message)
    return redirect(_safe_redirect_url(request, fallback_url="store:cart"))


def _cart_page_context(request):
    cart_products = Cart.objects.filter(**_cart_owner_kwargs(request)).select_related("product", "coupon", "product__category", "product__brand")
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

    return {
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


def _render_cart_contents(request, alert=None, tone="info"):
    """htmx response for cart mutations: fresh cart contents + OOB nav badge."""
    context = _cart_page_context(request)
    context["include_oob_badge"] = True
    if alert:
        context["cart_alert"] = alert
        context["cart_alert_tone"] = tone
    return render(request, "store/_cart_contents.html", context)


def cart(request):
    return render(request, "store/cart.html", _cart_page_context(request))


class AddCoupon(View):
    def post(self, request, *args, **kwargs):
        code = (request.POST.get("coupon") or "").strip()

        def _fail(msg):
            if _is_htmx(request):
                return _render_cart_contents(request, alert=msg, tone="warning")
            messages.warning(request, msg)
            return redirect("store:cart")

        if not code:
            return _fail("Please enter a coupon code.")

        coupon = Coupon.objects.filter(code__iexact=code).first()
        if coupon is None:
            return _fail("That coupon code doesn't exist.")

        issue = _coupon_issue(coupon)
        if issue:
            return _fail(issue)

        cart_products = Cart.objects.filter(**_cart_owner_kwargs(request))
        if not cart_products.exists():
            return _fail("Your cart is empty.")

        cart_products.update(coupon=coupon)
        if _is_htmx(request):
            return _render_cart_contents(
                request,
                alert=f"Coupon '{coupon.code}' applied — {coupon.discount}% off.",
                tone="success",
            )
        messages.success(request, "Coupon applied successfully.")
        return redirect("store:cart")


def remove_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    c = get_object_or_404(Cart, id=cart_id, **_cart_owner_kwargs(request))
    c.delete()

    if _is_htmx(request):
        return _render_cart_contents(request, alert="Item removed.", tone="success")
    messages.success(request, "Product removed from cart.")
    return redirect("store:cart")


def plus_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    cp = get_object_or_404(Cart.objects.select_related("product", "coupon"), id=cart_id, **_cart_owner_kwargs(request))

    if not cp.product.is_active or cp.product.is_sold_out:
        msg = f"{cp.product.title} is no longer available."
        if _is_htmx(request):
            return _render_cart_contents(request, alert=msg, tone="warning")
        messages.warning(request, msg)
        return redirect("store:cart")

    requested_quantity = cp.quantity + 1
    if not _product_can_fulfill_quantity(cp.product, requested_quantity, size_value=cp.size):
        msg = f"Only {_product_size_stock(cp.product, size_value=cp.size)} unit(s) are available."
        if _is_htmx(request):
            return _render_cart_contents(request, alert=msg, tone="warning")
        messages.warning(request, msg)
        return redirect("store:cart")

    cp.quantity += 1
    cp.save(update_fields=["quantity", "updated_at"])
    if _is_htmx(request):
        return _render_cart_contents(request)
    return redirect("store:cart")


def minus_cart(request, cart_id):
    if request.method != "POST":
        messages.warning(request, "Invalid cart action.")
        return redirect("store:cart")

    cp = get_object_or_404(Cart.objects.select_related("product", "coupon"), id=cart_id, **_cart_owner_kwargs(request))

    if cp.quantity == 1:
        cp.delete()
    else:
        cp.quantity -= 1
        cp.save(update_fields=["quantity", "updated_at"])

    if _is_htmx(request):
        return _render_cart_contents(request)
    return redirect("store:cart")
