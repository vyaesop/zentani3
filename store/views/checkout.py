"""Checkout, order confirmation, order history, and order cancellation."""
import json

from django.conf import settings
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
from store.forms import GuestCheckoutForm, PaymentMethodForm
from store.models import STATUS_CHOICES, BackgroundTask, Cart, Order, OrderGroup
from store.payments import chapa
from store.services.checkout import OrderPlacementError, cancel_order_line, place_order
from store.tasks import enqueue

from .affiliate import _affiliate_profile_from_session
from .cart import (
    _address_entry_url,
    _cart_owner_kwargs,
    _latest_saved_address,
)
from .catalog import _ga_item
from .common import _querystring_without, _telegram_optin_context

GUEST_ORDER_TOKENS_SESSION_KEY = "guest_order_tokens"


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
        "meta": f"Latest order: {latest_order.order_number} on {latest_order.ordered_date.strftime('%Y-%m-%d %H:%M')}.",
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


def _remember_guest_order(request, group):
    tokens = [token for token in request.session.get(GUEST_ORDER_TOKENS_SESSION_KEY, []) if token != group.claim_token]
    request.session[GUEST_ORDER_TOKENS_SESSION_KEY] = [group.claim_token, *tokens][:10]
    request.session.modified = True


def _confirmation_url(request, group):
    return request.build_absolute_uri(reverse("store:order-confirmation", kwargs={"token": group.claim_token}))


def checkout(request):
    if request.method != "POST":
        messages.warning(request, "Invalid checkout request.")
        return redirect("store:cart")

    user = request.user if request.user.is_authenticated else None
    affiliate_profile = _affiliate_profile_from_session(request)
    if affiliate_profile and user and affiliate_profile.user_id == user.id:
        affiliate_profile = None

    cart_items = list(Cart.objects.filter(**_cart_owner_kwargs(request)).select_related("product", "coupon"))

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

    payment_form = PaymentMethodForm(request.POST)
    if not payment_form.is_valid():
        for error in payment_form.errors.get("payment_method", []):
            messages.error(request, error)
        return redirect("store:cart")
    payment_method = payment_form.cleaned_data["payment_method"]

    customer_address = _latest_saved_address(request.user)
    guest_contact = None
    contact_email = ""

    if user is None:
        guest_form = GuestCheckoutForm(request.POST)
        if not guest_form.is_valid():
            for field_errors in guest_form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("store:cart")
        guest_contact = {
            "full_name": guest_form.cleaned_data["full_name"].strip(),
            "phone": guest_form.cleaned_data["phone"].strip(),
            "city": guest_form.cleaned_data["city"].strip(),
            "address": guest_form.cleaned_data["address"].strip(),
        }
        contact_email = guest_form.cleaned_data.get("email") or ""
        if contact_email:
            guest_contact["email"] = contact_email
    elif customer_address is None:
        messages.error(request, "Add a delivery address before placing your order.")
        return redirect(_address_entry_url("store:cart"))

    try:
        placement = place_order(
            user,
            cart_items,
            guest_contact=guest_contact,
            session_key=request.session.session_key or "",
            affiliate_profile=affiliate_profile,
            affiliate_click_id=request.session.get(AFFILIATE_CLICK_SESSION_KEY),
            address=customer_address,
            payment_method=payment_method,
            contact_email=contact_email,
        )
    except OrderPlacementError as exc:
        messages.error(request, str(exc))
        return redirect("store:cart")

    group = placement.group
    if user is None:
        _remember_guest_order(request, group)

    # Optional prepay: hand the shopper to Chapa. If Chapa is down, the order
    # still stands as cash on delivery rather than being lost.
    if payment_method == OrderGroup.PAYMENT_CHAPA:
        try:
            checkout_url = chapa.initialize_payment(
                group,
                return_url=request.build_absolute_uri(
                    f"{reverse('store:chapa-return')}?tx_ref={chapa.tx_ref_for(group)}"
                ),
                callback_url=request.build_absolute_uri(reverse("store:chapa-webhook")),
            )
        except chapa.ChapaError as exc:
            group.payment_method = OrderGroup.PAYMENT_COD
            group.payment_status = OrderGroup.PAYMENT_UNPAID
            group.save(update_fields=["payment_method", "payment_status", "updated_at"])
            messages.warning(request, f"{exc} Your order {group.number} was placed as cash on delivery instead.")
            checkout_url = ""
    else:
        checkout_url = ""

    _enqueue_order_notifications(request, user, group, placement, customer_address, guest_contact)

    messages.success(
        request,
        f"Order {group.number} placed successfully. Total including delivery: {placement.grand_total:,.2f} ETB.",
    )
    if checkout_url:
        return redirect(checkout_url)
    return redirect("store:order-confirmation", token=group.claim_token)


