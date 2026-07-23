"""Telegram notification services used by background-task handlers.

Wraps `store.telegram_notify` (which returns booleans and never raises) and
converts "configured but failed to send" into an exception so the task queue
can retry with backoff. When Telegram is not configured (local dev, tests),
sends are silent no-ops.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

from store.models import Address, Cart, Product, RestockRequest, TelegramLink
from store.telegram_notify import (
    _admin_bot_settings,
    _customer_bot_settings,
    notify_customer_abandoned_cart,
    notify_customer_order_confirmation,
    notify_customer_order_status,
    notify_customer_restock,
    notify_new_order,
    notify_new_signup,
    post_product_to_channel,
)


class TelegramSendError(Exception):
    """A Telegram send failed even though the bot is configured."""


def admin_bot_configured():
    token, _ = _admin_bot_settings()
    return bool(token)


def customer_bot_configured():
    token, channel_chat_id, bot_username = _customer_bot_settings()
    return bool(token and channel_chat_id and bot_username)


def send_product_post(product_id, force=False):
    product = (
        Product.objects.select_related("category", "brand")
        .filter(pk=product_id)
        .first()
    )
    if product is None:
        return  # Product deleted since enqueue — nothing to do.
    if not force and (not product.is_active or product.is_sold_out):
        return
    sent = post_product_to_channel(product, force=force)
    # Only a forced post is an unambiguous failure signal: an autopublish may
    # legitimately return False when the post signature is unchanged.
    if force and not sent and customer_bot_configured():
        raise TelegramSendError(f"Telegram channel post failed for product {product_id}.")


def send_order_notification(payload):
    user = None
    if payload.get("user_id"):
        user = User.objects.filter(pk=payload["user_id"]).first()
    guest_contact = payload.get("guest_contact")
    if user is None and not guest_contact:
        return
    address = None
    if payload.get("address_id"):
        address = Address.objects.filter(pk=payload["address_id"]).first()
    sent = notify_new_order(
        user=user,
        order_count=int(payload.get("order_count") or 0),
        order_total=Decimal(str(payload.get("order_total") or "0")),
        address=address,
        order_lines=payload.get("order_lines") or [],
        order_ids=payload.get("order_ids") or [],
        guest_contact=guest_contact,
    )
    if not sent and admin_bot_configured():
        raise TelegramSendError("Telegram order notification failed.")


def send_signup_notification(payload):
    user = User.objects.filter(pk=payload.get("user_id")).first()
    if user is None:
        return
    address = None
    if payload.get("address_id"):
        address = Address.objects.filter(pk=payload["address_id"]).first()
    sent = notify_new_signup(user=user, address=address)
    if not sent and admin_bot_configured():
        raise TelegramSendError("Telegram signup notification failed.")


# ── Customer-facing sends (all no-ops unless the customer linked Telegram) ──

def send_customer_order_confirmation(payload):
    chat_id = TelegramLink.linked_chat_id_for(
        user_id=payload.get("user_id"),
        session_key=payload.get("session_key") or "",
    )
    if not chat_id:
        return
    sent = notify_customer_order_confirmation(
        chat_id,
        order_ids=payload.get("order_ids") or [],
        order_lines=payload.get("order_lines") or [],
        order_total=Decimal(str(payload.get("order_total") or "0")),
        customer_name=payload.get("customer_name") or "",
    )
    if not sent and customer_bot_configured():
        raise TelegramSendError("Customer order confirmation failed.")


def send_customer_order_status(payload):
    from store.models import Order

    order = Order.objects.filter(pk=payload.get("order_id")).select_related("product").first()
    if order is None:
        return
    chat_id = TelegramLink.linked_chat_id_for(
        user_id=order.user_id,
        session_key=order.session_key or "",
    )
    if not chat_id:
        return
    from store.constants import ORDER_STATUS_COPY

    status = payload.get("status") or order.status
    sent = notify_customer_order_status(
        chat_id,
        order_id=order.id,
        product_title=order.product.title if order.product_id else "Your item",
        status=status,
        status_copy=payload.get("status_copy") or ORDER_STATUS_COPY.get(status, ""),
    )
    if not sent and customer_bot_configured():
        raise TelegramSendError(f"Customer status update failed for order {order.id}.")


def send_customer_restock_notifications(payload):
    """Alert every linked customer waiting on this product, then clear their
    restock requests so they are notified once per restock."""
    product = Product.objects.filter(pk=payload.get("product_id"), is_active=True, is_sold_out=False).first()
    if product is None:
        return

    failures = 0
    for restock_request in RestockRequest.objects.filter(product=product).select_related("user"):
        chat_id = ""
        if restock_request.user_id:
            chat_id = TelegramLink.linked_chat_id_for(user_id=restock_request.user_id)
        if not chat_id:
            continue  # No Telegram opt-in; the request stays for future channels.
        if notify_customer_restock(chat_id, product=product, size=restock_request.size or ""):
            restock_request.delete()
        else:
            failures += 1

    if failures and customer_bot_configured():
        raise TelegramSendError(f"{failures} restock alert(s) failed for product {product.id}.")


def send_customer_abandoned_cart_nudge(payload):
    link = TelegramLink.objects.filter(pk=payload.get("link_id")).exclude(chat_id="").first()
    if link is None:
        return
    if link.user_id:
        cart_rows = Cart.objects.filter(user_id=link.user_id).select_related("product")
    else:
        cart_rows = Cart.objects.filter(user=None, session_key=link.session_key).select_related("product")
    cart_rows = list(cart_rows)
    if not cart_rows:
        return

    latest_activity = max(row.updated_at for row in cart_rows)
    if link.last_abandoned_nudge_at and link.last_abandoned_nudge_at >= latest_activity:
        return  # Already nudged for this cart state.

    cart_lines = [{"title": row.product.title, "quantity": row.quantity} for row in cart_rows]
    cart_total = sum((row.total_price for row in cart_rows), Decimal("0.00"))
    sent = notify_customer_abandoned_cart(link.chat_id, cart_lines=cart_lines, cart_total=cart_total)
    if not sent:
        if customer_bot_configured():
            raise TelegramSendError(f"Abandoned-cart nudge failed for link {link.id}.")
        return
    link.last_abandoned_nudge_at = timezone.now()
    link.save(update_fields=["last_abandoned_nudge_at", "updated_at"])


def send_customer_broadcast(payload):
    from store.telegram_notify import send_customer_broadcast_message

    link = TelegramLink.objects.filter(pk=payload.get("link_id")).exclude(chat_id="").first()
    if link is None:
        return
    text = (payload.get("text") or "").strip()
    if not text:
        return
    sent = send_customer_broadcast_message(link.chat_id, text)
    if not sent and customer_bot_configured():
        raise TelegramSendError(f"Broadcast failed for link {link.id}.")


def send_wishlist_sale_notifications(payload):
    """Alert every linked customer whose wishlist contains this newly
    discounted product. Enqueued only on the not-on-sale -> on-sale
    transition, so each markdown notifies once."""
    from store.models import Wishlist
    from store.telegram_notify import notify_customer_wishlist_sale

    product = Product.objects.filter(pk=payload.get("product_id"), is_active=True).first()
    if product is None or not product.is_on_sale:
        return

    failures = 0
    notified_chat_ids = set()
    for entry in Wishlist.objects.filter(product=product).select_related("user"):
        chat_id = TelegramLink.linked_chat_id_for(user_id=entry.user_id)
        if not chat_id or chat_id in notified_chat_ids:
            continue
        if notify_customer_wishlist_sale(chat_id, product=product):
            notified_chat_ids.add(chat_id)
        else:
            failures += 1

    if failures and customer_bot_configured():
        raise TelegramSendError(f"{failures} wishlist sale alert(s) failed for product {product.id}.")
