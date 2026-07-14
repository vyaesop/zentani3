"""Telegram notification services used by background-task handlers.

Wraps `store.telegram_notify` (which returns booleans and never raises) and
converts "configured but failed to send" into an exception so the task queue
can retry with backoff. When Telegram is not configured (local dev, tests),
sends are silent no-ops.
"""
from decimal import Decimal

from django.contrib.auth.models import User

from store.models import Address, Product
from store.telegram_notify import (
    _admin_bot_settings,
    _customer_bot_settings,
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