def _enqueue_order_notifications(request, user, group, placement, customer_address, guest_contact):
    confirmation_url = _confirmation_url(request, group)
    notify_payload = {
        "user_id": user.id if user else None,
        "guest_contact": guest_contact,
        "order_count": placement.order_count,
        "order_total": str(placement.order_total),
        "delivery_fee": str(placement.delivery_fee),
        "grand_total": str(placement.grand_total),
        "order_number": group.number,
        "payment_method": group.payment_method,
        "address_id": customer_address.id if (user and customer_address) else None,
        "order_lines": placement.order_lines,
        "order_ids": placement.order_ids,
    }
    customer_confirm_payload = {
        "user_id": user.id if user else None,
        "session_key": request.session.session_key or "",
        "order_ids": placement.order_ids,
        "order_lines": placement.order_lines,
        "order_total": str(placement.order_total),
        "delivery_fee": str(placement.delivery_fee),
        "grand_total": str(placement.grand_total),
        "order_number": group.number,
        "confirmation_url": confirmation_url,
        "paid_online": group.is_paid_online,
        "customer_name": group.customer_name,
    }
    messages_payload = {"group_id": group.id}
    transaction.on_commit(
        lambda: (
            enqueue(BackgroundTask.TYPE_TELEGRAM_ORDER_NOTIFY, notify_payload),
            enqueue(BackgroundTask.TYPE_CUSTOMER_ORDER_CONFIRM, customer_confirm_payload),
            enqueue(BackgroundTask.TYPE_CUSTOMER_ORDER_MESSAGES, messages_payload),
        )
    )


def _group_lines(group):
    lines = list(group.lines.select_related("product").order_by("id"))
    for line in lines:
        line.timeline = _order_status_timeline(line.status)
        line.status_copy = ORDER_STATUS_COPY.get(line.status, "")
        line.can_cancel = _can_cancel_order(line)
    return lines


def order_confirmation(request, token):
    """Post-checkout receipt reachable by anyone holding the claim token.

    Guests get here straight after checkout (and again from the SMS/Telegram
    link); it carries the order number, lines, delivery fee, total, payment
    state, what happens next, and the Telegram opt-in where it finally has a
    concrete benefit to offer.
    """
    group = get_object_or_404(OrderGroup.objects.select_related("user"), claim_token=token)
    lines = _group_lines(group)

    emit_purchase = not group.purchase_tracked
    if emit_purchase:
        OrderGroup.objects.filter(pk=group.pk).update(purchase_tracked=True)

    ga_purchase = {
        "transaction_id": group.number,
        "value": float(group.total),
        "shipping": float(group.delivery_fee),
        "currency": "ETB",
        "coupon": group.coupon_code or "",
        "items": [_ga_item(line.product, quantity=line.quantity, size=line.size or "") for line in lines],
    }
    return render(
        request,
        "store/order_confirmation.html",
        {
            "group": group,
            "lines": lines,
            "group_status": group.status,
            "emit_purchase": emit_purchase,
            "ga_purchase_json": json.dumps(ga_purchase),
            "robots_meta": "noindex, nofollow",
            "store_phone": settings.STORE_PHONE,
            **_telegram_optin_context(request),
        },
    )


def orders(request):
    if request.user.is_authenticated:
        all_orders = Order.objects.filter(user=request.user)
    else:
        tokens = request.session.get(GUEST_ORDER_TOKENS_SESSION_KEY, [])
        if not tokens:
            return redirect(f"{reverse('store:login')}?next={reverse('store:orders')}")
        all_orders = Order.objects.filter(group__claim_token__in=tokens)

    all_orders = all_orders.select_related("product", "group").only(
        "id",
        "quantity",
        "size",
        "status",
        "ordered_date",
        "line_total",
        "price_at_purchase",
        "staff_notes",
        "group__id",
        "group__number",
        "group__claim_token",
        "group__delivery_fee",
        "group__total",
        "group__payment_method",
        "group__payment_status",
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
        order.can_cancel = _can_cancel_order(order) and request.user.is_authenticated
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
            "robots_meta": "noindex, nofollow",
            **_telegram_optin_context(request),
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

    cancel_order_line(order)
    messages.success(request, f"Order {order.order_number} ({order.product.title}) was cancelled.")
    return redirect("store:orders")
