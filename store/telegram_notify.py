import logging
import os
import html
import json
from decimal import Decimal
from urllib import error, parse, request

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _telegram_settings():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_ALERT_CHAT_ID") or "").strip()
    channel_chat_id = (os.getenv("TELEGRAM_CHANNEL_CHAT_ID") or "").strip()
    bot_username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@")
    if not token:
        return None, None, None, None
    return token, chat_id or None, channel_chat_id or None, bot_username or None


def _telegram_api_request(method, payload):
    token, _, _, _ = _telegram_settings()
    if not token:
        return False

    endpoint = f"https://api.telegram.org/bot{token}/{method}"
    encoded = parse.urlencode(payload).encode("utf-8")
    req = request.Request(endpoint, data=encoded, method="POST")
    try:
        with request.urlopen(req, timeout=6) as resp:
            status = getattr(resp, "status", 0)
            return 200 <= int(status) < 300
    except (error.HTTPError, error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False


def send_telegram_message(text, chat_id=None, reply_markup=None, parse_mode=None):
    _, default_chat_id, _, _ = _telegram_settings()
    target_chat_id = (chat_id or default_chat_id or "").strip()
    if not target_chat_id:
        return False

    payload = {
        "chat_id": target_chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _telegram_api_request("sendMessage", payload)


def _send_telegram_photo(photo_url, caption, chat_id, reply_markup=None, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    return _telegram_api_request("sendPhoto", payload)


def _send_telegram_media_group(chat_id, media_items):
    payload = {
        "chat_id": chat_id,
        "media": json.dumps(media_items),
    }
    return _telegram_api_request("sendMediaGroup", payload)


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


def _format_money(value):
    try:
        amount = Decimal(value)
    except Exception:
        return _safe_text(value)
    return f"{amount:,.2f}"


def _absolute_media_url(url):
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    site_url = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if site_url and url.startswith("/"):
        return f"{site_url}{url}"
    return None


def _product_caption(product):
    category = getattr(getattr(product, "category", None), "title", "N/A")
    brand = getattr(getattr(product, "brand", None), "title", "N/A")
    sizes = product.available_sizes or "Ask in bot"
    return _trim_message(
        (
            "<b>NEW DROP JUST LANDED</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"<b>{html.escape(_safe_text(product.title))}</b>\n"
            "\n"
            f"<b>Price</b>: {_format_money(product.price)} ETB\n"
            f"<b>Category</b>: {html.escape(_safe_text(category))}\n"
            f"<b>Brand</b>: {html.escape(_safe_text(brand))}\n"
            f"<b>Available Sizes</b>: {html.escape(_safe_text(sizes))}\n"
            "\n"
            "Tap <b>Choose Size</b> below to order in chat.\n"
            "\n"
            f"{html.escape(_safe_text(product.short_description, fallback='No description yet.'))}"
        )
    )


def _collect_product_image_urls(product, max_images=10):
    image_urls = []

    primary_url = _absolute_media_url(getattr(product.product_image, "url", ""))
    if primary_url:
        image_urls.append(primary_url)

    for extra in product.p_images.only("image")[:max_images]:
        url = _absolute_media_url(getattr(extra.image, "url", ""))
        if url and url not in image_urls:
            image_urls.append(url)
        if len(image_urls) >= max_images:
            break

    return image_urls


def post_product_to_channel(product):
    _, _, channel_chat_id, bot_username = _telegram_settings()
    if not product or not channel_chat_id or not bot_username:
        return False

    deep_link = f"https://t.me/{bot_username}?start=order_{product.id}"
    reply_markup = {
        "inline_keyboard": [[{"text": "Choose Size", "url": deep_link}]],
    }

    caption = _product_caption(product)
    image_urls = _collect_product_image_urls(product)

    if len(image_urls) > 1:
        media_items = []
        for idx, image_url in enumerate(image_urls):
            media = {
                "type": "photo",
                "media": image_url,
            }
            if idx == 0:
                media["caption"] = caption
                media["parse_mode"] = "HTML"
            media_items.append(media)

        album_sent = _send_telegram_media_group(
            chat_id=channel_chat_id,
            media_items=media_items,
        )
        if album_sent:
            cta_text = (
                "Ready to order this item?\n"
                "Tap below and choose your size to continue in chat."
            )
            return send_telegram_message(
                text=cta_text,
                chat_id=channel_chat_id,
                reply_markup=reply_markup,
            )

    if image_urls:
        sent = _send_telegram_photo(
            photo_url=image_urls[0],
            caption=caption,
            chat_id=channel_chat_id,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        if sent:
            return True

    fallback_text = (
        "NEW DROP JUST LANDED\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{_safe_text(product.title)}\n"
        f"Price: {_format_money(product.price)} ETB\n"
        f"Sizes: {_safe_text(product.available_sizes, fallback='Ask in bot')}\n"
        f"Order here: {deep_link}"
    )
    return send_telegram_message(
        text=fallback_text,
        chat_id=channel_chat_id,
        reply_markup=reply_markup,
    )


def notify_bot_order_lead(lead):
    if not lead:
        return False

    message = _trim_message(
        (
            "ORDER REQUEST FROM TELEGRAM BOT\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Ref: {_safe_text(lead.get('order_ref'))}\n"
            f"Customer: {_safe_text(lead.get('full_name'))}\n"
            f"Phone: {_safe_text(lead.get('phone'))}\n"
            f"Telegram: {_safe_text(lead.get('telegram_username'))}\n"
            f"Address: {_safe_text(lead.get('address'))}\n"
            f"City: {_safe_text(lead.get('city'))}\n"
            "\n"
            f"Product: {_safe_text(lead.get('product_title'))}\n"
            f"SKU: {_safe_text(lead.get('product_sku'))}\n"
            f"Size: {_safe_text(lead.get('size'))}\n"
            f"Quantity: {_safe_text(lead.get('quantity'))}\n"
            f"Unit Price: {_format_money(lead.get('unit_price'))} ETB\n"
            f"Estimated Total: {_format_money(lead.get('estimated_total'))} ETB\n"
            "\n"
            f"Requested at: {_safe_text(lead.get('requested_at'))}"
        )
    )
    return send_telegram_message(message)


def notify_customer_delivery_status(bot_order):
    if not bot_order:
        return False

    chat_id = _safe_text(getattr(bot_order, "telegram_chat_id", None), fallback="")
    if not chat_id:
        return False

    message = _trim_message(
        (
            "DELIVERY STATUS UPDATE\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"Order Ref: TG-{bot_order.id}\n"
            f"Product: {_safe_text(bot_order.product_title)}\n"
            f"SKU: {_safe_text(bot_order.product_sku)}\n"
            f"Size: {_safe_text(bot_order.size)}\n"
            f"Quantity: {_safe_text(bot_order.quantity)}\n"
            f"Status: {_safe_text(bot_order.status)}\n"
            "\n"
            "We will continue to notify you as your order progresses."
        )
    )
    return send_telegram_message(text=message, chat_id=chat_id)


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
    return send_telegram_message(_trim_message(message))


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
    return send_telegram_message(_trim_message(message))
