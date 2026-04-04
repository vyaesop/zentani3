import logging
import os
import html
import json
import hashlib
import mimetypes
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from urllib import error, parse, request

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)
TELEGRAM_MEDIA_GROUP_LIMIT = 10
_TELEGRAM_AUTOPUBLISH_SUSPENDED = ContextVar("telegram_autopublish_suspended", default=False)
_INVALID_CLOUDINARY_VALUES = {
    "",
    "untitled",
    "changeme",
    "your-cloud-name",
    "none",
    "null",
}


def _normalized_media_name(name):
    value = str(name or "").replace("\\", "/").lstrip("/")
    if value.startswith("media/"):
        return value[len("media/"):]
    return value


def _cloudinary_cloud_name():
    value = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
    if value.lower() in _INVALID_CLOUDINARY_VALUES:
        return ""
    return value


def _cloudinary_delivery_url(storage_name):
    cloud_name = _cloudinary_cloud_name()
    normalized_name = _normalized_media_name(storage_name)
    if not cloud_name or not normalized_name:
        return None
    return (
        f"https://res.cloudinary.com/{cloud_name}/image/upload/"
        f"f_webp,q_auto/v1/media/{normalized_name}"
    )


@contextmanager
def suspend_telegram_autopublish():
    token = _TELEGRAM_AUTOPUBLISH_SUSPENDED.set(True)
    try:
        yield
    finally:
        _TELEGRAM_AUTOPUBLISH_SUSPENDED.reset(token)


def telegram_autopublish_suspended():
    return _TELEGRAM_AUTOPUBLISH_SUSPENDED.get()


def _admin_bot_settings():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_ALERT_CHAT_ID") or "").strip()
    if not token:
        return None, None
    return token, chat_id or None


def _customer_bot_settings():
    token = (os.getenv("TELEGRAM_CUSTOMER_BOT_TOKEN") or "").strip()
    channel_chat_id = (os.getenv("TELEGRAM_CUSTOMER_CHANNEL_CHAT_ID") or "").strip()
    bot_username = (os.getenv("TELEGRAM_CUSTOMER_BOT_USERNAME") or "").strip().lstrip("@")
    if not token:
        return None, None, None
    return token, channel_chat_id or None, bot_username or None


def _base_site_url():
    for candidate in (
        getattr(settings, "SITE_URL", ""),
        os.getenv("SITE_URL", ""),
        os.getenv("VERCEL_PROJECT_PRODUCTION_URL", ""),
        os.getenv("VERCEL_URL", ""),
    ):
        value = (candidate or "").strip().rstrip("/")
        if not value:
            continue
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return f"https://{value.lstrip('/')}"
    return ""


def _telegram_api_request(method, payload, token):
    return _telegram_api_request_with_files(method, payload, token, files=None)


