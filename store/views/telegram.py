"""Telegram bot webhooks and the chat order conversation flow."""
import json
import os
from datetime import timedelta

from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from store.constants import TELEGRAM_ORDER_STATE_TTL_SECONDS
from store.models import Product, TelegramBotOrder, TelegramConversationState
from store.telegram_notify import (
    notify_bot_order_lead,
    send_admin_alert_message,
    send_customer_bot_message,
    send_product_gallery_to_customer,
)

from .catalog import _parse_available_sizes


def _set_telegram_order_state(chat_id, state):
    # Stored in the database (not the cache) so the conversation survives between
    # webhook requests on serverless/multi-process hosting where the local-memory
    # cache is not shared across processes.
    TelegramConversationState.objects.update_or_create(
        chat_id=str(chat_id),
        defaults={"state": state},
    )


def _get_telegram_order_state(chat_id):
    record = TelegramConversationState.objects.filter(chat_id=str(chat_id)).first()
    if not record:
        return None
    expiry_cutoff = timezone.now() - timedelta(seconds=TELEGRAM_ORDER_STATE_TTL_SECONDS)
    if record.updated_at < expiry_cutoff:
        record.delete()
        return None
    return record.state


def _clear_telegram_order_state(chat_id):
    TelegramConversationState.objects.filter(chat_id=str(chat_id)).delete()


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

    # If no secrets are configured in production, deny all requests.
    # In DEBUG mode we allow through so local dev works without a tunnel.
    if not accepted_secrets:
        from django.conf import settings as _settings
        return bool(_settings.DEBUG)

    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
    # Always require the header when secrets are configured — Telegram will
    # send it if you set secret_token when calling setWebhook.
    if not incoming_secret:
        return False
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
    if start_payload.startswith("notify_"):
        from django.utils import timezone as _tz

        from store.models import TelegramLink

        token = start_payload.replace("notify_", "", 1).strip()
        link = TelegramLink.objects.filter(token=token).first()
        if link is None:
            _send_customer_bot_text(chat_id, "This notification link is no longer valid — open the store and tap the Telegram button again.")
            return
        link.chat_id = str(chat_id)
        link.telegram_username = username or ""
        link.linked_at = _tz.now()
        link.save(update_fields=["chat_id", "telegram_username", "linked_at", "updated_at"])
        _send_customer_bot_text(
            chat_id,
            "You're all set! 🎉 We'll message you here with order confirmations, delivery updates, and back-in-stock alerts.",
        )
        return

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
