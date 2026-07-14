"""Checkout, order history, and order cancellation."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from store.constants import (
    ACCOUNT_ORDERS_PAGE_SIZE,
    AFFILIATE_CLICK_SESSION_KEY,
    ORDER_STATUS_COPY,
    ORDER_STATUS_SEQUENCE,
)
from store.forms import GuestCheckoutForm
from store.models import STATUS_CHOICES, Address, BackgroundTask, Cart, Order
from store.services.checkout import OrderPlacementError, place_order
from store.tasks import enqueue

from .affiliate import _affiliate_profile_from_session
from .cart import (
    _address_entry_url,
    _cart_owner_user,
    _latest_saved_address,
    _shipping_amount_for_city,
)
from .common import _querystring_without


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
    from django.db.models import Count as _Count
    counts = dict(
        orders_queryset.values("status").annotate(n=_Count("id")).values_list("status", "n")
    )
    return [{"label": label, "count": counts.get(value, 0)} for value, label in STATUS_CHOICES]


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

    customer_address = _latest_saved_address(request.user)
    guest_checkout_address = None

    if not request.user.is_authenticated:
        guest_form = GuestCheckoutForm(request.POST)
        if not guest_form.is_valid():
            for field_errors in guest_form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("store:cart")
        full_name = guest_form.cleaned_data["full_name"]
        phone = guest_form.cleaned_data["phone"]
        city = guest_form.cleaned_data["city"]
        address = guest_form.cleaned_data["address"]

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
        placement = place_order(
            user,
            cart_items,
            affiliate_profile=affiliate_profile,
            affiliate_click_id=request.session.get(AFFILIATE_CLICK_SESSION_KEY),
        )
    except OrderPlacementError as exc:
        messages.error(request, str(exc))
        return redirect("store:cart")

    shipping_amount = _shipping_amount_for_city(
        getattr(shipping_source_address, "city", ""),
        placement.order_total,
    )

    notify_payload = {
        "user_id": user.id,
        "order_count": placement.order_count,
        "order_total": str(placement.order_total),
        "address_id": shipping_source_address.id if shipping_source_address else None,
        "order_lines": placement.order_lines,
        "order_ids": placement.order_ids,
    }
    transaction.on_commit(
        lambda: enqueue(BackgroundTask.TYPE_TELEGRAM_ORDER_NOTIFY, notify_payload)
    )

    messages.success(
        request,
        f"Order placed successfully. Estimated grand total including delivery: {(placement.order_total + shipping_amount):.2f} ETB.",
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
    # Paginate the queryset first, then decorate only the current page's rows —
    # never materialize the full order history per request.
    paginator = Paginator(all_orders, ACCOUNT_ORDERS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    for order in page_obj.object_list:
        order.timeline = _order_status_timeline(order.status)
        order.status_copy = ORDER_STATUS_COPY.get(order.status, "")
        order.can_cancel = _can_cancel_order(order)
    return render(
        request,
        "store/orders.html",
        {
            "orders": page_obj,
            "page_obj": page_obj,
            "page_numbers": paginator.get_elided_page_range(number=page_obj.number, on_each_side=1, on_ends=1),
            "page_query": _querystring_without(request, "page"),
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