def _telegram_api_request_with_files(method, payload, token, files=None):
    if not token:
        return False

    endpoint = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        boundary = f"----CodexTelegram{uuid.uuid4().hex}"
        body = bytearray()

        for key, value in payload.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        for field_name, filename, content, content_type in files:
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8")
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            body.extend(content)
            body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        req = request.Request(
            endpoint,
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    else:
        encoded = parse.urlencode(payload).encode("utf-8")
        req = request.Request(endpoint, data=encoded, method="POST")
    try:
        with request.urlopen(req, timeout=6) as resp:
            status = getattr(resp, "status", 0)
            return 200 <= int(status) < 300
    except error.HTTPError as exc:
        response_body = ""
        try:
            response_body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            response_body = ""
        if response_body:
            logger.warning("Telegram %s failed: %s | response=%s", method, exc, response_body)
        else:
            logger.warning("Telegram %s failed: %s", method, exc)
        return False
    except (error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Telegram %s failed: %s", method, exc)
        return False


def send_admin_alert_message(text, chat_id=None, reply_markup=None, parse_mode=None):
    token, default_chat_id = _admin_bot_settings()
    target_chat_id = (chat_id or default_chat_id or "").strip()
    if not target_chat_id or not token:
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
    return _telegram_api_request("sendMessage", payload, token)


def send_customer_bot_message(text, chat_id, reply_markup=None, parse_mode=None):
    token, _, _ = _customer_bot_settings()
    target_chat_id = (chat_id or "").strip()
    if not target_chat_id or not token:
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
    return _telegram_api_request("sendMessage", payload, token)


def _send_telegram_photo(photo_url, caption, chat_id, token, reply_markup=None, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    return _telegram_api_request("sendPhoto", payload, token)


def _send_telegram_media_group(chat_id, media_items, token, files=None):
    payload = {
        "chat_id": chat_id,
        "media": json.dumps(media_items),
    }
    return _telegram_api_request_with_files("sendMediaGroup", payload, token, files=files)


def _mark_channel_post_success(product, signature):
    product.__class__.objects.filter(pk=product.pk).update(
        telegram_channel_last_post_signature=signature,
        telegram_channel_last_posted_at=timezone.now(),
    )


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


def _normalized_storage_candidates(name):
    value = _normalized_media_name(name)
    candidates = []
    if name:
        candidates.append(str(name).replace("\\", "/").lstrip("/"))
    if value and value not in candidates:
        candidates.append(value)
    return candidates


def _field_file_upload(field_file, field_name):
    if not field_file:
        return None

    storage = getattr(field_file, "storage", None)
    fallback_url = _cloudinary_delivery_url(getattr(field_file, "name", ""))
    for candidate_name in _normalized_storage_candidates(getattr(field_file, "name", "")):
        try:
            if storage is not None and hasattr(storage, "exists") and not storage.exists(candidate_name):
                continue
            if storage is not None:
                opened = storage.open(candidate_name, "rb")
            else:
                field_file.open("rb")
                opened = field_file
            try:
                content = opened.read()
            finally:
                opened.close()
        except Exception as exc:
            if not fallback_url:
                logger.warning("Telegram media open failed for %s: %s", candidate_name, exc)
            continue

        if not content:
            continue

        filename = os.path.basename(candidate_name) or f"{field_name}.jpg"
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return (field_name, filename, content, content_type)
    return None


def _absolute_media_url(url, storage_name=""):
    candidate = (url or "").strip()
    cloudinary_url = _cloudinary_delivery_url(storage_name)

    if candidate.startswith("https://res.cloudinary.com/"):
        if "/upload/" in candidate and "f_webp,q_auto" not in candidate:
            return candidate.replace("/upload/", "/upload/f_webp,q_auto/", 1)
        return candidate

    if not candidate and storage_name:
        if cloudinary_url:
            return cloudinary_url
        normalized_name = _normalized_media_name(storage_name)
        if normalized_name:
            candidate = f"/media/{normalized_name}"

    if not candidate:
        return None

    if cloudinary_url:
        return cloudinary_url

    if candidate.startswith("/media/media/"):
        candidate = candidate[len("/media"):]
    elif candidate.startswith("media/"):
        candidate = f"/{candidate}"

    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate

    site_url = _base_site_url()
    if site_url and candidate.startswith("/"):
        return f"{site_url}{candidate}"
    return None


def _product_post_signature(product):
    category_title = getattr(getattr(product, "category", None), "title", "")
    brand_title = getattr(getattr(product, "brand", None), "title", "")
    extra_image_names = list(
        product.p_images.order_by("id").values_list("image", flat=True)
    )
    signature_payload = "|".join(
        [
            _safe_text(product.title, fallback=""),
            _safe_text(product.sku, fallback=""),
            _safe_text(product.short_description, fallback=""),
            _safe_text(product.available_sizes, fallback=""),
            _safe_text(product.price, fallback=""),
            _safe_text(category_title, fallback=""),
            _safe_text(brand_title, fallback=""),
            _safe_text(getattr(product.product_image, "name", ""), fallback=""),
            "1" if getattr(product, "is_active", False) else "0",
            "1" if getattr(product, "is_sold_out", False) else "0",
            *[_safe_text(name, fallback="") for name in extra_image_names],
        ]
    )
    return hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()


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


def _collect_product_image_urls(product, max_images=None):
    image_urls = []

    primary_url = _absolute_media_url(
        getattr(product.product_image, "url", ""),
        storage_name=getattr(product.product_image, "name", ""),
    )
    if primary_url:
        image_urls.append(primary_url)

    extras_qs = product.p_images.only("image").order_by("id")
    extras = extras_qs[:max_images] if max_images else extras_qs
    for extra in extras:
        url = _absolute_media_url(
            getattr(extra.image, "url", ""),
            storage_name=getattr(extra.image, "name", ""),
        )
        if url and url not in image_urls:
            image_urls.append(url)
        if max_images and len(image_urls) >= max_images:
            break

    return image_urls


def _collect_product_media_entries(product, max_images=None):
    media_entries = []
    seen = set()

    def add_entry(field_file):
        if not field_file:
            return
        file_name = _normalized_media_name(getattr(field_file, "name", ""))
        fallback_url = _absolute_media_url(
            getattr(field_file, "url", ""),
            storage_name=getattr(field_file, "name", ""),
        )
        dedupe_key = file_name or fallback_url
        if dedupe_key and dedupe_key in seen:
            return
        if dedupe_key:
            seen.add(dedupe_key)
        media_entries.append(
            {
                "field_file": field_file,
                "file_name": file_name,
                "fallback_url": fallback_url,
            }
        )

    add_entry(getattr(product, "product_image", None))

    extras_qs = product.p_images.only("image").order_by("id")
    extras = extras_qs[:max_images] if max_images else extras_qs
    for extra in extras:
        add_entry(getattr(extra, "image", None))
        if max_images and len(media_entries) >= max_images:
            break

    return media_entries


def _chunked_media_groups(media_entries, intro_caption=None):
    chunks = []
    for start in range(0, len(media_entries), TELEGRAM_MEDIA_GROUP_LIMIT):
        chunk_entries = media_entries[start:start + TELEGRAM_MEDIA_GROUP_LIMIT]
        media_items = []
        files = []
        for idx, entry in enumerate(chunk_entries):
            attach_name = f"photo{start + idx}"
            upload = _field_file_upload(entry.get("field_file"), attach_name)
            media_ref = entry.get("fallback_url")
            if upload:
                files.append(upload)
                media_ref = f"attach://{attach_name}"
            if not media_ref:
                continue
            media = {"type": "photo", "media": media_ref}
            if start == 0 and idx == 0 and intro_caption:
                media["caption"] = intro_caption
                media["parse_mode"] = "HTML"
            media_items.append(media)
        if media_items:
            chunks.append((media_items, files))
    return chunks


def _send_all_media_groups(chat_id, media_entries, token, intro_caption=None):
    if not media_entries:
        return False

    sent_any = False
    for media_items, files in _chunked_media_groups(media_entries, intro_caption=intro_caption):
        group_sent = _send_telegram_media_group(
            chat_id=chat_id,
            media_items=media_items,
            token=token,
            files=files or None,
        )
        if not group_sent:
            return False
        sent_any = True
    return sent_any


def _product_gallery_intro(product):
    sizes = product.available_sizes or "Ask in chat"
    return _trim_message(
        (
            f"<b>{html.escape(_safe_text(product.title))}</b>\n"
            f"Price: {_format_money(product.price)} ETB\n"
            f"Sizes: {html.escape(_safe_text(sizes))}\n"
            "\n"
            "Reply with your size to continue."
        )
    )


def _send_media_entry_photo(entry, caption, chat_id, token, reply_markup=None, parse_mode="HTML"):
    upload = _field_file_upload(entry.get("field_file"), "photo")
    if upload:
        payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        return _telegram_api_request_with_files("sendPhoto", payload, token, files=[upload])

    fallback_url = entry.get("fallback_url")
    if fallback_url:
        return _send_telegram_photo(
            photo_url=fallback_url,
            caption=caption,
            chat_id=chat_id,
            token=token,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    return False


def send_product_gallery_to_customer(product, chat_id):
    token, _, _ = _customer_bot_settings()
    target_chat_id = (chat_id or "").strip()
    if not token or not target_chat_id or not product:
        return False

    media_entries = _collect_product_media_entries(product)
    if len(media_entries) > 1:
        intro = _product_gallery_intro(product)
        if _send_all_media_groups(chat_id=target_chat_id, media_entries=media_entries, token=token, intro_caption=intro):
            return True

    if media_entries:
        return _send_media_entry_photo(
            entry=media_entries[0],
            caption=_product_gallery_intro(product),
            chat_id=target_chat_id,
            token=token,
            parse_mode="HTML",
        )

    return False


def post_product_to_channel(product, force=False):
    token, channel_chat_id, bot_username = _customer_bot_settings()
    if not product or not channel_chat_id or not bot_username or not token:
        return False

    current_signature = _product_post_signature(product)
    if not force and current_signature == _safe_text(getattr(product, "telegram_channel_last_post_signature", ""), fallback=""):
        return False

    deep_link = f"https://t.me/{bot_username}?start=order_{product.id}"
    reply_markup = {
        "inline_keyboard": [[{"text": "Choose Size", "url": deep_link}]],
    }

    caption = _product_caption(product)
    media_entries = _collect_product_media_entries(product)

    if len(media_entries) > 1:
        album_sent = _send_all_media_groups(
            chat_id=channel_chat_id,
            media_entries=media_entries,
            token=token,
            intro_caption=caption,
        )
        if album_sent:
            cta_text = (
                "Ready to order this item?\n"
                "Tap below and choose your size to continue in chat."
            )
            sent = send_customer_bot_message(
                text=cta_text,
                chat_id=channel_chat_id,
                reply_markup=reply_markup,
            )
            if sent:
                _mark_channel_post_success(product, current_signature)
                return True
            sent = send_customer_bot_message(
                text=f"{cta_text}\n\nOrder link: {deep_link}",
                chat_id=channel_chat_id,
            )
            if sent:
                _mark_channel_post_success(product, current_signature)
            return sent

    if media_entries:
        sent = _send_media_entry_photo(
            entry=media_entries[0],
            caption=caption,
            chat_id=channel_chat_id,
            token=token,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        if sent:
            _mark_channel_post_success(product, current_signature)
            return True

    fallback_text = (
        "NEW DROP JUST LANDED\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{_safe_text(product.title)}\n"
        f"Price: {_format_money(product.price)} ETB\n"
        f"Sizes: {_safe_text(product.available_sizes, fallback='Ask in bot')}\n"
        f"Order here: {deep_link}"
    )
    sent = send_customer_bot_message(
        text=fallback_text,
        chat_id=channel_chat_id,
        reply_markup=reply_markup,
    )
    if not sent:
        sent = send_customer_bot_message(
            text=f"{fallback_text}\nChoose Size in bot: {deep_link}",
            chat_id=channel_chat_id,
        )
    if sent:
        _mark_channel_post_success(product, current_signature)
    return sent


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
    return send_admin_alert_message(message)


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
    return send_customer_bot_message(text=message, chat_id=chat_id)


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
    return send_admin_alert_message(_trim_message(message))


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
    return send_admin_alert_message(_trim_message(message))
