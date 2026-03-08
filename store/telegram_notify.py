import logging
import os
from decimal import Decimal
from urllib import error, parse, request

from django.utils import timezone

logger = logging.getLogger(__name__)


def _telegram_settings():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_ALERT_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return None, None
    return token, chat_id


def _send_telegram_message(text):
    token, chat_id = _telegram_settings()
    if not token or not chat_id:
        return False

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    req = request.Request(endpoint, data=payload, method="POST")
    try:
        with request.urlopen(req, timeout=6) as resp:
            status = getattr(resp, "status", 0)
            return 200 <= int(status) < 300
    except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False


def _format_full_name(user):
    full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
    return full_name or "N/A"


def _safe_text(value, fallback="N/A"):
    if value is None:
        return fallback
    value = str(value).strip()
    return value if value else fallback


def _trim_message(text, max_len=3900):
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n...truncated"


def notify_new_signup(user, address=None):
    if not user:
        return False

    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    address_text = _safe_text(getattr(address, "address", None))
    city_text = _safe_text(getattr(address, "city", None))
    phone_text = _safe_text(getattr(address, "phone", None), fallback=_safe_text(user.username))
    message = (
        "🟢 NEW SIGNUP ALERT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 Customer\n"
        f"• ID: {user.id}\n"
        f"• Full name: {_format_full_name(user)}\n"
        f"• Phone/Username: {_safe_text(user.username)}\n"
        f"• Email: {_safe_text(user.email)}\n"
        "\n"
        "📍 Address\n"
        f"• Address: {address_text}\n"
        f"• City: {city_text}\n"
        f"• Phone: {phone_text}\n"
        "\n"
        f"⏰ Time: {timestamp}"
    )
    return _send_telegram_message(_trim_message(message))


def notify_new_order(user, order_count, order_total, address=None, order_lines=None, order_ids=None):
    if not user or order_count <= 0:
        return False

    if not isinstance(order_total, Decimal):
        try:
            order_total = Decimal(order_total)
        except Exception:
            order_total = Decimal("0.00")

    timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")

    address_text = _safe_text(getattr(address, "address", None))
    city_text = _safe_text(getattr(address, "city", None))
    phone_text = _safe_text(getattr(address, "phone", None), fallback=_safe_text(user.username))

    order_ids_text = ", ".join([str(oid) for oid in (order_ids or [])]) if order_ids else "N/A"

    line_chunks = []
    for idx, line in enumerate(order_lines or [], start=1):
        line_chunks.append(
            (
                f"{idx}. 🧾 {_safe_text(line.get('title'))}\n"
                f"   • SKU: {_safe_text(line.get('sku'))}\n"
                f"   • Qty: {_safe_text(line.get('quantity'))} | Size: {_safe_text(line.get('size'))}\n"
                f"   • Unit: {_safe_text(line.get('unit_price'))} | Line total: {_safe_text(line.get('line_total'))}\n"
                f"   • Coupon: {_safe_text(line.get('coupon'))} | Status: {_safe_text(line.get('status'))}"
            )
        )
    order_lines_text = "\n".join(line_chunks) if line_chunks else "N/A"

    message = (
        "🛒 NEW ORDER ALERT\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 Customer\n"
        f"• ID: {user.id}\n"
        f"• Full name: {_format_full_name(user)}\n"
        f"• Phone/Username: {_safe_text(user.username)}\n"
        f"• Email: {_safe_text(user.email)}\n"
        "\n"
        "📍 Delivery\n"
        f"• Address: {address_text}\n"
        f"• City: {city_text}\n"
        f"• Phone: {phone_text}\n"
        "\n"
        "💳 Order Summary\n"
        f"• Order IDs: {order_ids_text}\n"
        f"• Lines: {order_count}\n"
        f"• Total: {order_total:.2f}\n"
        "\n"
        f"🧺 Items\n{order_lines_text}\n"
        "\n"
        f"⏰ Time: {timestamp}"
    )
    return _send_telegram_message(_trim_message(message))
