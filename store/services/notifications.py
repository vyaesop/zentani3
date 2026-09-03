"""Customer messages outside Telegram: SMS and email.

Telegram stays the rich channel (see services.telegram); these helpers cover
the customers who never linked a chat — which, for a cash-on-delivery store,
is almost everyone. Every buyer leaves a phone number, so SMS is the default
confirmation channel; email is used when the customer gave one.

Handlers raise NotificationError only when a configured channel failed, so the
task queue retries real outages but never loops on "SMS is disabled".
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from store.models import Order, OrderGroup, RestockRequest
from store.sms import send_sms, sms_enabled

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """A configured channel failed to deliver."""


def _site_url():
    from store.telegram_notify import _base_site_url

    return _base_site_url()


def _absolute(path):
    base = _site_url()
    return f"{base}{path}" if base else path


def _email_enabled():
    backend = getattr(settings, "EMAIL_BACKEND", "")
    return bool(backend) and not backend.endswith("console.EmailBackend") and not backend.endswith("dummy.EmailBackend")


def _fmt(amount):
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def confirmation_url(group):
    return _absolute(reverse("store:order-confirmation", kwargs={"token": group.claim_token}))


def review_url(order):
    return _absolute(reverse("store:review-invite", kwargs={"token": order.ensure_review_token()}))


# ── Order confirmation ───────────────────────────────────────────────────────

def order_confirmation_sms_text(group):
    store_name = getattr(settings, "STORE_NAME", "Zentanee")
    payment = "Paid online" if group.is_paid_online else "Pay cash on delivery"
    return (
        f"{store_name}: order {group.number} received. "
        f"Total {_fmt(group.total)} ETB ({payment}). "
        f"We will call to confirm before dispatch. Track: {confirmation_url(group)}"
    )


def send_order_confirmation_sms(group):
    phone = group.customer_phone
    if not phone or not sms_enabled():
        return False
    return send_sms(phone, order_confirmation_sms_text(group))


def send_order_confirmation_email(group):
    email = group.customer_email
    if not email:
        return False
    lines = list(group.lines.select_related("product").order_by("id"))
    context = {
        "group": group,
        "lines": lines,
        "confirmation_url": confirmation_url(group),
        "store_name": getattr(settings, "STORE_NAME", "Zentanee"),
        "store_phone": getattr(settings, "STORE_PHONE", ""),
    }
    subject = f"{context['store_name']} order {group.number} received"
    body = render_to_string("emails/order_confirmation.txt", context)
    try:
        sent = send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", None), [email], fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - surfaced as a retryable task error
        logger.warning("Order confirmation email failed for %s: %s", group.number, exc)
        if _email_enabled():
            raise NotificationError(f"Email send failed for {group.number}: {exc}") from exc
        return False
    return bool(sent)


def send_order_messages(payload):
    """Task handler: SMS + email confirmation for one order group."""
    group = OrderGroup.objects.filter(pk=payload.get("group_id")).first()
    if group is None:
        return
    sms_ok = send_order_confirmation_sms(group)
    if group.customer_phone and sms_enabled() and not sms_ok and _sms_gateway_configured():
        raise NotificationError(f"SMS confirmation failed for {group.number}.")
    send_order_confirmation_email(group)


def _sms_gateway_configured():
    backend = (getattr(settings, "SMS_BACKEND", "disabled") or "").lower()
    return backend in {"afromessage", "http"}


# ── Status updates ───────────────────────────────────────────────────────────

def send_status_sms(order, status):
    """SMS for the statuses in SMS_STATUS_NOTIFY_STATUSES (dispatch by default)."""
    if status not in getattr(settings, "SMS_STATUS_NOTIFY_STATUSES", []):
        return False
    phone = order.customer_phone
    if not phone or not sms_enabled():
        return False
    store_name = getattr(settings, "STORE_NAME", "Zentanee")
    number = order.order_number
    if status == "On The Way":
        text = (
            f"{store_name}: order {number} is on the way. Please have "
            f"{_fmt(order.group.total if order.group_id else order.line_total)} ETB ready in cash "
            "and check the item with the driver before paying."
        )
    else:
        text = f"{store_name}: order {number} is now {status}."
    return send_sms(phone, text)


# ── Review invites ───────────────────────────────────────────────────────────

def review_invite_text(order):
    store_name = getattr(settings, "STORE_NAME", "Zentanee")
    return (
        f"{store_name}: how was your {order.product.title}? "
        f"A 30-second review helps the next shopper pick the right size: {review_url(order)}"
    )


def send_review_invite(payload):
    """Task handler: invite the buyer of a delivered line to review it.

    Telegram first (when the customer linked a chat), then SMS, then email.
    Exactly one channel is used; the invite timestamp prevents repeats.
    """
    order = Order.objects.select_related("product", "group", "user").filter(pk=payload.get("order_id")).first()
    if order is None or order.status != "Delivered" or order.review_invited_at:
        return
    if hasattr(order, "review") and order.review is not None:
        return

    from django.utils import timezone

    from store.models import TelegramLink
    from store.telegram_notify import send_customer_bot_message

    text = review_invite_text(order)
    delivered = False

    chat_id = TelegramLink.linked_chat_id_for(user_id=order.user_id, session_key=order.session_key or "")
    if chat_id:
        delivered = bool(send_customer_bot_message(text, chat_id))
    if not delivered and order.customer_phone and sms_enabled():
        delivered = send_sms(order.customer_phone, text)
    if not delivered:
        email = order.group.customer_email if order.group_id else (order.user.email if order.user_id else "")
        if email:
            try:
                send_mail(
                    f"How was your {order.product.title}?",
                    text,
                    getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    [email],
                    fail_silently=True,
                )
                delivered = True
            except Exception:  # noqa: BLE001
                delivered = False

    if delivered:
        order.review_invited_at = timezone.now()
        order.save(update_fields=["review_invited_at"])


# ── Restock alerts by email ──────────────────────────────────────────────────

def send_restock_emails(product, skip_user_ids=()):
    """Email everyone on the restock list who did not get a Telegram alert.

    Returns the ids of requests that were emailed successfully so the caller
    can clear them (one alert per restock).
    """
    if not product:
        return []
    store_name = getattr(settings, "STORE_NAME", "Zentanee")
    product_url = _absolute(reverse("store:product-detail", kwargs={"slug": product.slug}))
    emailed_ids = []
    for restock_request in RestockRequest.objects.filter(product=product):
        if restock_request.user_id and restock_request.user_id in skip_user_ids:
            continue
        if not restock_request.email:
            continue
        size_text = f" in size {restock_request.size}" if restock_request.size else ""
        try:
            sent = send_mail(
                f"{product.title} is back in stock",
                (
                    f"Good news — {product.title}{size_text} is available again at {store_name}.\n\n"
                    f"{product_url}\n\n"
                    "It went fast last time; cash on delivery, inspect before you pay."
                ),
                getattr(settings, "DEFAULT_FROM_EMAIL", None),
                [restock_request.email],
                fail_silently=True,
            )
        except Exception:  # noqa: BLE001
            sent = 0
        if sent:
            emailed_ids.append(restock_request.id)
    return emailed_ids
